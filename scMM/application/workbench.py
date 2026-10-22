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

from scMM.analysis import SupervisedAnalyzer, differential_features
from scMM.analysis.embedding import reduce_dimension
from scMM.analysis.quality import quality_metrics
from scMM.analysis.statistics import feature_correlation_network, marker_features
from scMM.file.data import CyESIData
from scMM.util.intensity import intensity_states, transformed_state, write_intensity_states
from scMM.util.normalize import normalize

from .result_catalog import metadata_dependencies, serialize_reports, stale_metadata_results


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
        self._result_identities = {}

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
        states = intensity_states(candidate)
        metadata["schema_version"] = 1
        if "original_layer" not in metadata:
            layer = self._layer_key(candidate, "input")
            candidate.layers[layer] = candidate.X.copy()
            metadata["original_layer"] = layer
            states[layer] = states["X"]
        if metadata["original_layer"] not in candidate.layers:
            raise ValueError("preprocessing input layer is missing")
        metadata.setdefault("history_json", "[]")
        # Validate serialized history before replacing a usable session.
        if not isinstance(json.loads(metadata["history_json"]), list):
            raise ValueError("invalid preprocessing history")
        write_intensity_states(candidate, states)
        self.dataset_id = uuid4().hex
        self.revision = 0
        self.source = str(source)
        self.data = candidate
        self._original = candidate.copy()
        self.results.clear()
        self._result_identities.clear()

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
        from scMM.util.lifecycle import invalidate_derived

        invalidate_derived(data)

    def _commit(self, candidate, operation, parameters, *, clear_derived=True, save_layer=True):
        self._validate(candidate)
        states = intensity_states(candidate)
        if operation == "restore":
            states["X"] = states.get(parameters["layer"], "unknown")
        elif operation != "reset":
            states["X"] = transformed_state(states["X"], operation, parameters)
        # Reset's candidate is the full baseline, including its actual X lineage.
        if clear_derived:
            self._clear_derived(candidate)
        metadata = candidate.uns.setdefault("scmm_workbench", {})
        history = json.loads(metadata.get("history_json", "[]"))
        layer = ""
        if save_layer:
            layer = self._layer_key(candidate, operation)
            candidate.layers[layer] = candidate.X.copy()
            states[layer] = states["X"]
        write_intensity_states(candidate, states)
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
            self._result_identities.clear()
        else:
            # Additive embeddings/annotations do not alter existing analysis inputs.
            self.results = {key: (self.token, value) for key, (_, value) in self.results.items()}

    def normalize(self, method, *, scale=1.0, axis=None, reference="median", pseudo=1e-6):
        from scMM.analysis.preprocessing import normalization_options

        params = normalization_options(
            method, scale=scale, axis=axis, reference=reference, pseudo=pseudo
        )
        candidate = self.require_data().copy()
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                candidate.X = normalize(dense(candidate.X), method=method, norm_kwargs=params)
        except FloatingPointError as exc:
            raise ValueError("normalization is undefined for these values and parameters") from exc
        self._commit(candidate, "normalize", {"method": method, "effective_parameters": params})

    def impute(self, method="median", *, n_neighbors=5, weights="uniform"):
        from scMM.analysis.preprocessing import imputation_estimator

        candidate = self.require_data().copy()
        estimator, params = imputation_estimator(method, candidate.n_obs, n_neighbors, weights)
        candidate.X = estimator.fit_transform(dense(candidate.X))
        self._commit(
            candidate,
            "impute",
            {"method": method, "missing_values": 0, "effective_parameters": params},
        )

    def filter(self, *, min_total=0.0, min_detected=0.2, min_feature_fraction=0.0):
        data = self.require_data()
        if (
            not np.isfinite([min_total, min_detected, min_feature_fraction]).all()
            or min_total < 0
            or not 0 <= min_detected <= 1
            or not 0 <= min_feature_fraction <= 1
        ):
            raise ValueError("invalid QC filter thresholds")
        X = dense(data.X)
        rows = (X.sum(axis=1) >= min_total) & ((X > 0).mean(axis=1) >= min_detected)
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

    def subset(self, *, cell_ids=None, feature_ids=None):
        data = self.require_data()
        if cell_ids is None and feature_ids is None:
            raise ValueError("select stable cell IDs or feature IDs explicitly")

        def selected(values, index, name):
            if values is None:
                return list(index)
            if not isinstance(values, (list, tuple)) or not values:
                raise ValueError(f"{name} must be a non-empty list of stable IDs")
            if any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique string IDs")
            missing = set(values) - set(index)
            if missing:
                raise ValueError(f"{name} contains unknown IDs")
            return list(values)

        rows = selected(cell_ids, data.obs_names, "cell_ids")
        columns = selected(feature_ids, data.var_names, "feature_ids")
        candidate = data[rows, columns].copy()
        self._commit(
            candidate,
            "subset",
            {
                "cell_ids": cell_ids,
                "feature_ids": feature_ids,
                "cells": len(rows),
                "features": len(columns),
            },
        )

    def remove_outliers(
        self,
        contamination=0.05,
        random_state=42,
        *,
        n_estimators=100,
        max_samples="auto",
        max_features=1.0,
        bootstrap=False,
    ):
        from scMM.analysis.preprocessing import outlier_options

        data = self.require_data()
        params = outlier_options(
            data.shape,
            contamination=contamination,
            random_state=random_state,
            n_estimators=n_estimators,
            max_samples=max_samples,
            max_features=max_features,
            bootstrap=bootstrap,
        )
        keep = IsolationForest(**params).fit_predict(dense(data.X)) == 1
        self._commit(data[keep].copy(), "outliers", {**params, "effective_parameters": params})

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
        previous = self.results.get(name)
        if previous is None or previous[1] is not value or name not in self._result_identities:
            self._result_identities[name] = uuid4().hex
        self.results[name] = (token, value)

    def result(self, name):
        token, value = self.results[name]
        if token != self.token:
            raise RuntimeError("Stale analysis result")
        return value

    def sync_sample_metadata(self, samples, mapping=None, source_key="sample"):
        """Stage current/reset metadata; return fields changed on current data."""
        if self.data is None:
            return set()
        lookup = {s["id"]: s for s in samples}
        names = {}
        for sample in samples:
            names.setdefault(sample["name"], []).append(sample["id"])
        current_changes, baseline_changes = set(), set()
        current = self.data.copy()
        baseline = self._original.copy() if self._original is not None else None
        for data, changed in ((current, current_changes), (baseline, baseline_changes)):
            if data is None:
                continue
            ids = (
                data.obs["sample_id"].astype(str).copy()
                if "sample_id" in data.obs
                else pd.Series("", index=data.obs_names)
            )
            if source_key in data.obs:
                for index, name in data.obs[source_key].astype(str).items():
                    if ids.loc[index] not in lookup:
                        candidates = names.get(name, [])
                        ids.loc[index] = (mapping or {}).get(
                            name, candidates[0] if len(candidates) == 1 else ""
                        )
            valid = ids.isin(lookup)
            if not valid.any():
                continue
            if "sample_id" not in data.obs or not data.obs["sample_id"].astype(str).equals(ids):
                changed.add("sample_id")
                data.obs["sample_id"] = ids
            for column, key in (
                ("sample", "name"),
                ("group", "group"),
                ("subject", "subject"),
                ("batch", "batch"),
            ):
                previous = (
                    data.obs[column].astype(str)
                    if column in data.obs
                    else pd.Series("", index=data.obs_names)
                )
                update_mask = valid & ids.map(
                    lambda identity, key=key: (
                        key not in lookup.get(identity, {}).get("metadata_unresolved", [])
                    )
                )
                values = ids.loc[update_mask].map(
                    lambda identity, key=key: str(lookup[identity][key])
                )
                if column not in data.obs or not previous.loc[update_mask].equals(values):
                    changed.add(column)
                    data.obs[column] = previous
                    data.obs.loc[update_mask, column] = values
        if not current_changes and not baseline_changes:
            return set()
        from scMM.util.lifecycle import (
            invalidate_observation_embeddings,
            invalidate_observation_reports,
        )

        for data, changed in ((current, current_changes), (baseline, baseline_changes)):
            if data is not None:
                changed.update(invalidate_observation_embeddings(data, changed))
                invalidate_observation_reports(data, changed)
        values = {name: value for name, (_, value) in self.results.items()}
        stale = stale_metadata_results(values, current_changes)
        remaining = {name: value for name, value in values.items() if name not in stale}
        self.data, self._original = current, baseline
        self.revision += 1
        self.results = {key: (self.token, value) for key, value in remaining.items()}
        self._result_identities = {
            key: value for key, value in self._result_identities.items() if key in remaining
        }
        return current_changes

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
        self,
        method,
        *,
        use_rep="X",
        key="clusters",
        n_clusters=3,
        n_neighbors=15,
        random_state=42,
        eps=0.5,
        min_samples=5,
        resolution=1.0,
        n_init=10,
        max_iter=300,
        tol=1e-4,
        linkage="ward",
        metric="euclidean",
        n_iterations=2,
        threshold=1e-7,
        max_level=None,
    ):
        from scMM.analysis.clustering import cluster_matrix

        candidate = self.require_data().copy()
        if key in candidate.obs:
            raise ValueError("Observation key already exists; choose a new key")
        X = dense(candidate.X if use_rep == "X" else candidate.obsm[use_rep])
        labels, effective = cluster_matrix(
            X,
            method,
            n_clusters=n_clusters,
            n_neighbors=n_neighbors,
            random_state=random_state,
            eps=eps,
            min_samples=min_samples,
            resolution=resolution,
            n_init=n_init,
            max_iter=max_iter,
            tol=tol,
            linkage=linkage,
            metric=metric,
            n_iterations=n_iterations,
            threshold=threshold,
            max_level=max_level,
        )
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
                "effective_parameters": effective,
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
        token = self.token
        analyzer = SupervisedAnalyzer(
            self.require_data(),
            label_key,
            group_key=group_key,
            layer=layer,
            random_state=options.pop("random_state", 42),
        )
        analyzer.label_key = label_key
        analyzer.group_key = group_key
        analyzer.evaluate(model, **options)
        self.results.pop("shap", None)
        self.put_result("supervised", analyzer, token)
        return analyzer

    def markers(self, group_key, *, method="mannwhitney", layer=None):
        self.results.pop("markers", None)
        token = self.token
        result = {"group_key": group_key, "method": method, "layer": layer}
        if method == "classifier":
            from scMM.analysis.markers import classifier_markers

            result["table"] = classifier_markers(self.require_data(), group_key, layer=layer)
        else:
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
            "parameters": {**options, **analyzer.shap_parameters_},
            "output_space": analyzer.shap_output_space_,
            "background_obs": analyzer.shap_background_obs_.tolist(),
            "obs_names": analyzer.shap_obs_names_.tolist(),
            "values": explanation.values,
            "base_values": explanation.base_values,
            "data": explanation.data,
            "feature_names": list(analyzer.feature_names),
            "classes": analyzer.classes_.tolist(),
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
        fields = sorted(metadata_dependencies("supervised", analyzer, {}))
        rules = json.loads(metadata.get("latent_dependencies_json", "{}"))
        if not isinstance(rules, dict):
            raise ValueError("invalid latent dependency metadata")
        rules[key] = fields
        metadata["latent_dependencies_json"] = json.dumps(rules)
        self._commit(
            candidate,
            "latent",
            {
                "model": analyzer.model_name_,
                "store_key": key,
                "label_key": analyzer.label_key,
                "group_key": analyzer.group_key,
                "observation_dependencies": fields,
            },
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
        reports = serialize_reports(
            {name: self.result(name) for name in self.results}, identities=self._result_identities
        )
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
