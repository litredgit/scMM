import json
from pathlib import Path

import numpy as np
import pytest
from anndata import AnnData

from scMM.application import StorageRoot
from scMM.application.naming import beijing_time, dataset_filename
from scMM.application.projects import ProjectStore
from scMM.application.trash import SavedItems


def setup(tmp_path, **kwargs):
    root = tmp_path / "projects"
    root.mkdir()
    store = ProjectStore(root)
    manager = SavedItems(
        store, (StorageRoot("results", tmp_path),), trash_root=tmp_path / "recycle", **kwargs
    )
    return store, manager


def test_readable_names_and_legacy_project_roundtrip(tmp_path):
    assert beijing_time("2026-10-12T20:00:01Z", compact=True) == "20261013-040001"
    assert "北京时间" in beijing_time("2026-10-12T20:00:01Z")
    name = dataset_filename(
        "实验 / A", timestamp="2026-10-12T20:00:01Z", revision=3, batches=("批次A", "批次A")
    )
    assert name == "实验_A_批次A_20261013-040001_r003.h5ad"
    store, _ = setup(tmp_path)
    project = store.create("实验 / A")
    assert "实验_A_20" in project.folder.name
    project.workspace.replace(AnnData(np.ones((3, 2))))
    store.save(project)
    artifact = Path(project.manifest["artifacts"]["current"])
    assert "_r001_" in artifact.parent.name
    assert artifact.name.endswith("_r001.h5ad")
    # Older manifests and conventional current.h5ad names remain readable.
    current = project.folder / artifact
    legacy = current.with_name("current.h5ad")
    current.rename(legacy)
    project.manifest["artifacts"]["current"] = str(legacy.relative_to(project.folder))
    (project.folder / "project.json").write_text(json.dumps(project.manifest))
    reopened = store.open(project.folder)
    before = reopened.folder
    store.save(reopened)
    assert reopened.folder == before
    assert store.open(before).workspace.data.shape == (3, 2)


def test_trash_project_restore_and_conflict(tmp_path):
    store, manager = setup(tmp_path)
    project = store.create("可恢复项目")
    project.workspace.replace(AnnData(np.ones((3, 2))))
    store.save(project)
    original = project.folder
    entry = manager.move(manager.plan("项目结果", original))
    assert not original.exists() and not store.list()
    assert manager.list_trash()[0]["entry"] == str(entry)
    original.mkdir()
    with pytest.raises(FileExistsError):
        manager.restore(entry)
    original.rmdir()
    assert manager.restore(entry) == original
    assert store.open(original).workspace.data.shape == (3, 2)
    assert not manager.list_trash()


def test_trash_standalone_result_and_changed_plan(tmp_path):
    _, manager = setup(tmp_path)
    result = tmp_path / "result.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(result)
    plan = manager.plan("results", result)
    AnnData(np.ones((10, 3))).write_h5ad(result)
    with pytest.raises(RuntimeError, match="重新预览"):
        manager.move(plan)
    entry = manager.move(manager.plan("results", result))
    manager.restore(entry)
    assert result.is_file()


def test_active_sessions_tasks_and_referenced_artifacts_block_removal(tmp_path):
    store, manager = setup(tmp_path)
    project = store.create("active")
    manager.active_paths = lambda: (project.folder,)
    with pytest.raises(RuntimeError, match="会话"):
        manager.plan("项目结果", project.folder)
    manager.active_paths = lambda: ()
    batch = project.folder / "processing" / "batch"
    batch.mkdir()
    state = batch / "state.json"
    state.write_text(json.dumps({"status": "queued"}))
    (batch / "request.json").write_text("{}")
    with pytest.raises(RuntimeError, match="任务"):
        manager.plan("项目结果", project.folder)
    state.write_text(json.dumps({"status": "completed"}))
    source = tmp_path / "input.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(source)
    project.workspace.replace(AnnData(np.ones((2, 2))), source=str(source))
    store.save(project)
    with pytest.raises(RuntimeError, match="引用"):
        manager.plan("results", source)
    current = project.folder / project.manifest["artifacts"]["current"]
    with pytest.raises(RuntimeError, match="引用"):
        manager.plan("项目结果", current)
    project.workspace.source = str(state)
    store.save(project)
    with pytest.raises(RuntimeError, match="引用"):
        manager.plan("项目结果", batch)


def test_old_manifest_and_other_environment_references_are_protected(tmp_path):
    store, manager = setup(tmp_path)
    other = tmp_path / "other-projects"
    other.mkdir()
    external_store = ProjectStore(other)
    external = external_store.create("other environment")
    source = tmp_path / "shared.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(source)
    external.workspace.replace(AnnData(np.ones((2, 2))), source=str(source))
    external_store.save(external)
    external.manifest.pop("data_source")
    (external.folder / "project.json").write_text(json.dumps(external.manifest))
    with pytest.raises(RuntimeError, match="引用"):
        manager.plan("results", source)
    current = external.folder / external.manifest["artifacts"]["current"]
    with pytest.raises(PermissionError, match="所属环境"):
        manager.plan("results", current)
    assert store.list() == []


def test_raw_symlinks_root_and_move_failure_preserve_data(tmp_path, monkeypatch):
    store, manager = setup(tmp_path)
    with pytest.raises(PermissionError):
        manager.plan("results", tmp_path)
    project = store.create("raw protected")
    raw = project.folder / "experiment.RAW"
    raw.write_bytes(b"raw")
    with pytest.raises(PermissionError, match="原始谱"):
        manager.plan("项目结果", project.folder)
    raw.unlink()
    link = project.folder / "link.h5ad"
    link.symlink_to(tmp_path / "outside.h5ad")
    with pytest.raises(PermissionError, match="符号链接"):
        manager.plan("项目结果", project.folder)
    link.unlink()
    plan = manager.plan("项目结果", project.folder)

    def fail(*args, **kwargs):
        raise OSError("read-only storage")

    monkeypatch.setattr("scMM.application.trash.os.rename", fail)
    with pytest.raises(OSError):
        manager.move(plan)
    assert project.folder.is_dir()
    assert not manager.list_trash()


def test_legacy_active_task_and_h5ad_result_directory_are_protected(tmp_path):
    _, manager = setup(tmp_path)
    result = tmp_path / "batch-output"
    result.mkdir()
    AnnData(np.ones((2, 2))).write_h5ad(result / "data.h5ad")
    state = tmp_path / ".scmm-tasks" / "task" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"status": "running", "result_path": str(result)}))
    with pytest.raises(RuntimeError, match="未结束"):
        manager.plan("results", result)
    state.write_text(json.dumps({"status": "succeeded", "result_path": str(result)}))
    entry = manager.move(manager.plan("results", result))
    manager.restore(entry)
    assert (result / "data.h5ad").is_file()


def test_restore_rejects_tampered_parent_traversal(tmp_path):
    _, manager = setup(tmp_path)
    result = tmp_path / "result.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(result)
    entry = manager.move(manager.plan("results", result))
    record = json.loads((entry / "record.json").read_text(encoding="utf-8"))
    record["path"] = str(tmp_path / ".." / "outside.h5ad")
    (entry / "record.json").write_text(json.dumps(record))
    with pytest.raises(PermissionError, match="越过"):
        manager.restore(entry)
    assert (entry / "payload").is_file()


def test_shared_recycle_clear_and_symlink_failure_preserves_inventory(tmp_path):
    store, manager = setup(tmp_path)
    second = SavedItems(store, (StorageRoot("results", tmp_path),), trash_root=manager.trash_root)
    source = tmp_path / "result.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(source)
    entry = manager.move(manager.plan("results", source))
    assert second.list_trash()[0]["entry"] == str(entry)
    external = tmp_path / "keep.txt"
    external.write_text("keep")
    link = manager.trash_root / "unsafe"
    link.symlink_to(external)
    with pytest.raises(PermissionError, match="符号链接"):
        second.clear()
    assert (entry / "payload").exists() and external.read_text() == "keep"
    link.unlink()
    assert second.clear() == 1
    assert manager.list_trash() == []
    assert external.read_text() == "keep"
    assert second.clear() == 0


def test_clear_rejects_active_payload_and_reports_partial_failure(tmp_path, monkeypatch):
    _, manager = setup(tmp_path)
    for name in ("one", "two"):
        result = tmp_path / f"{name}.h5ad"
        AnnData(np.ones((2, 2))).write_h5ad(result)
        manager.move(manager.plan("results", result))
    entries = manager.list_trash()
    manager.active_paths = lambda: (entries[0]["entry"],)
    with pytest.raises(RuntimeError, match="会话"):
        manager.clear()
    assert len(manager.list_trash()) == 2
    manager.active_paths = lambda: ()
    import shutil

    actual = shutil.rmtree
    blocked = Path(entries[0]["entry"])

    def fail(path, *args, **kwargs):
        if Path(path) == blocked:
            raise OSError("read-only")
        return actual(path, *args, **kwargs)

    monkeypatch.setattr("scMM.application.trash.shutil.rmtree", fail)
    with pytest.raises(RuntimeError, match="已清理 1 项"):
        manager.clear()
    assert len(manager.list_trash()) == 1
    assert (blocked / "payload").exists()


def test_cross_device_move_restore_and_copy_failure(tmp_path, monkeypatch):
    import errno
    import os

    _, manager = setup(tmp_path)
    source = tmp_path / "result.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(source)
    rename = os.rename

    def cross_device(left, right):
        if Path(left) == source or Path(left).name == "payload":
            raise OSError(errno.EXDEV, "cross-device")
        return rename(left, right)

    monkeypatch.setattr("scMM.application.trash.os.rename", cross_device)
    entry = manager.move(manager.plan("results", source))
    assert not source.exists()
    manager.restore(entry)
    assert source.exists() and not manager.list_trash()

    def fail(*args, **kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr("scMM.application.trash.shutil.copy2", fail)
    with pytest.raises(OSError, match="copy failed"):
        manager.move(manager.plan("results", source))
    assert source.exists() and not manager.list_trash()


def test_saved_items_home_does_not_scan_usage_until_project_is_selected(tmp_path, monkeypatch):
    from scMM.ui.saved_items import SavedItemsPanel

    store, manager = setup(tmp_path)
    project = store.create("已有项目")
    calls = []
    actual_plan = manager.plan

    def plan(*args):
        calls.append(args)
        return actual_plan(*args)

    monkeypatch.setattr(manager, "plan", plan)
    monkeypatch.setattr("scMM.ui.saved_items.SavedItems", lambda *args, **kwargs: manager)
    panel = SavedItemsPanel(store, (), active_paths=lambda: (), changed=lambda: None)
    panel.refresh()
    assert panel.project.value is None
    assert panel.move_button.disabled
    assert calls == []
    panel.project.value = str(project.folder)
    assert len(calls) == 1
    assert panel.plan["path"] == str(project.folder)
    assert not panel.move_button.disabled
