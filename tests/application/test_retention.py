"""Retention advice protects references, unknown state and unsafe paths without writing."""

import json
from pathlib import Path

import numpy as np
import pytest
from anndata import AnnData

from scMM.application.projects import ProjectStore, write_json
from scMM.application.retention import retention_plan
from scMM.application.storage import StorageRoot
from scMM.application.trash import SavedItems


def setup(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    store = ProjectStore(root)
    project = store.create("retention")
    project.workspace.replace(AnnData(np.ones((3, 2))))
    store.save(project)
    previous = Path(project.manifest["artifacts"]["current"]).parent
    project = store.open(project.folder)
    store.save(project)
    manager = SavedItems(store, [StorageRoot("Results", tmp_path)], trash_root=tmp_path / "trash")
    preview = project.folder / "processing" / f"preview-{'a' * 32}"
    preview.mkdir()
    for name in ("data.h5ad", "traces.csv", "detection.json", "targets.npy", "identity.json"):
        (preview / name).write_bytes(b"cached artifact")
    shared = project.folder / "processing" / f"shared-{'b' * 64}.npy"
    np.save(shared, np.array([150.0]))
    write_json(shared.with_suffix(".json"), {"sha256": "placeholder"})
    return store, project, manager, previous, preview, shared


def rows(plan, prefix):
    return [row for row in plan["items"] if any(p.startswith(prefix) for p in row["paths"])]


def inventory(root):
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in root.rglob("*")
        if p.is_file()
    }


def test_read_only_plan_groups_shared_pair_and_protects_current_snapshot(tmp_path):
    _, project, manager, previous, _preview, shared = setup(tmp_path)
    before = inventory(tmp_path)
    plan = retention_plan(manager, project.folder)
    assert inventory(tmp_path) == before
    assert not manager.trash_root.exists()
    assert plan["read_only"] and plan["immediate_freed_bytes"] == 0
    assert "token" not in plan
    assert not plan["warnings"]
    assert rows(plan, str(previous))[0]["status"] == "candidate"
    current = str(Path(project.manifest["artifacts"]["current"]).parent)
    assert rows(plan, current)[0]["status"] == "protected"
    assert rows(plan, "processing/preview-")[0]["status"] == "candidate"
    shared_row = rows(plan, "processing/shared-")[0]
    assert shared_row["status"] == "candidate" and len(shared_row["paths"]) == 2
    assert shared_row["bytes"] == shared.stat().st_size + shared.with_suffix(".json").stat().st_size
    assert plan["candidate_bytes"] == sum(
        r["bytes"] for r in plan["items"] if r["status"] == "candidate"
    )


def test_preview_manifest_and_other_project_provenance_retain_candidates(tmp_path):
    store, project, manager, previous, preview, _ = setup(tmp_path)
    project.manifest["samples"] = [
        {"preview": {"artifact": str(preview.relative_to(project.folder))}}
    ]
    # Only disk references are relevant to closed-project retention advice.
    write_json(project.folder / "project.json", project.manifest)
    other = store.create("dependent")
    other.workspace.replace(AnnData(np.ones((2, 2))), source=str(project.folder / previous))
    store.save(other)
    other.manifest.pop("data_source", None)  # Read H5AD provenance for older manifests too.
    write_json(other.folder / "project.json", other.manifest)
    plan = retention_plan(manager, project.folder)
    assert rows(plan, "processing/preview-")[0]["status"] == "protected"
    assert rows(plan, str(previous))[0]["status"] == "protected"


@pytest.mark.parametrize("status", ["queued", "running", "unexpected"])
def test_active_or_unknown_task_prevents_candidates(tmp_path, status):
    _, project, manager, *_ = setup(tmp_path)
    job = project.folder / "processing" / "preview-jobs" / "job"
    job.mkdir(parents=True)
    write_json(job / "state.json", {"status": status})
    write_json(job / "request.json", {"project_folder": str(project.folder)})
    plan = retention_plan(manager, project.folder)
    assert not any(row["status"] == "candidate" for row in plan["items"])
    assert bool(plan["warnings"]) == (status == "unexpected")


def test_external_detached_task_and_active_workspace_protect_project(tmp_path):
    _, project, manager, *_ = setup(tmp_path)
    task = tmp_path / ".scmm-tasks" / "job"
    task.mkdir(parents=True)
    write_json(task / "state.json", {"status": "running"})
    write_json(task / "request.json", {"output": str(project.folder)})
    assert retention_plan(manager, project.folder)["candidate_bytes"] == 0
    write_json(task / "state.json", {"status": "completed"})
    manager.active_paths = lambda: [project.folder]
    assert retention_plan(manager, project.folder)["candidate_bytes"] == 0


@pytest.mark.parametrize("damage", ["manifest", "matrix", "task"])
def test_unreadable_reference_or_task_prevents_all_recommendations(tmp_path, damage):
    store, project, manager, *_ = setup(tmp_path)
    other = store.create("other")
    if damage == "manifest":
        (other.folder / "project.json").write_text("null", encoding="utf-8")
    elif damage == "matrix":
        other.workspace.replace(AnnData(np.ones((2, 2))))
        store.save(other)
        (other.folder / other.manifest["artifacts"]["current"]).write_bytes(b"broken")
    else:
        job = other.folder / "processing" / "job"
        job.mkdir()
        (job / "state.json").write_text("broken", encoding="utf-8")
    plan = retention_plan(manager, project.folder)
    assert plan["warnings"] and plan["candidate_bytes"] == 0


def test_incomplete_cache_unknown_files_and_symlinks_are_retained(tmp_path):
    _, project, manager, _, preview, shared = setup(tmp_path)
    (preview / "detection.json").unlink()
    shared.with_suffix(".json").unlink()
    unknown = project.folder / "processing" / "unrecognized.bin"
    unknown.write_bytes(b"retain")
    link = project.folder / "snapshots" / "unsafe"
    link.symlink_to(tmp_path / "outside")
    plan = retention_plan(manager, project.folder)
    for prefix in (
        "processing/preview-",
        "processing/shared-",
        "processing/unrecognized",
        "snapshots/unsafe",
    ):
        assert rows(plan, prefix)[0]["status"] == "unknown"
    assert unknown.read_bytes() == b"retain" and link.is_symlink()


def test_changed_workspace_registry_invalidates_advice(tmp_path):
    _, project, manager, *_ = setup(tmp_path)
    values = iter([(), (project.folder,)])
    manager.active_paths = lambda: next(values)
    plan = retention_plan(manager, project.folder)
    assert plan["warnings"] and plan["candidate_bytes"] == 0


def test_only_local_project_paths_are_allowed(tmp_path):
    store, project, manager, *_ = setup(tmp_path)
    link = store.root / "alias"
    link.symlink_to(project.folder, target_is_directory=True)
    with pytest.raises(PermissionError):
        retention_plan(manager, link)
    outside = tmp_path / "other"
    outside.mkdir()
    foreign = ProjectStore(outside).create("foreign")
    with pytest.raises(PermissionError):
        retention_plan(manager, foreign.folder)
    processing = project.folder / "processing"
    processing.rename(project.folder / "keep-processing")
    processing.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PermissionError):
        retention_plan(manager, project.folder)


@pytest.mark.parametrize("change", ["manifest", "new_task", "task_state"])
def test_reference_or_task_change_during_inspection_invalidates_advice(
    tmp_path, monkeypatch, change
):
    _, project, manager, *_ = setup(tmp_path)
    import scMM.application.retention as retention

    job = project.folder / "processing" / "job"
    job.mkdir()
    write_json(job / "state.json", {"status": "completed"})
    original = manager._inventory
    changed = False

    def inventory_with_change(path):
        nonlocal changed
        result = original(path)
        if not changed:
            changed = True
            if change == "manifest":
                manifest = json.loads((project.folder / "project.json").read_text(encoding="utf-8"))
                manifest["name"] = "changed during plan"
                write_json(project.folder / "project.json", manifest)
            elif change == "new_task":
                other = project.folder / "processing" / "new-job"
                other.mkdir()
                write_json(other / "state.json", {"status": "queued"})
            else:
                write_json(job / "state.json", {"status": "running"})
        return result

    monkeypatch.setattr(manager, "_inventory", inventory_with_change)
    plan = retention.retention_plan(manager, project.folder)
    assert changed and plan["warnings"] and plan["candidate_bytes"] == 0


def test_unreadable_reference_scan_disables_candidates(tmp_path, monkeypatch):
    _, project, manager, *_ = setup(tmp_path)
    import scMM.application.retention as retention

    def denied(*args, **kwargs):
        kwargs["onerror"](PermissionError("unreadable directory"))
        yield

    monkeypatch.setattr(retention.os, "walk", denied)
    plan = retention_plan(manager, project.folder)
    assert plan["warnings"] and plan["candidate_bytes"] == 0


def test_detached_task_state_output_is_protected_without_request_reference(tmp_path):
    _, project, manager, *_ = setup(tmp_path)
    task = tmp_path / ".scmm-tasks" / "job"
    task.mkdir(parents=True)
    write_json(task / "state.json", {"status": "running", "result_path": str(project.folder)})
    write_json(task / "request.json", {})
    assert retention_plan(manager, project.folder)["candidate_bytes"] == 0
