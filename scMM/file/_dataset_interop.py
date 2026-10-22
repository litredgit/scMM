"""Access, persistence, annotation, and AnnData interoperability methods."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from anndata import AnnData

from ..util.annotation import SDFMzSearcher


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
        from ._dataset_persistence import save_directory

        return save_directory(
            root_path, self.get_name(), self.file_meta, _dataset_frames(self), overwrite=overwrite
        )

    def to_anndata(self) -> AnnData:
        """Return an AnnData copy with stable cell and feature identifiers."""
        from ._anndata_interop import to_anndata

        return to_anndata(self)

    @classmethod
    def from_anndata(cls, adata: AnnData, *, name="dataset", ref_mz=None):
        """Import processed data, retaining AnnData analysis artifacts for H5AD export."""
        from ._anndata_interop import anndata_state

        state, template = anndata_state(adata, name=name, ref_mz=ref_mz)
        obj = object.__new__(cls)
        obj._apply_state(state)
        obj._anndata_template = template
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
                if (
                    isinstance(updated[key].dtype, pd.CategoricalDtype)
                    and pd.api.types.is_scalar(value)
                    and not pd.isna(value)
                    and value not in updated[key].cat.categories
                ):
                    updated[key] = updated[key].cat.add_categories([value])
                updated.loc[updated["source_file"] == source, key] = value
        changed = {
            key
            for key in updated
            if key not in self.peak_meta or not updated[key].equals(self.peak_meta[key])
        }
        if not changed:
            return self
        from ..util.lifecycle import (
            invalidate_observation_embeddings,
            invalidate_observation_reports,
        )
        from ._dataset_candidates import commit_candidate, prepare_candidate

        candidate = prepare_candidate(self, data=self.data, peak_meta=updated, invalidate=False)
        template = getattr(self, "_anndata_template", None)
        if template is not None:
            template = template.copy()
            removed = invalidate_observation_embeddings(template, changed)
            changed.update(removed)
            invalidate_observation_reports(template, changed)
            candidate["peak_meta"] = candidate["peak_meta"].drop(
                columns=list(removed), errors="ignore"
            )
            candidate["_anndata_template"] = template
        commit_candidate(self, candidate)
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
    from ._dataset_candidates import validate_axes

    validate_axes(
        dataset.data,
        dataset.peak_meta,
        dataset.feature_meta,
        getattr(dataset, "feature_snr", None),
        aligned_observations=hasattr(dataset, "_anndata_template"),
    )
