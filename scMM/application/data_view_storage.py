"""Atomic complete catalogue snapshots; executable models never enter formal projects."""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from anndata import read_h5ad

from scMM.ion.identity import dataset_identity, json_identity

from .data_views import DataViewCatalog, freeze_active_branch
from .naming import beijing_time, project_dataset_filename
from .projects import child_path, project_lock, write_json
from .result_catalog import rebind_figure_identity
from .storage import StorageCatalog, StorageRoot
from .tasks import utc_now
from .workbench import AnalysisWorkspace


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid catalogue artifact ID")
    return value


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
            reopened = read_h5ad(target)
            if dataset_identity(reopened, allow_missing=True) != dataset_identity(
                data, allow_missing=True
            ):
                raise ValueError("snapshot matrix roundtrip identity differs")
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
    branches = {}
    for key, entry in state["branches"].items():
        safe_id(key)
        branch = AnalysisWorkspace()
        branch.__dict__.update(deepcopy(entry["workspace"]))
        folder = snapshot / "branches" / key
        folder.mkdir(parents=True)
        storage = StorageCatalog([StorageRoot("snapshot", folder)])
        current = branch.save_h5ad(storage, "snapshot", ".", current_filename)
        data = read_h5ad(current)
        reports = json.loads(data.uns["scmm_workbench"]["reports_json"])
        presentation = entry.get("presentation", {})
        token = presentation.get("report_token") or presentation.get("saved_token")
        if token is not None and tuple(token) == branch.token:
            reports = {**presentation.get("saved_reports", {}), **reports}
        data.uns["scmm_workbench"]["reports_json"] = json.dumps(
            reports, default=lambda v: v.tolist()
        )
        data.write_h5ad(current)
        if dataset_identity(read_h5ad(current)) != dataset_identity(branch.data):
            raise ValueError("branch current matrix roundtrip differs")
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
        view_file = artifact(f"branches/{key}/views.json", payload=views)
        branches[key] = {
            "view_id": entry["view_id"],
            "materialization": entry.get("materialization"),
            "current": current_path,
            "baseline": baseline,
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
    # Read the entire candidate before publishing a manifest or changing live state.
    loaded = read_catalog_snapshot(project.folder, str(path.relative_to(project.folder)))
    return str(path.relative_to(project.folder)), loaded


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
        catalog_path, _loaded = write_catalog_snapshot(
            project, snapshot, state, current_filename=filename
        )
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
        write_json(folder / "project.json", candidate)
        project.manifest = candidate
        project.ion_state = state
        project.saved_token = project.workspace.token
        project.report_token = project.workspace.token
        project.dirty = False
