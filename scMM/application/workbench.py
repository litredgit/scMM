"""Session-local datasets, revision-bound results and reversible preprocessing."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import numpy as np
import pandas as pd
from anndata import read_h5ad
from sklearn.ensemble import IsolationForest
from sklearn.impute import KNNImputer, SimpleImputer

from scMM.analysis import SupervisedAnalyzer, differential_features
from scMM.analysis.embedding import reduce_dimension
from scMM.analysis.quality import quality_metrics
from scMM.analysis.statistics import feature_correlation_network, marker_features
from scMM.file.data import CyESIData
from scMM.util.normalize import normalize


def dense(matrix):
    return matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)


def read_dataset(storage, label, selected_path, *, trust_pickle=False):
    """Read only server-native paths within a configured storage root.

    Legacy directories may contain executable pickle data: the UI must obtain
    explicit trust confirmation. Child-file symlinks cannot escape the root.
    """
    path = storage.resolve(label, selected_path)
    if path.is_file() and path.suffix.lower() == ".h5ad":
        return read_h5ad(path)
    if path.is_dir() and (path / ".meta").is_file():
        for name in (
            ".meta",
            "data.pkl",
            "peak_meta.pkl",
            "feature_meta.pkl",
            "feature_snr.pkl",
            "data.csv",
            "peak_meta.csv",
            "feature_meta.csv",
            "feature_snr.csv",
        ):
            child = path / name
            if child.exists() or child.is_symlink():
                storage.resolve(label, child)
                if child.suffix == ".pkl" and not trust_pickle:
                    raise PermissionError("Legacy pickle data requires explicit trust confirmation")
        return CyESIData.load_from_processed(path).to_anndata()
    raise ValueError("Select a processed result directory or an .h5ad file")


class AnalysisWorkspace:
    """One dataset per session. Changes are transactional and invalidate results.

    X contains the active preprocessing version. Layers preserve input and every
    committed transformation on the current axes. Reset restores the session's
    entire initial dataset, including rows/columns removed by filtering.
    """

    def __init__(self):
        self.data = None
        self._original = None
        self.dataset_id = ""
        self.revision = 0
        self.source = ""
        self.results = {}

    @property
    def token(self):
        return self.dataset_id, self.revision

    def require_data(self):
        if self.data is None:
            raise ValueError("Load a processed dataset first")
        return self.data

    def replace(self, data, *, source=""):
        candidate = data.copy()
        self._validate(candidate)
        metadata = candidate.uns.setdefault("scmm_workbench", {})
        if not isinstance(metadata, dict):
            raise ValueError("invalid scmm_workbench metadata")
        if metadata.get("schema_version", 1) != 1:
            raise ValueError("unsupported scmm_workbench schema version")
        metadata["schema_version"] = 1
        if "original_layer" not in metadata:
            layer = self._layer_key(candidate, "input")
            candidate.layers[layer] = candidate.X.copy()
            metadata["original_layer"] = layer
        if metadata["original_layer"] not in candidate.layers:
            raise ValueError("preprocessing input layer is missing")
        metadata.setdefault("history_json", "[]")
        # Validate serialized history before replacing a usable session.
        if not isinstance(json.loads(metadata["history_json"]), list):
            raise ValueError("invalid preprocessing history")
        self.dataset_id = uuid4().hex
        self.revision = 0
        self.source = str(source)
        self.data = candidate
        self._original = candidate.copy()
        self.results.clear()

    @staticmethod
    def _validate(data):
        if min(data.shape) < 1:
            raise ValueError("dataset must have at least one observation and one feature")
        if not data.obs_names.is_unique or not data.var_names.is_unique:
            raise ValueError("observation and feature identifiers must be unique")
        if not np.isfinite(dense(data.X)).all():
            raise ValueError("dataset X must contain finite values")

    @staticmethod
    def _layer_key(data, operation):
        number = 0
        while f"scmm_{operation}_{number}" in data.layers:
            number += 1
        return f"scmm_{operation}_{number}"

    @staticmethod
    def _clear_derived(data):
        metadata = data.uns.setdefault("scmm_workbench", {})
        for column in metadata.get("derived_obs", []):
            if column in data.obs:
                del data.obs[column]
        metadata["derived_obs"] = []
        for mapping in (data.obsm, data.obsp, data.varm, data.varp):
            mapping.clear()
        for key in list(data.uns):
            if key.endswith(("_params", "_qc")):
                del data.uns[key]

    def _commit(self, candidate, operation, parameters, *, clear_derived=True, save_layer=True):
        self._validate(candidate)
        if clear_derived:
            self._clear_derived(candidate)
        metadata = candidate.uns.setdefault("scmm_workbench", {})
        history = json.loads(metadata.get("history_json", "[]"))
        layer = ""
        if save_layer:
            layer = self._layer_key(candidate, operation)
            candidate.layers[layer] = candidate.X.copy()
        history.append(
            {
                "operation": operation,
                "parameters": parameters,
                "layer": layer,
                "dataset_id": self.dataset_id,
                "revision": self.revision + 1,
                "shape": list(candidate.shape),
                "at": datetime.now(UTC).isoformat(),
            }
        )
        metadata["history_json"] = json.dumps(history, ensure_ascii=False)
        self.data = candidate
        self.revision += 1
        if clear_derived:
            self.results.clear()
        else:
            # Additive embeddings/annotations do not alter existing analysis inputs.
            self.results = {key: (self.token, value) for key, (_, value) in self.results.items()}

    def normalize(self, method):
        candidate = self.require_data().copy()
        candidate.X = normalize(dense(candidate.X), method=method)
        self._commit(candidate, "normalize", {"method": method})

    def impute(self, method="median"):
        candidate = self.require_data().copy()
        if method not in {"median", "mean", "knn"}:
            raise ValueError("imputation must be median, mean or knn")
        estimator = (
            KNNImputer(missing_values=0, keep_empty_features=True)
            if method == "knn"
            else SimpleImputer(strategy=method, missing_values=0, keep_empty_features=True)
        )
        candidate.X = estimator.fit_transform(dense(candidate.X))
        self._commit(candidate, "impute", {"method": method, "missing_values": 0})

    def filter(self, *, min_total=0.0, min_detected=0, min_feature_fraction=0.0):
        data = self.require_data()
        if (
            not np.isfinite([min_total, min_detected, min_feature_fraction]).all()
            or min_total < 0
            or min_detected < 0
            or not 0 <= min_feature_fraction <= 1
        ):
            raise ValueError("invalid QC filter thresholds")
        X = dense(data.X)
        rows = (X.sum(axis=1) >= min_total) & ((X > 0).sum(axis=1) >= min_detected)
        if not rows.any():
            raise ValueError("QC filter would remove every observation")
        columns = (X[rows] > 0).mean(axis=0) >= min_feature_fraction
        candidate = data[rows, columns].copy()
        self._commit(
            candidate,
            "filter",
            {
                "min_total": min_total,
                "min_detected": min_detected,
                "min_feature_fraction": min_feature_fraction,
            },
        )

    def remove_outliers(self, contamination=0.05, random_state=42):
        data = self.require_data()
        if not 0 < contamination <= 0.5:
            raise ValueError("contamination must be within (0, 0.5]")
        keep = (
            IsolationForest(contamination=contamination, random_state=random_state).fit_predict(
                dense(data.X)
            )
            == 1
        )
        self._commit(
            data[keep].copy(),
            "outliers",
            {"contamination": contamination, "random_state": random_state},
        )

    def restore(self, layer):
        candidate = self.require_data().copy()
        candidate.X = candidate.layers[layer].copy()
        self._commit(candidate, "restore", {"layer": layer})

    def reset(self):
        self.require_data()
        self._commit(self._original.copy(), "reset", {}, clear_derived=True)

    def put_result(self, name, value, token):
        if token != self.token:
            raise RuntimeError("Dataset changed; discard stale analysis result")
        self.results[name] = (token, value)

    def result(self, name):
        token, value = self.results[name]
        if token != self.token:
            raise RuntimeError("Stale analysis result")
        return value

    def qc(self):
        return quality_metrics(self.require_data())

    def reduce(self, method, *, store_key, **options):
        candidate = self.require_data().copy()
        if store_key in candidate.obsm:
            raise ValueError("Embedding key already exists; choose a new key")
        reduce_dimension(candidate, method, store_key=store_key, **options)
        self._commit(
            candidate,
            "reduce",
            {"method": method, "store_key": store_key, **options},
            clear_derived=False,
            save_layer=False,
        )

    def cluster(
        self, method, *, use_rep="X", key="clusters", n_clusters=3, n_neighbors=15, random_state=42
    ):
        from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans

        candidate = self.require_data().copy()
        if key in candidate.obs:
            raise ValueError("Observation key already exists; choose a new key")
        X = dense(candidate.X if use_rep == "X" else candidate.obsm[use_rep])
        if method == "kmeans":
            labels = KMeans(
                n_clusters=n_clusters, random_state=random_state, n_init=10
            ).fit_predict(X)
        elif method == "hierarchical":
            labels = AgglomerativeClustering(n_clusters=n_clusters).fit_predict(X)
        elif method == "dbscan":
            labels = DBSCAN().fit_predict(X)
        elif method in {"leiden", "louvain"}:
            from scMM.plot._engine_clustering import _build_neighbor_edges, _cluster_graph

            if not 1 <= n_neighbors < len(X):
                raise ValueError("n_neighbors must be below n_obs")
            labels = _cluster_graph(
                method, len(X), _build_neighbor_edges(X, n_neighbors), 1.0, random_state, {}
            )
        else:
            raise ValueError("unsupported clustering method")
        candidate.obs[key] = pd.Categorical(labels.astype(str))
        metadata = candidate.uns["scmm_workbench"]
        metadata["derived_obs"] = [*metadata.get("derived_obs", []), key]
        self._commit(
            candidate,
            "cluster",
            {
                "method": method,
                "source": use_rep,
                "key": key,
                "n_clusters": n_clusters,
                "n_neighbors": n_neighbors,
                "random_state": random_state,
            },
            clear_derived=False,
            save_layer=False,
        )

    def differential(self, group_key, group_a, group_b, *, method="mannwhitney", layer=None):
        self.results.pop("differential", None)
        token = self.token
        table = differential_features(
            self.require_data(), group_key, group_a, group_b, method=method, layer=layer
        )
        result = {
            "table": table,
            "group_key": group_key,
            "group_a": str(group_a),
            "group_b": str(group_b),
            "method": method,
            "layer": layer,
        }
        self.put_result("differential", result, token)
        return result

    def train(self, label_key, *, group_key=None, layer=None, model="logistic", **options):
        self.results.pop("supervised", None)
        self.results.pop("shap", None)
        token = self.token
        analyzer = SupervisedAnalyzer(
            self.require_data(),
            label_key,
            group_key=group_key,
            layer=layer,
            random_state=options.pop("random_state", 42),
        )
        analyzer.evaluate(model, **options)
        self.put_result("supervised", analyzer, token)
        return analyzer

    def markers(self, group_key, *, method="mannwhitney", layer=None):
        self.results.pop("markers", None)
        token = self.token
        result = {"group_key": group_key, "method": method, "layer": layer}
        result["table"] = marker_features(
            self.require_data(), group_key, method=method, layer=layer
        )
        self.put_result("markers", result, token)
        return result

    def network(self, **options):
        self.results.pop("network", None)
        token = self.token
        graph, corr = feature_correlation_network(self.require_data(), **options)
        table = pd.DataFrame(
            [(a, b, attrs["correlation"]) for a, b, attrs in graph.edges(data=True)],
            columns=["source", "target", "correlation"],
        )
        result = {"graph": graph, "correlation": corr, "table": table, "parameters": options}
        self.put_result("network", result, token)
        return result

    def explain_shap(self, **options):
        self.results.pop("shap", None)
        token = self.token
        analyzer = self.result("supervised")
        explanation = analyzer.explain_shap(**options)
        values = np.abs(explanation.values)
        if values.ndim not in (2, 3):
            raise ValueError("Unsupported SHAP value shape")
        importance = values.mean(axis=(0, 2) if values.ndim == 3 else 0)
        table = pd.DataFrame({"feature_id": analyzer.feature_names, "mean_abs_shap": importance})
        result = {
            "table": table.sort_values("mean_abs_shap", ascending=False),
            "parameters": options,
            "obs_names": analyzer.shap_obs_names_.tolist(),
        }
        self.put_result("shap", result, token)
        return result

    def save_latent(self, key):
        analyzer = self.result("supervised")
        candidate = self.require_data().copy()
        if key in candidate.obsm or f"{key}_split" in candidate.obs:
            raise ValueError("Latent output key already exists")
        if not key or "/" in key:
            raise ValueError("Invalid output key")
        scores = analyzer.latent_scores().reindex(candidate.obs_names)
        candidate.obsm[key] = scores.to_numpy()
        split = pd.Series("unlabeled", index=candidate.obs_names)
        split.loc[analyzer.train_obs_names_] = "train"
        split.loc[analyzer.test_obs_names_] = "test"
        candidate.obs[f"{key}_split"] = pd.Categorical(split)
        metadata = candidate.uns["scmm_workbench"]
        metadata["derived_obs"] = [*metadata.get("derived_obs", []), f"{key}_split"]
        self._commit(
            candidate,
            "latent",
            {"model": analyzer.model_name_, "store_key": key},
            clear_derived=False,
            save_layer=False,
        )
        self.put_result("supervised", analyzer, self.token)

    def save_h5ad(self, storage, label, directory, filename):
        data = self.require_data()
        if (
            Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or not filename.lower().endswith(".h5ad")
        ):
            raise ValueError("Use a simple filename ending in .h5ad")
        folder = storage.resolve_output_directory(label, directory)
        folder.mkdir(exist_ok=True)
        target = folder / filename
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        snapshot = data.copy()
        snapshot.uns["scmm_workbench"].update(
            dataset_id=self.dataset_id, revision=self.revision, source=self.source
        )
        reports = {}
        for name in ("markers", "network", "shap"):
            if name in self.results:
                result = self.result(name)
                reports[name] = {
                    **{
                        k: v
                        for k, v in result.items()
                        if k not in {"table", "graph", "correlation"}
                    },
                    "table": result["table"].to_dict(orient="records"),
                }
                if name == "network":
                    reports[name]["nodes"] = list(result["graph"].nodes)
        if "differential" in self.results:
            result = self.result("differential")
            reports["differential"] = {
                **{key: value for key, value in result.items() if key != "table"},
                "table": result["table"].to_dict(orient="records"),
            }
        if "supervised" in self.results:
            analyzer = self.result("supervised")
            reports["supervised"] = {
                "diagnostics": analyzer.result_,
                "train_obs": analyzer.train_obs_names_.tolist(),
                "test_obs": analyzer.test_obs_names_.tolist(),
                "classes": analyzer.classes_.tolist(),
            }
        snapshot.uns["scmm_workbench"]["reports_json"] = json.dumps(
            reports, default=lambda v: v.tolist()
        )
        with NamedTemporaryFile(dir=folder, suffix=".h5ad", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            snapshot.write_h5ad(temporary)
            target.hardlink_to(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def history(self):
        metadata = self.require_data().uns["scmm_workbench"]
        return deepcopy(json.loads(metadata["history_json"]))
