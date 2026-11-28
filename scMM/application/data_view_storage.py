"""Atomic complete catalogue snapshots; executable models never enter formal projects."""

import json
import re
from copy import deepcopy
from math import prod
from pathlib import Path
from uuid import uuid4

from anndata import read_h5ad

from scMM.ion.identity import json_identity
from scMM.util.artifacts import digest_file as file_sha

from .data_views import DataViewCatalog, freeze_active_branch
from .naming import beijing_time, project_dataset_filename
from .projects import child_path, project_lock, write_json
from .result_catalog import rebind_figure_identity
from .storage import StorageCatalog, StorageRoot
from .tasks import utc_now
from .workbench import AnalysisWorkspace


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid catalogue artifact ID")
    return value


def _equal_arrays(saved, expected):
    import numpy as np

    saved, expected = np.asarray(saved), np.asarray(expected)
    numeric_with_nan = saved.dtype.kind in "fc" and expected.dtype.kind in "fc"
    if np.array_equal(saved, expected, equal_nan=numeric_with_nan):
        return True
    if (
        saved.shape != expected.shape
        or saved.dtype.kind not in "OUS"
        or expected.dtype.kind not in "OUS"
    ):
        return False

    # AnnData reads variable-width text back as str, including UTF-8 bytes supplied by callers.
    def utf8(value):
        return value.encode("utf-8") if isinstance(value, str) else value

    return all(utf8(a) == utf8(b) for a, b in zip(saved.flat, expected.flat, strict=True))


def _equal_matrix_values(saved, expected):
    # Bound the dense comparison even for wide sparse matrices.
    rows = max(1, min(128, 2**20 // max(1, prod(expected.shape[1:]))))
    for start in range(0, expected.shape[0], rows):
        stop = start + rows
        left, right = saved[start:stop], expected[start:stop]
        if hasattr(left, "toarray"):
            left = left.toarray()
        if hasattr(right, "toarray"):
            right = right.toarray()
        if not _equal_arrays(left, right):
            return False
    return True


def _equal_metadata(saved, expected):
    import numpy as np
    import pandas as pd
    from scipy.sparse import issparse

    if issparse(expected):
        return (
            issparse(saved)
            and saved.shape == expected.shape
            and saved.dtype == expected.dtype
            and _equal_matrix_values(saved, expected)
        )

    if isinstance(expected, dict):
        return (
            isinstance(saved, dict)
            # AnnData 0.10/0.11 omit mapping values of None from H5AD.
            and not (saved.keys() - expected.keys())
            and all(_equal_metadata(saved.get(key), value) for key, value in expected.items())
        )
    if isinstance(expected, pd.DataFrame):
        try:
            pd.testing.assert_frame_equal(
                saved, expected, check_dtype=False, check_categorical=False, check_exact=True
            )
        except AssertionError:
            return False
        return True
    if isinstance(expected, (np.ndarray, list, tuple)):
        return _equal_arrays(saved, expected)
    if np.isscalar(expected) and np.isscalar(saved):
        return bool(saved == expected or (pd.isna(saved) and pd.isna(expected)))
    return saved is None and expected is None


def verify_h5ad_snapshot(path, expected, *, expected_uns=None):
    import h5py
    from pandas.testing import assert_frame_equal

    try:
        from anndata.io import read_elem, sparse_dataset
    except ImportError:  # AnnData 0.10
        from anndata._core.sparse_dataset import sparse_dataset
        from anndata.experimental import read_elem

    try:
        with h5py.File(path, "r") as h5ad:
            if any(
                not isinstance(h5ad[key], h5py.Group)
                for key in ("uns", "obs", "var", "layers", "obsm")
            ):
                raise ValueError("Snapshot H5AD structure is invalid")
            if expected_uns is None:
                expected_uns = expected.uns
            if not _equal_metadata(read_elem(h5ad["uns"]), expected_uns):
                raise ValueError("Snapshot unstructured metadata differs from the input")
            try:
                for key, original in (("obs", expected.obs), ("var", expected.var)):
                    assert_frame_equal(
                        read_elem(h5ad[key]),
                        original,
                        check_dtype=False,
                        check_column_type=False,
                        check_categorical=False,
                        check_exact=True,
                    )
            except AssertionError as exc:
                raise ValueError("Snapshot axis annotations differ from the input") from exc
            if set(h5ad["layers"]) != set(expected.layers):
                raise ValueError("Snapshot layers differ from the input")
            if set(h5ad["obsm"]) != set(expected.obsm):
                raise ValueError("Snapshot embeddings differ from the input")
            matrices = [(h5ad["X"], expected.X)]
            for group in ("layers", "obsm"):
                for key, original in getattr(expected, group).items():
                    node = h5ad[group][key]
                    if (
                        isinstance(node, h5py.Group)
                        and node.attrs.get("encoding-type") == "dataframe"
                    ):
                        if not _equal_metadata(read_elem(node), original):
                            raise ValueError("Snapshot embedding values differ from the input")
                    else:
                        matrices.append((node, original))
            for node, original in matrices:
                saved = sparse_dataset(node) if isinstance(node, h5py.Group) else node
                if saved.shape != original.shape:
                    raise ValueError("Snapshot matrix shape differs from the input")
                if (
                    isinstance(node, h5py.Dataset)
                    and node.attrs.get("encoding-type") == "string-array"
                ):
                    # AnnData stores Unicode and object arrays of text in one UTF-8 encoding.
                    if original.dtype.kind not in "UOS":
                        raise ValueError("Snapshot matrix dtype differs from the input")
                    saved = node.asstr()
                elif saved.dtype != original.dtype:
                    raise ValueError("Snapshot matrix dtype differs from the input")
                if not _equal_matrix_values(saved, original):
                    raise ValueError("Snapshot values differ from the input")
    except (KeyError, AttributeError) as exc:
        raise ValueError("Snapshot H5AD structure is invalid") from exc


def write_catalog_snapshot(project, snapshot, state, *, current_filename="current.h5ad"):
    """Write a candidate dependency closure; caller alone publishes project.json."""
    DataViewCatalog.from_state(state)
    snapshot = Path(snapshot)
    files = {}

    def artifact(relative, data=None, payload=None):
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            data.copy().write_h5ad(target)
            verify_h5ad_snapshot(target, data)
        else:
            write_json(target, payload)
        path = str(target.relative_to(project.folder))
        files[path] = file_sha(target)
        return path

    roots = {}
    for key, record in state["roots"].items():
        roots[key] = {
            "metadata": deepcopy(record["metadata"]),
            "artifact": artifact(f"roots/{safe_id(key)}.h5ad", data=record["data"]),
        }
    sources = {
        key: artifact(f"sources/{safe_id(key)}.h5ad", data=data)
        for key, data in state.get("source_matrices", {}).items()
    }
    registry = state.get("registry", {})
    json_identity(registry)
    registry_path = artifact("evidence/registry.json", payload=registry)
    branches, presentations = {}, {}
    for key, entry in state["branches"].items():
        safe_id(key)
        branch = AnalysisWorkspace()
        branch.__dict__.update(deepcopy(entry["workspace"]))
        folder = snapshot / "branches" / key
        folder.mkdir(parents=True)
        storage = StorageCatalog([StorageRoot("snapshot", folder)])
        presentation = entry.get("presentation", {})
        token = presentation.get("report_token") or presentation.get("saved_token")
        reports = branch.snapshot_reports(
            presentation.get("saved_reports")
            if token is not None and tuple(token) == branch.token
            else None
        )
        current = branch.save_h5ad(storage, "snapshot", ".", current_filename, reports=reports)
        current_path = str(current.relative_to(project.folder))
        files[current_path] = file_sha(current)
        baseline = artifact(f"branches/{key}/baseline.h5ad", data=branch._original)
        views = deepcopy(presentation.get("views", {}))
        identities = {name: value.get("_result_identity") for name, value in reports.items()}
        identities.update(branch._result_identities)
        for kind, source in views.get("figures", {}).items():
            figure = json.loads(source) if isinstance(source, str) else source
            if rebind_figure_identity(figure, branch, kind=kind, identities=identities):
                views["figures"][kind] = figure
        selection = (
            artifact(f"branches/{key}/selection.h5ad", data=branch._selection_source)
            if branch._selection_source is not None
            else None
        )
        view_file = artifact(f"branches/{key}/views.json", payload=views)
        presentations[key] = {
            "saved_reports": reports,
            "views": views,
            "saved_token": branch.token,
            "report_token": branch.token,
        }
        branches[key] = {
            "view_id": entry["view_id"],
            "materialization": entry.get("materialization"),
            "current": current_path,
            "baseline": baseline,
            "selection": selection,
            "views": view_file,
        }
    catalog = {
        "schema_version": 1,
        "roots": roots,
        "views": state["views"],
        "source_matrices": sources,
        "registry_artifact": registry_path,
        "branches": branches,
        "active_branch_id": state["active_branch_id"],
        "revision": state["revision"],
        "project_presentation": state.get("project_presentation", {}),
        "files": files,
    }
    path = snapshot / "catalog.json"
    write_json(path, catalog)
    return str(path.relative_to(project.folder)), presentations


def read_catalog_snapshot(folder, catalog_path):
    catalog = json.loads(child_path(folder, catalog_path).read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1:
        raise ValueError("unsupported data catalogue schema")
    files = catalog["files"]
    for relative, checksum in files.items():
        path = child_path(folder, relative)
        if file_sha(path) != checksum:
            raise ValueError("catalogue artifact checksum differs")

    def verified_path(relative):
        if relative not in files:
            raise ValueError("unverified catalogue artifact")
        return child_path(folder, relative)

    state = {
        "schema_version": 1,
        "roots": {},
        "views": deepcopy(catalog["views"]),
        "source_matrices": {},
        "branches": {},
        "active_branch_id": catalog["active_branch_id"],
        "revision": catalog["revision"],
        "project_presentation": catalog.get("project_presentation", {}),
        "registry": json.loads(
            verified_path(catalog["registry_artifact"]).read_text(encoding="utf-8")
        ),
    }
    for key, record in catalog["roots"].items():
        state["roots"][key] = {
            "metadata": deepcopy(record["metadata"]),
            "data": read_h5ad(verified_path(record["artifact"])),
        }
    for key, relative in catalog["source_matrices"].items():
        state["source_matrices"][key] = read_h5ad(verified_path(relative))
    for key, record in catalog["branches"].items():
        data = read_h5ad(verified_path(record["current"]))
        baseline = read_h5ad(verified_path(record["baseline"]))
        branch = AnalysisWorkspace()
        branch.replace(data, source=str(folder))
        branch._validate(baseline)
        branch._original = baseline
        if record.get("selection"):
            branch._selection_source = read_h5ad(verified_path(record["selection"]))
            branch._validate(branch._selection_source)
            from .selection_labels import validate_pool

            validate_pool(branch)
        reports = json.loads(data.uns["scmm_workbench"].get("reports_json", "{}"))
        views = json.loads(verified_path(record["views"]).read_text(encoding="utf-8"))
        identities = {name: value.get("_result_identity") for name, value in reports.items()}
        for kind, source in views.get("figures", {}).items():
            figure = json.loads(source) if isinstance(source, str) else source
            if rebind_figure_identity(figure, branch, kind=kind, identities=identities):
                views["figures"][kind] = figure
        entry = {
            "view_id": record["view_id"],
            "workspace": dict(vars(branch)),
            "presentation": {
                "saved_reports": reports,
                "views": views,
                "saved_token": branch.token,
                "report_token": branch.token,
            },
        }
        if record.get("materialization"):
            entry["materialization"] = record["materialization"]
        state["branches"][key] = entry
    DataViewCatalog.from_state(state)
    return state


def install_catalog_state(project, state):
    catalog = DataViewCatalog.from_state(state)
    active = state["active_branch_id"]
    if active is None:
        project.workspace = AnalysisWorkspace()
        project.saved_reports = {}
        project.views = deepcopy(state.get("project_presentation", {}).get("views", {}))
    else:
        project.workspace = catalog.workspace
        presentation = state["branches"][active].get("presentation", {})
        project.saved_reports = deepcopy(presentation.get("saved_reports", {}))
        project.views = deepcopy(presentation.get("views", {}))
    project.ion_state = state
    project.saved_token = project.workspace.token
    project.report_token = project.workspace.token


def save_ion_project(store, project):
    folder = store._folder(project.folder)
    project.validate_samples()
    from .processing import ProcessingParameters

    ProcessingParameters(**project.manifest["parameters"])
    with project_lock(store.root), project_lock(folder):
        disk = store._manifest(folder)
        if disk["revision"] != project.manifest["revision"]:
            raise RuntimeError("Project was saved by another session; reopen before saving")
        state = freeze_active_branch(project)
        saved_at = utc_now()
        revision = disk["revision"] + 1
        snapshot = (
            folder
            / "snapshots"
            / f"{beijing_time(saved_at, compact=True)}_r{revision:03d}_{uuid4().hex[:8]}"
        )
        snapshot.mkdir()
        filename = project_dataset_filename(project, timestamp=saved_at, revision=revision)
        catalog_path, presentations = write_catalog_snapshot(
            project, snapshot, state, current_filename=filename
        )
        for key, presentation in presentations.items():
            state["branches"][key]["presentation"] = presentation
        candidate = deepcopy(project.manifest)
        artifacts = {"data_catalog": catalog_path}
        catalog = json.loads((folder / catalog_path).read_text(encoding="utf-8"))
        active = state["active_branch_id"]
        if active is not None:
            artifacts.update(
                {key: catalog["branches"][active][key] for key in ("current", "baseline", "views")}
            )
        candidate.update(
            schema_version=2,
            artifacts=artifacts,
            revision=disk["revision"] + 1,
            saved_at=saved_at,
            data_source=project.workspace.source,
        )
        presentation = (
            presentations[active] if active is not None else state.get("project_presentation", {})
        )
        reports = deepcopy(presentation.get("saved_reports", {}))
        views = deepcopy(presentation.get("views", {}))
        write_json(folder / "project.json", candidate)
        project.manifest = candidate
        project.saved_reports = reports
        project.views = views
        project.ion_state = state
        project.saved_token = project.workspace.token
        project.report_token = project.workspace.token
        project.dirty = False
