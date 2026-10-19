"""Explicit service-only state codec. No pickle or dynamically selected constructors."""

import importlib.metadata
from pathlib import Path

import numpy as np
import pandas as pd
from anndata import AnnData, read_h5ad

from scMM.analysis.supervised import SupervisedAnalyzer

TRUSTED = {
    "scMM.analysis.supervised.PLSDAClassifier",
    "imblearn.pipeline.Pipeline",
    "imblearn.over_sampling._smote.base.SMOTE",
    "sklearn.tree._tree.Tree",
}


def versions():
    import hashlib

    from scMM.analysis import supervised

    return {
        **{
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "scikit-learn", "imbalanced-learn", "skops", "anndata")
        },
        "implementation": hashlib.sha256(Path(supervised.__file__).read_bytes()).hexdigest(),
    }


class StateCodec:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.counter = 0

    def artifact(self, suffix):
        self.counter += 1
        return self.directory / f"artifact-{self.counter:06d}{suffix}"

    def encode(self, value):
        if value is None or type(value) in (str, int, bool):
            return value
        if isinstance(value, np.generic):
            return self.encode(value.item())
        if isinstance(value, float):
            return value if np.isfinite(value) else {"@": "float", "value": repr(value)}
        if isinstance(value, Path):
            return {"@": "path", "value": str(value)}
        if isinstance(value, AnnData):
            path = self.artifact(".h5ad")
            value.write_h5ad(path)
            return {"@": "anndata", "file": path.name}
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                return {
                    "@": "object_array",
                    "shape": list(value.shape),
                    "values": self.encode(value.tolist()),
                }
            path = self.artifact(".npy")
            np.save(path, value, allow_pickle=False)
            return {"@": "array", "file": path.name}
        if isinstance(value, pd.DataFrame):
            return {
                "@": "frame",
                "index": self.encode(value.index),
                "columns": self.encode(value.columns),
                "values": self.encode(value.to_numpy()),
                "dtypes": [str(v) for v in value.dtypes],
            }
        if isinstance(value, pd.Index):
            return {
                "@": "index",
                "values": self.encode(value.tolist()),
                "name": self.encode(value.name),
            }
        from .raw_preview import CellDetectionPreview

        if isinstance(value, CellDetectionPreview):
            from dataclasses import asdict

            return {"@": "detection", "value": self.encode(asdict(value))}
        if isinstance(value, SupervisedAnalyzer):
            import skops.io as sio

            attrs = {
                k: v for k, v in vars(value).items() if k not in {"model_", "shap_explanation_"}
            }
            path = self.artifact(".skops")
            sio.dump(value.model_, path)
            unknown = set(sio.get_untrusted_types(file=path))
            if unknown - TRUSTED:
                raise ValueError(f"Unaudited model types: {sorted(unknown - TRUSTED)}")
            restored = sio.load(path, trusted=sorted(unknown))
            before, after = (
                value.model_.predict_proba(value.X_test_),
                restored.predict_proba(value.X_test_),
            )
            if not np.array_equal(before, after):
                raise ValueError("Model restoration changes predictions")
            return {
                "@": "analyzer",
                "attrs": self.encode(attrs),
                "file": path.name,
                "versions": versions(),
                "verification": self.encode(before),
            }
        if isinstance(value, tuple):
            return {"@": "tuple", "values": [self.encode(v) for v in value]}
        if isinstance(value, list):
            return [self.encode(v) for v in value]
        if isinstance(value, dict):
            return {
                "@": "dict",
                "items": [[self.encode(k), self.encode(v)] for k, v in value.items()],
            }
        if type(value).__module__.startswith("networkx."):
            import networkx as nx

            return {"@": "graph", "value": self.encode(nx.node_link_data(value, edges="edges"))}
        raise ValueError(
            f"Unsupported recovery state: {type(value).__module__}.{type(value).__name__}"
        )

    def file(self, name):
        path = self.directory / name
        if Path(name).name != name or path.is_symlink() or not path.is_file():
            raise ValueError("Invalid recovery artifact")
        return path

    def decode(self, value):
        if isinstance(value, list):
            return [self.decode(v) for v in value]
        if not isinstance(value, dict):
            return value
        tag = value.get("@")
        if tag == "dict":
            return {self.decode(k): self.decode(v) for k, v in value["items"]}
        if tag == "float":
            return {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}[value["value"]]
        if tag == "path":
            return Path(value["value"])
        if tag == "array":
            return np.load(self.file(value["file"]), allow_pickle=False)
        if tag == "object_array":
            return np.asarray(self.decode(value["values"]), dtype=object).reshape(value["shape"])
        if tag == "index":
            return pd.Index(self.decode(value["values"]), name=self.decode(value["name"]))
        if tag == "frame":
            frame = pd.DataFrame(
                self.decode(value["values"]),
                index=self.decode(value["index"]),
                columns=self.decode(value["columns"]),
            )
            for name, dtype in zip(frame.columns, value["dtypes"], strict=True):
                frame[name] = frame[name].astype(dtype)
            return frame
        if tag == "anndata":
            return read_h5ad(self.file(value["file"]))
        if tag == "tuple":
            return tuple(self.decode(v) for v in value["values"])
        if tag == "graph":
            import networkx as nx

            return nx.node_link_graph(self.decode(value["value"]), edges="edges")
        if tag == "detection":
            from .raw_preview import CellDetectionPreview

            return CellDetectionPreview(**self.decode(value["value"]))
        if tag == "analyzer":
            import skops.io as sio

            if value["versions"] != versions():
                raise ValueError("Model recovery dependency/implementation version differs")
            path = self.file(value["file"])
            unknown = set(sio.get_untrusted_types(file=path))
            if unknown - TRUSTED:
                raise ValueError("Unaudited model recovery type")
            result = SupervisedAnalyzer.__new__(SupervisedAnalyzer)
            result.__dict__.update(self.decode(value["attrs"]))
            result.model_ = sio.load(path, trusted=sorted(unknown))
            if not np.array_equal(
                result.model_.predict_proba(result.X_test_), self.decode(value["verification"])
            ):
                raise ValueError("Restored model prediction verification failed")
            return result
        raise ValueError("Unknown recovery state type")
