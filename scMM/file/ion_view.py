"""Tagged single compound sources are projections, never fabricated Feature roots."""

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import numpy as np
from anndata import read_h5ad

from scMM.application.data_views import DataViewCatalog, freeze_active_branch
from scMM.ion.identity import dataset_identity

from .ion_bundle import validate_hdf5_container

TAG = "scmm_source_view_json"


def export_compound_source(project, view_id):
    state = freeze_active_branch(project)
    view = state["views"][view_id]
    if view["level"] != "L2":
        raise ValueError("use ordinary H5AD export for a feature analysis branch")
    data = state["source_matrices"][view_id].copy()
    data.uns[TAG] = json.dumps(
        {
            "schema_version": 1,
            "view": view,
            "data_identity": dataset_identity(data, allow_missing=True),
            "completeness": "single_source_without_measurement_root",
        },
        allow_nan=False,
    )
    with TemporaryDirectory(prefix="scmm-source-export-") as temporary:
        path = Path(temporary) / "source.h5ad"
        data.write_h5ad(path)
        return path.read_bytes()


def import_compound_source(project, content, *, max_bytes=2_000_000_000):
    if len(content) > max_bytes:
        raise ValueError("source H5AD exceeds import budget")
    with TemporaryDirectory(prefix="scmm-source-import-") as temporary:
        path = Path(temporary) / "source.h5ad"
        path.write_bytes(content)
        validate_hdf5_container(path, max_bytes=max_bytes)
        data = read_h5ad(path)
    metadata = json.loads(data.uns[TAG])
    if (
        metadata.get("schema_version") != 1
        or metadata.get("completeness") != "single_source_without_measurement_root"
    ):
        raise ValueError("unsupported compound source projection")
    view = deepcopy(metadata["view"])
    if (
        view.get("level") != "L2"
        or view.get("variable_kind") != "empirical_compound"
        or min(data.shape) < 1
    ):
        raise ValueError("invalid compound source view")
    if dataset_identity(data, allow_missing=True) != metadata["data_identity"]:
        raise ValueError("compound source identity differs")
    values = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
    mask = data.layers["scmm_quantifiable"]
    mask = mask.toarray() if hasattr(mask, "toarray") else np.asarray(mask)
    if (
        mask.dtype.kind != "b"
        or np.isinf(values).any()
        or not np.array_equal(np.isnan(values), ~mask)
    ):
        raise ValueError("compound source availability differs")
    state = (
        freeze_active_branch(project)
        if project.ion_state is not None
        else DataViewCatalog().export_state()
    )
    root = state["roots"].get(view["root_id"])
    if root is not None and root["metadata"]["identity"] != view["root_identity"]:
        raise ValueError("imported root reference conflicts with existing measurement")
    view_id = uuid4().hex
    view.update(
        id=view_id,
        root_available=root is not None,
        cell_ids=list(data.obs_names),
        variable_ids=list(data.var_names),
        source_identity=metadata["data_identity"],
        import_kind="single_source_projection",
    )
    state["views"][view_id] = view
    state["source_matrices"][view_id] = data
    state["revision"] += 1
    DataViewCatalog.from_state(state)
    project.ion_state = state
    project.dirty = True
    return deepcopy(view)
