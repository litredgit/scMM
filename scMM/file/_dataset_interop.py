"""Access, persistence, annotation, and AnnData interoperability methods."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from anndata import AnnData

from ..util.annotation import SDFMzSearcher

logger = logging.getLogger(__name__)


class DatasetInteropMixin:
    """Provide accessors and external representations for a dataset."""

    def __len__(self) -> int:
        return self.data.shape[0]

    def __getitem__(self, key):
        if self.data.shape[1] == 0:
            raise KeyError("Dataset has no features")
        target = float(key)
        index = np.abs(self.data.columns.values.astype(float) - target).argmin()
        return self.data.iloc[:, index].values

    def get_name(self) -> str:
        """Return the human-readable dataset name."""
        return str(self.file_meta.get("name", "unnamed"))

    def get_labels(self, mapping: dict | None = None) -> np.ndarray:
        """Return per-cell labels, optionally replacing them with ``mapping``."""
        if "label" not in self.peak_meta:
            raise KeyError("peak_meta does not contain a 'label' column")
        labels = self.peak_meta["label"]
        if mapping is not None:
            labels = labels.map(lambda value: mapping.get(value, value))
        return labels.to_numpy()

    def save(self, root_path: str | Path, *, overwrite: bool = False) -> Path:
        """Save the dataset below ``root_path`` and return its directory."""
        _validate_metadata_dimensions(self)
        result_path = _create_result_directory(root_path, self.get_name(), overwrite)
        logger.info("Saving processed data to %s", result_path)
        with (result_path / ".meta").open("w", encoding="utf-8") as handle:
            json.dump(self.file_meta, handle, ensure_ascii=False, indent=2)
        for name, frame in _dataset_frames(self):
            frame.to_pickle(result_path / f"{name}.pkl")
            frame.to_csv(result_path / f"{name}.csv")
        if not hasattr(self, "feature_snr"):
            # Remove only stale optional artifacts when explicitly overwriting this dataset.
            for name in ("feature_snr.pkl", "feature_snr.csv"):
                (result_path / name).unlink(missing_ok=True)
        return result_path

    def to_anndata(self) -> AnnData:
        """Return an AnnData copy with stable cell and feature identifiers."""
        _validate_metadata_dimensions(self)
        observations = self.peak_meta.copy()
        if "source_index" not in observations:
            observations.insert(0, "source_index", self.peak_meta.index.astype(str))
        observations.index = pd.Index(
            [f"cell_{index}" for index in range(len(observations))],
            name="cell_id",
        )
        variables = self.feature_meta.reindex(self.data.columns).copy()
        variables.index = pd.Index(self.data.columns.astype(str), name="feature_id")
        template = getattr(self, "_anndata_template", None)
        if template is None:
            adata = AnnData(X=self.data.values.copy(), obs=observations, var=variables)
            adata.raw = adata.copy()
        else:
            # Retain imported embeddings, layers, graphs and raw across axis subsetting.
            rows = template.obs_names.get_indexer(self.data.index.astype(str))
            masses = pd.Index(template.var["mz"].to_numpy(dtype=float))
            columns = masses.get_indexer(self.data.columns.astype(float))
            if (rows < 0).any() or (columns < 0).any():
                raise ValueError("imported AnnData axes no longer match dataset")
            adata = template[rows, columns].copy()
            adata.X = self.data.to_numpy(copy=True)
            observations.index = template.obs_names[rows]
            variables.index = template.var_names[columns]
            adata.obs, adata.var = observations, variables
        adata.uns["scmm"] = {
            "schema_version": 1,
            "file_meta_json": json.dumps(self.file_meta, ensure_ascii=False),
        }
        if hasattr(self, "feature_snr"):
            adata.layers["feature_snr"] = self.feature_snr.to_numpy(copy=True)
        return adata

    @classmethod
    def from_anndata(cls, adata: AnnData, *, name="dataset", ref_mz=None):
        """Import processed data, retaining AnnData analysis artifacts for H5AD export."""
        from ._dataset_loading import DatasetState

        data = adata.copy()
        if not data.obs_names.is_unique:
            raise ValueError("AnnData observation names must be unique")
        masses = np.asarray(data.var.get("mz", data.var_names), dtype=float)
        if (
            not np.isfinite(masses).all()
            or (masses <= 0).any()
            or len(np.unique(masses)) != len(masses)
        ):
            raise ValueError("AnnData requires unique positive finite feature m/z values")
        data.var["mz"] = masses
        frame = data.to_df()
        frame.columns = masses
        var = data.var.copy()
        var.index = pd.Index(masses, name="feature_id")
        payload = data.uns.get("scmm", {})
        if payload.get("schema_version", 1) != 1:
            raise ValueError("unsupported scMM H5AD schema version")
        metadata = json.loads(payload.get("file_meta_json", "{}"))
        metadata.setdefault("name", name)
        if ref_mz is not None:
            metadata["ref_mz"] = ref_mz
        snr = data.layers.get("feature_snr")
        if snr is not None:
            snr = snr.toarray() if hasattr(snr, "toarray") else np.asarray(snr)
            snr = pd.DataFrame(snr, index=frame.index, columns=frame.columns)
        obj = object.__new__(cls)
        obj._apply_state(
            DatasetState(frame, data.obs.copy(), metadata, metadata.get("ref_mz"), var, snr)
        )
        obj._anndata_template = data
        return obj

    @classmethod
    def read_h5ad(cls, path):
        from anndata import read_h5ad

        return cls.from_anndata(read_h5ad(path), name=Path(path).stem)

    def save_h5ad(self, path, *, overwrite=False, compression="gzip") -> Path:
        """Export a separate H5AD artifact without changing legacy directory save()."""
        from tempfile import NamedTemporaryFile

        target = Path(path).expanduser()
        if target.suffix.lower() != ".h5ad":
            raise ValueError("H5AD output must use the .h5ad suffix")
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, suffix=".h5ad", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            self.to_anndata().write_h5ad(temporary, compression=compression)
            if overwrite:
                temporary.replace(target)
            else:
                # An atomic link protects against a concurrent writer after the existence check.
                target.hardlink_to(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def assign_source_metadata(self, metadata_by_file, *, overwrite=False):
        """Attach sample metadata by source filename with explicit collision policy."""
        if "source_file" not in self.peak_meta:
            raise KeyError("source_file is required for assigning sample metadata")
        updated = self.peak_meta.copy()
        for source, fields in metadata_by_file.items():
            for key, value in fields.items():
                if key == "source_file" or (key in self.peak_meta and not overwrite):
                    raise ValueError(f"metadata column already exists: {key}")
                if key not in updated:
                    updated[key] = pd.Series(
                        [None] * len(updated), index=updated.index, dtype=object
                    )
                updated.loc[updated["source_file"] == source, key] = value
        self.peak_meta = updated
        return self

    def get_annotation(
        self,
        sdf_path: str | Path,
        ppm_tol: float,
        search_mode: Literal["pos", "neg", "both"] = "pos",
        adducts_pos: dict | None = None,
        adducts_neg: dict | None = None,
        **kwargs,
    ):
        """Search an SDF database for the dataset's feature masses."""
        searcher = SDFMzSearcher(
            sdf_path=sdf_path,
            adducts_pos=adducts_pos,
            adducts_neg=adducts_neg,
        )
        return searcher.search(
            mz=self.data.columns.astype(float),
            ppm_tol=ppm_tol,
            mode=search_mode,
            **kwargs,
        )


def _create_result_directory(root_path, dataset_name: str, overwrite: bool) -> Path:
    root = Path(root_path).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    safe_name = Path(dataset_name).name
    if safe_name in {"", ".", ".."}:
        raise ValueError(f"Invalid dataset name: {safe_name!r}")
    result_path = root / safe_name
    result_path.mkdir(exist_ok=overwrite)
    return result_path


def _dataset_frames(dataset):
    frames = [
        ("data", dataset.data),
        ("peak_meta", dataset.peak_meta),
        ("feature_meta", dataset.feature_meta),
    ]
    if hasattr(dataset, "feature_snr"):
        frames.append(("feature_snr", dataset.feature_snr))
    return frames


def _validate_metadata_dimensions(dataset) -> None:
    if len(dataset.peak_meta) != len(dataset.data):
        raise ValueError("peak_meta row count must match data row count")
    if len(dataset.feature_meta) != dataset.data.shape[1]:
        raise ValueError("feature_meta row count must match data column count")
    if hasattr(dataset, "feature_snr") and (
        dataset.feature_snr.shape != dataset.data.shape
        or not dataset.feature_snr.columns.equals(dataset.data.columns)
        or not dataset.feature_snr.index.equals(dataset.data.index)
    ):
        raise ValueError("feature_snr axes must match data axes")
