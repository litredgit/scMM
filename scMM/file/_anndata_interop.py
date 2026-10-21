"""AnnData import/export policy, independent of directory persistence and mutation."""

import json

import numpy as np
import pandas as pd
from anndata import AnnData

from ..util.intensity import dataset_intensity_state, intensity_states, write_intensity_states
from ._dataset_candidates import validate_axes


def to_anndata(dataset) -> AnnData:
    """Return an AnnData copy with stable cell and feature identifiers."""
    validate_axes(
        dataset.data,
        dataset.peak_meta,
        dataset.feature_meta,
        getattr(dataset, "feature_snr", None),
        aligned_observations=hasattr(dataset, "_anndata_template"),
    )
    if not isinstance(dataset.file_meta, dict):
        raise ValueError("file_meta must be a mapping")
    observations = dataset.peak_meta.copy()
    if "source_index" not in observations:
        observations.insert(0, "source_index", dataset.peak_meta.index.astype(str))
    observations.index = pd.Index(
        [f"cell_{index}" for index in range(len(observations))],
        name="cell_id",
    )
    variables = dataset.feature_meta.reindex(dataset.data.columns).copy()
    variables.index = pd.Index(dataset.data.columns.astype(str), name="feature_id")
    template = getattr(dataset, "_anndata_template", None)
    if template is None:
        adata = AnnData(X=dataset.data.values.copy(), obs=observations, var=variables)
        adata.raw = adata.copy()
    else:
        # Retain imported embeddings, layers, graphs and raw across axis subsetting.
        rows = template.obs_names.get_indexer(dataset.data.index.astype(str))
        masses = pd.Index(template.var["mz"].to_numpy(dtype=float))
        columns = masses.get_indexer(dataset.data.columns.astype(float))
        if (rows < 0).any() or (columns < 0).any():
            raise ValueError("imported AnnData axes no longer match dataset")
        adata = template[rows, columns].copy()
        adata.X = dataset.data.to_numpy(copy=True)
        observations.index = template.obs_names[rows]
        variables.index = template.var_names[columns]
        adata.obs, adata.var = observations, variables
    adata.uns["scmm"] = {
        "schema_version": 1,
        "file_meta_json": json.dumps(dataset.file_meta, ensure_ascii=False),
    }
    if hasattr(dataset, "feature_snr"):
        adata.layers["feature_snr"] = dataset.feature_snr.to_numpy(copy=True)
    states = intensity_states(adata) if template is not None else {}
    states["X"] = dataset_intensity_state(dataset)
    write_intensity_states(adata, states)
    return adata


def anndata_state(adata, *, name="dataset", ref_mz=None):
    from ._dataset_loading import DatasetState

    if not adata.var_names.is_unique:
        raise ValueError("AnnData feature names must be unique")
    if not adata.obs_names.is_unique:
        raise ValueError("AnnData observation names must be unique")
    data = adata.copy()
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
    if not isinstance(payload, dict):
        raise ValueError("scmm H5AD metadata must be a mapping")
    if payload.get("schema_version", 1) != 1:
        raise ValueError("unsupported scMM H5AD schema version")
    try:
        metadata = json.loads(payload.get("file_meta_json", "{}"))
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid file_meta_json in scmm H5AD metadata") from exc
    if not isinstance(metadata, dict):
        raise ValueError("H5AD file metadata must be a mapping")
    metadata["intensity_state"] = intensity_states(data)["X"]
    metadata.setdefault("name", name)
    if ref_mz is not None:
        metadata["ref_mz"] = ref_mz
    snr = data.layers.get("feature_snr")
    if snr is not None:
        snr = snr.toarray() if hasattr(snr, "toarray") else np.asarray(snr)
        snr = pd.DataFrame(snr, index=frame.index, columns=frame.columns)
    validate_axes(frame, data.obs, var, snr, aligned_observations=True)
    return DatasetState(frame, data.obs.copy(), metadata, metadata.get("ref_mz"), var, snr), data
