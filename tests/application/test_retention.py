"""Retention advice protects references, unknown state and unsafe paths without writing."""

import json
import os
from pathlib import Path

import numpy as np
import pytest
from anndata import AnnData

from scMM.application.projects import ProjectStore, write_json
from scMM.application.retention import retention_plan
from scMM.application.retention_cleanup import cleanup_plan, execute_cleanup
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


def test_explicit_policy_age_count_ties_and_protection(tmp_path, monkeypatch):
    _, project, manager, _, preview, shared = setup(tmp_path)
    from scMM.application import retention

    day = 86400 * 10**9
    now = 20000 * day
    monkeypatch.setattr(retention.time, "time_ns", lambda: now)
    # Per-kind ordering: two old tied previews and one recent preview.
    for path in [preview, *preview.iterdir(), shared, shared.with_suffix(".json")]:
        os.utime(path, ns=(now - 40 * day, now - 40 * day))
    import shutil

    tied = preview.with_name(f"preview-{'c' * 32}")
    shutil.copytree(preview, tied)
    os.utime(tied, ns=(now - 40 * day, now - 40 * day))
    recent = preview.with_name(f"preview-{'d' * 32}")
    shutil.copytree(preview, recent)
    os.utime(recent, ns=(now - day, now - day))
    before = inventory(tmp_path)
    default = retention_plan(manager, project.folder)
    assert default["selected_bytes"] == 0
    assert not any(row["selected_for_cleanup"] for row in default["items"])
    plan = retention_plan(manager, project.folder, min_age_days=30, keep_latest=1)
    assert inventory(tmp_path) == before
    assert plan["policy_parameters"] == {"min_age_days": 30, "keep_latest": 1}
    previews = rows(plan, "processing/preview-")
    assert sum(row["selected_for_cleanup"] for row in previews) == 2
    # The sole shared pair is the newest of its own kind and is kept.
    assert not rows(plan, "processing/shared-")[0]["selected_for_cleanup"]
    boundary = retention_plan(manager, project.folder, keep_latest=2)
    assert not any(row["selected_for_cleanup"] for row in rows(boundary, "processing/preview-"))
    # Even an explicit zero count and age never override persisted references.
    all_old = retention_plan(manager, project.folder, min_age_days=0, keep_latest=0)
    assert all(
        not r["selected_for_cleanup"] for r in all_old["items"] if r["status"] != "candidate"
    )
    assert rows(all_old, "processing/shared-")[0]["selected_for_cleanup"]
    assert all_old["selected_bytes"] == sum(
        r["bytes"] for r in all_old["items"] if r["selected_for_cleanup"]
    )


def test_future_modified_and_unknown_state_never_selected(tmp_path, monkeypatch):
    _, project, manager, _, preview, _ = setup(tmp_path)
    from scMM.application import retention

    monkeypatch.setattr(retention.time, "time_ns", lambda: 1)
    plan = retention_plan(manager, project.folder, min_age_days=0, keep_latest=0)
    assert plan["selected_bytes"] == 0
    (preview / "identity.json").unlink()
    monkeypatch.setattr(retention.time, "time_ns", lambda: 2**62)
    plan = retention_plan(manager, project.folder, min_age_days=0, keep_latest=0)
    assert not rows(plan, "processing/preview-")[0]["selected_for_cleanup"]


def test_incomplete_newer_cache_does_not_replace_valid_retained_cache(tmp_path):
    _, project, manager, _, preview, _ = setup(tmp_path)
    broken = preview.with_name(f"preview-{'f' * 32}")
    broken.mkdir()
    (broken / "data.h5ad").write_bytes(b"incomplete")
    plan = retention_plan(manager, project.folder, keep_latest=1)
    assert not any(row["selected_for_cleanup"] for row in rows(plan, "processing/preview-"))


@pytest.mark.parametrize("change", ["new_item", "content"])
def test_product_changes_during_plan_disable_policy(tmp_path, monkeypatch, change):
    _, project, manager, _, preview, _ = setup(tmp_path)
    original = manager._inventory
    changed = False

    def changing(path):
        nonlocal changed
        result = original(path)
        if not changed and path == preview:
            changed = True
            if change == "new_item":
                (project.folder / "processing" / "new-product").mkdir()
            else:
                (preview / "data.h5ad").write_bytes(b"replacement")
        return result

    monkeypatch.setattr(manager, "_inventory", changing)
    plan = retention_plan(manager, project.folder, min_age_days=0, keep_latest=0)
    assert changed and plan["warnings"] and plan["selected_bytes"] == 0


@pytest.mark.parametrize("value", [True, -1, 1.5, "2"])
@pytest.mark.parametrize("key", ["min_age_days", "keep_latest"])
def test_policy_requires_nonnegative_integers(tmp_path, key, value):
    with pytest.raises(ValueError, match=key):
        retention_plan(None, tmp_path, **{key: value})


def test_cleanup_archives_paired_members_and_restores_all_without_changing_current(tmp_path):
    store, project, manager, previous, preview, shared = setup(tmp_path)
    before = inventory(project.folder)
    plan = cleanup_plan(manager, project.folder, min_age_days=0, keep_latest=0)
    assert {
        str(shared.relative_to(project.folder)),
        str(shared.with_suffix(".json").relative_to(project.folder)),
    } <= {m["path"] for m in plan["members"]}
    entry = execute_cleanup(manager, plan)
    assert not (project.folder / previous).exists()
    assert not preview.exists() and not shared.exists() and not shared.with_suffix(".json").exists()
    assert store.open(project.folder).workspace.data.shape == (3, 2)
    assert manager.list_trash()[0]["status"] == "moved"
    assert manager.restore(entry) == project.folder
    after = inventory(project.folder)
    assert {k: v[1] for k, v in after.items() if not k.endswith(".project.lock")} == {
        k: v[1] for k, v in before.items() if not k.endswith(".project.lock")
    }
    assert not manager.list_trash()
    with pytest.raises(ValueError):
        cleanup_plan(manager, project.folder)


@pytest.mark.parametrize("change", ["content", "active", "reference", "unknown_task"])
def test_cleanup_revalidates_plan_and_leaves_all_sources(tmp_path, change):
    _, project, manager, _, preview, _ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    if change == "content":
        (preview / "data.h5ad").write_bytes(b"changed")
    elif change == "active":
        manager.active_paths = lambda: [project.folder]
    elif change == "reference":
        project.manifest["samples"] = [{"preview": {"artifact": str(preview)}}]
        write_json(project.folder / "project.json", project.manifest)
    else:
        job = project.folder / "processing" / "new-job"
        job.mkdir()
        write_json(job / "state.json", {"status": "uncertain"})
    before = inventory(project.folder)
    with pytest.raises((RuntimeError, ValueError)):
        execute_cleanup(manager, plan)
    assert inventory(project.folder) == before
    assert not manager.list_trash()


@pytest.mark.parametrize("damage", ["copy_failure", "copy_corruption", "new_active"])
def test_archive_failure_never_removes_sources(tmp_path, monkeypatch, damage):
    from scMM.application import retention_cleanup as cleanup

    _, project, manager, *_ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    before = {k: v[1] for k, v in inventory(project.folder).items()}
    original = cleanup._copy

    def copy(source, target):
        if damage == "copy_failure":
            raise OSError("disk full")
        original(source, target)
        if damage == "copy_corruption":
            if target.is_dir():
                (target / "corrupt").write_bytes(b"corrupt")
            else:
                target.write_bytes(b"corrupt")
        else:
            manager.active_paths = lambda: [project.folder]

    monkeypatch.setattr(cleanup, "_copy", copy)
    with pytest.raises((OSError, ValueError, RuntimeError)):
        execute_cleanup(manager, plan)
    after = {k: v[1] for k, v in inventory(project.folder).items()}
    assert {k: v for k, v in after.items() if not k.endswith(".project.lock")} == {
        k: v for k, v in before.items() if not k.endswith(".project.lock")
    }
    assert not manager.list_trash()


def test_partial_directory_deletion_is_rolled_back_from_verified_archive(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    _, project, manager, *_ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    before = {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    }

    def fail(path):
        next(p for p in path.rglob("*") if p.is_file()).unlink()
        raise OSError("partial deletion")

    monkeypatch.setattr(cleanup, "_remove", fail)
    with pytest.raises(OSError, match="partial deletion"):
        execute_cleanup(manager, plan)
    assert {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    } == before
    assert not manager.list_trash()


def test_crash_leaves_recoverable_record_and_clear_is_blocked(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    class Crash(BaseException):
        pass

    _, project, manager, *_ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    before = {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    }
    original = cleanup._remove
    calls = 0

    def crash(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Crash()
        original(path)

    monkeypatch.setattr(cleanup, "_remove", crash)
    with pytest.raises(Crash):
        execute_cleanup(manager, plan)
    record = manager.list_trash()[0]
    assert record["status"] == "prepared"
    with pytest.raises(RuntimeError, match="先恢复"):
        manager.clear()
    monkeypatch.setattr(cleanup, "_remove", original)
    # A new manager has no in-memory plan or task to rely on.
    recovered = SavedItems(manager.store, manager.catalog.roots[1:], trash_root=manager.trash_root)
    recovered.restore(record["entry"])
    assert {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    } == before
    assert not recovered.list_trash()


def test_failed_rollback_preserves_archive_then_restoration_checks_conflicts(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    _, project, manager, *_ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    remove, copy = cleanup._remove, cleanup._copy
    calls = 0

    def fail_remove(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("removal failed")
        remove(path)

    def fail_restore(source, target):
        if target.name.startswith(".restore-"):
            raise OSError("restore disk full")
        copy(source, target)

    monkeypatch.setattr(cleanup, "_remove", fail_remove)
    monkeypatch.setattr(cleanup, "_copy", fail_restore)
    with pytest.raises(RuntimeError, match="完整副本保留"):
        execute_cleanup(manager, plan)
    record = manager.list_trash()[0]
    entry = Path(record["entry"])
    assert record["status"] == "restoring"
    with pytest.raises(RuntimeError, match="先恢复"):
        manager.clear()
    monkeypatch.setattr(cleanup, "_remove", remove)
    monkeypatch.setattr(cleanup, "_copy", copy)
    missing = project.folder / record["members"][0]["path"]
    missing.mkdir()
    (missing / "conflict").write_bytes(b"user change")
    with pytest.raises(FileExistsError):
        manager.restore(entry)
    assert (missing / "conflict").read_bytes() == b"user change"
    (missing / "conflict").unlink()
    missing.rmdir()
    manager.restore(entry)
    assert missing.exists() and not manager.list_trash()


def test_cleanup_archive_tampering_prevents_restore(tmp_path):
    _, project, manager, *_ = setup(tmp_path)
    entry = execute_cleanup(manager, cleanup_plan(manager, project.folder, keep_latest=0))
    (entry / "payload" / "0" / "tampered").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="副本内容发生变化"):
        manager.restore(entry)
    assert manager.list_trash()


def test_pair_second_removal_failure_restores_both_and_all_earlier_members(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    _, project, manager, _, _, shared = setup(tmp_path)
    before = {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    }
    remove = cleanup._remove

    def fail(path):
        if path == shared:
            assert not shared.with_suffix(".json").exists()
            raise OSError("second member failed")
        remove(path)

    monkeypatch.setattr(cleanup, "_remove", fail)
    with pytest.raises(OSError, match="second member failed"):
        execute_cleanup(manager, cleanup_plan(manager, project.folder, keep_latest=0))
    assert {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    } == before
    assert not manager.list_trash()


def test_archive_flush_failure_preserves_sources(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    _, project, manager, *_ = setup(tmp_path)
    before = {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    }

    def fail(path):
        raise OSError("flush failed")

    monkeypatch.setattr(cleanup, "_sync_tree", fail)
    with pytest.raises(OSError, match="flush failed"):
        execute_cleanup(manager, cleanup_plan(manager, project.folder, keep_latest=0))
    assert {
        k: v[1] for k, v in inventory(project.folder).items() if not k.endswith(".project.lock")
    } == before
    assert not manager.list_trash()


def test_restoration_without_hardlink_support_and_residual_archive_retry(tmp_path, monkeypatch):
    import errno

    from scMM.application import retention_cleanup as cleanup

    _, project, manager, *_ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    entry = execute_cleanup(manager, plan)
    rmtree = cleanup.shutil.rmtree

    def unsupported(*args):
        raise OSError(errno.EOPNOTSUPP, "links unavailable")

    def residual(path, *args, **kwargs):
        if Path(path) == entry:
            raise OSError("residual cleanup failed")
        return rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cleanup.os, "link", unsupported)
    monkeypatch.setattr(cleanup.shutil, "rmtree", residual)
    with pytest.raises(OSError, match="residual cleanup failed"):
        manager.restore(entry)
    assert manager.list_trash()[0]["status"] == "restored"
    assert all((project.folder / m["path"]).exists() for m in plan["members"])
    monkeypatch.setattr(cleanup.shutil, "rmtree", rmtree)
    manager.restore(entry)
    assert not manager.list_trash()


def test_restore_checks_all_conflicts_and_rejects_member_traversal_before_writing(tmp_path):
    _, project, manager, *_ = setup(tmp_path)
    plan = cleanup_plan(manager, project.folder, keep_latest=0)
    entry = execute_cleanup(manager, plan)
    record_path = entry / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    last = project.folder / record["members"][-1]["path"]
    last.write_bytes(b"new user contents")
    with pytest.raises(FileExistsError):
        manager.restore(entry)
    assert not (project.folder / record["members"][0]["path"]).exists()
    assert last.read_bytes() == b"new user contents"
    last.unlink()
    record["members"][-1]["path"] = "../outside"
    write_json(record_path, record)
    with pytest.raises(PermissionError, match="越界"):
        manager.restore(entry)
    assert not (project.folder / record["members"][0]["path"]).exists()
