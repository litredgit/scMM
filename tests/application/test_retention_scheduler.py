"""Opt-in retention survives restarts without replaying uncertain writes."""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from scMM.application.auth import AuthStore
from scMM.application.parameters import load_defaults
from scMM.application.projects import write_json
from scMM.application.retention_scheduler import RetentionScheduler
from scMM.application.storage import StorageRoot
from scMM.application.web_workspace import WebWorkspaceService


def setup(tmp_path):
    (tmp_path / "projects").mkdir()
    roots = [StorageRoot("synthetic", tmp_path)]
    manager = WebWorkspaceService(roots, roots, tmp_path / "projects", load_defaults())
    manager.trash_root = tmp_path / "trash"
    auth, _ = AuthStore.initialize(tmp_path / "auth.sqlite3", "admin")
    owner = auth.users()[0]["id"]
    clock = [1000.0]
    scheduler = RetentionScheduler(manager, auth, clock=lambda: clock[0])
    manager.retention = scheduler
    project = manager.store.create("scheduled")
    shared = cache(project.folder, "b")
    return manager, auth, owner, clock, scheduler, project, shared


def cache(folder, key):
    path = folder / "processing" / f"shared-{key * 64}.npy"
    np.save(path, np.array([150.123456789]))
    path.with_suffix(".json").write_text("{}", encoding="utf-8")
    return path


def enable(scheduler, project, owner):
    review = scheduler.review(project.folder, {"min_age_days": 0, "keep_latest": 0}, 1)
    return scheduler.enable(review, owner)


def test_disabled_by_default_and_explicit_rule_validation(tmp_path):
    _, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    clock[0] += 3600
    scheduler.tick()
    assert scheduler.status(project.folder) == {"policy": None, "runs": [], "error": None}
    assert shared.exists()
    for interval in (True, 0, -1, 1.5, 525601):
        with pytest.raises(ValueError):
            scheduler.review(project.folder, {"min_age_days": 0}, interval)
    with pytest.raises(ValueError, match="显式指定"):
        scheduler.review(project.folder, {"min_age_days": None, "keep_latest": None}, 1)
    with pytest.raises(PermissionError):
        enable(scheduler, project, owner + "missing")


def test_future_artifacts_are_selected_each_cycle_and_policy_survives_restart(tmp_path):
    manager, auth, owner, clock, scheduler, project, shared = setup(tmp_path)
    status = enable(scheduler, project, owner)
    assert status["policy"]["enabled"] and status["policy"]["next_at"] == 1060
    scheduler.tick()
    assert shared.exists()
    clock[0] = 1060
    scheduler.tick()
    assert not shared.exists()
    first = scheduler.status(project.folder)["runs"][0]
    assert first["status"] == "completed" and Path(first["entry"]).is_dir()
    later = cache(project.folder, "c")
    restarted = RetentionScheduler(manager, auth, clock=lambda: clock[0])
    assert restarted.status(project.folder)["policy"]["enabled"]
    clock[0] += 86400  # Coalesce missed cycles into one, no catch-up replay.
    restarted.tick()
    assert not later.exists()
    assert len(restarted.status(project.folder)["runs"]) == 2
    restarted.tick()
    assert len(restarted.status(project.folder)["runs"]) == 2
    restarted.disable(project.folder)
    retained = cache(project.folder, "d")
    clock[0] += 3600
    restarted.tick()
    assert retained.exists()


def test_open_project_skips_then_closed_project_runs_and_freeze_defers(tmp_path):
    manager, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    enable(scheduler, project, owner)
    identity = manager.create()["workspace_id"]
    manager.open_project(identity, 0, str(project.folder))
    clock[0] += 60
    scheduler.tick()
    assert scheduler.status(project.folder)["runs"][0]["status"] == "skipped"
    assert scheduler.status(project.folder)["policy"]["enabled"]
    manager.close_project(identity, 1)
    manager.maintenance_frozen = True
    clock[0] += 3600
    scheduler.tick()
    assert shared.exists() and len(scheduler.status(project.folder)["runs"]) == 1
    manager.maintenance_frozen = False
    scheduler.tick()
    assert not shared.exists()


def test_disable_during_copy_rolls_back_and_stops_future_cycles(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    manager, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    enable(scheduler, project, owner)
    original = cleanup._copy

    def copy(source, target):
        original(source, target)
        scheduler.disable(project.folder)

    monkeypatch.setattr(cleanup, "_copy", copy)
    clock[0] += 60
    scheduler.tick()
    assert shared.exists() and shared.with_suffix(".json").exists()
    status = scheduler.status(project.folder)
    assert not status["policy"]["enabled"] and status["runs"][0]["status"] == "cancelled"
    assert not manager.saved_items().list_trash()


def test_copy_failure_disables_policy_and_requires_new_review(tmp_path, monkeypatch):
    from scMM.application import retention_cleanup as cleanup

    _, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    enable(scheduler, project, owner)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(cleanup, "_copy", fail)
    clock[0] += 60
    scheduler.tick()
    status = scheduler.status(project.folder)
    assert shared.exists() and not status["policy"]["enabled"]
    assert status["runs"][0]["status"] == "failed"
    assert "disk full" in status["runs"][0]["message"]
    clock[0] += 60
    scheduler.tick()
    assert len(scheduler.status(project.folder)["runs"]) == 1


def test_interrupted_cycle_is_not_replayed_and_pending_archive_blocks_reenable(
    tmp_path, monkeypatch
):
    from scMM.application import retention_cleanup as cleanup

    class Crash(BaseException):
        pass

    manager, auth, owner, clock, scheduler, project, shared = setup(tmp_path)
    enable(scheduler, project, owner)
    remove = cleanup._remove
    calls = 0

    def crash(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Crash()
        remove(path)

    monkeypatch.setattr(cleanup, "_remove", crash)
    clock[0] += 60
    with pytest.raises(Crash):
        scheduler.tick()
    assert scheduler.runtime()[0] == []
    assert "未完成自动保留" in scheduler.runtime()[1]
    with pytest.raises(RuntimeError, match="未完成自动保留"):
        scheduler.tick()
    restarted = RetentionScheduler(manager, auth, clock=lambda: clock[0])
    status = restarted.status(project.folder)
    assert not status["policy"]["enabled"] and status["runs"][0]["status"] == "interrupted"
    with pytest.raises(RuntimeError, match="先恢复"):
        enable(restarted, project, owner)
    monkeypatch.setattr(cleanup, "_remove", remove)
    manager.saved_items().restore(manager.saved_items().list_trash()[0]["entry"])
    assert shared.exists()
    enable(restarted, project, owner)


def test_policy_revision_and_project_identity_cannot_be_silently_rebound(tmp_path):
    _, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    review = scheduler.review(project.folder, {"keep_latest": 0}, 1)
    scheduler.enable(review, owner)
    with pytest.raises(RuntimeError, match="规则已被其他操作改变"):
        scheduler.enable(review, owner)
    changed = json.loads((project.folder / "project.json").read_text(encoding="utf-8"))
    changed["id"] = "replacement"
    write_json(project.folder / "project.json", changed)
    clock[0] += 60
    scheduler.tick()
    assert shared.exists() and not scheduler.status(project.folder)["policy"]["enabled"]
    assert scheduler.status(project.folder)["runs"][0]["status"] == "failed"


def test_revoked_authorization_disables_policy_without_removing_sources(tmp_path, monkeypatch):
    _, auth, owner, clock, scheduler, project, shared = setup(tmp_path)
    enable(scheduler, project, owner)
    users = auth.users()
    users[0]["active"] = False
    monkeypatch.setattr(auth, "users", lambda: users)
    clock[0] += 60
    scheduler.tick()
    status = scheduler.status(project.folder)
    assert shared.exists() and not status["policy"]["enabled"]
    assert status["runs"][0]["status"] == "cancelled"


def test_concurrent_ticks_remain_serial_and_claim_each_due_policy_once(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from scMM.application import retention_cleanup as cleanup

    manager, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    other = manager.store.create("other")
    second = cache(other.folder, "c")
    enable(scheduler, project, owner)
    enable(scheduler, other, owner)
    entered, release = threading.Event(), threading.Event()
    copy = cleanup._copy

    def slow(source, target):
        entered.set()
        assert release.wait(5)
        copy(source, target)

    monkeypatch.setattr(cleanup, "_copy", slow)
    clock[0] += 60
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(scheduler.tick)
        try:
            assert entered.wait(5)
            executor.submit(scheduler.tick).result(timeout=5)
            assert len(scheduler.runtime()[0]) == 1
        finally:
            release.set()
        pending.result(timeout=5)
    assert not shared.exists() and not second.exists()
    assert len(scheduler.status(project.folder)["runs"]) == 1
    assert len(scheduler.status(other.folder)["runs"]) == 1


def test_service_thread_stops_at_safe_checkpoint_and_keeps_sources(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from scMM.application import retention_cleanup as cleanup

    _, _, owner, clock, scheduler, project, shared = setup(tmp_path)
    enable(scheduler, project, owner)
    entered, release = threading.Event(), threading.Event()
    copy = cleanup._copy

    def slow(source, target):
        entered.set()
        assert release.wait(5)
        copy(source, target)

    monkeypatch.setattr(cleanup, "_copy", slow)
    clock[0] += 60
    scheduler.start()
    try:
        assert entered.wait(5) and scheduler._thread.is_alive()
        with ThreadPoolExecutor(max_workers=1) as executor:
            stopping = executor.submit(scheduler.stop)
            assert scheduler._stop.wait(5)
            release.set()
            stopping.result(timeout=5)
    finally:
        release.set()
        scheduler.stop()
    assert not scheduler._thread.is_alive() and shared.exists()
    assert scheduler.status(project.folder)["runs"][0]["status"] == "cancelled"


def test_persistent_run_history_is_bounded_without_changing_future_schedule(tmp_path):
    _, _, owner, clock, scheduler, project, _ = setup(tmp_path)
    enable(scheduler, project, owner)
    for _ in range(55):
        clock[0] += 60
        scheduler.tick()
    status = scheduler.status(project.folder)
    assert len(status["runs"]) == 50
    assert all(row["status"] == "retained" for row in status["runs"])
    assert status["policy"]["enabled"] and status["policy"]["next_at"] == clock[0] + 60


def test_unknown_database_version_is_rejected_without_disabling_existing_policy(tmp_path):
    manager, auth, owner, _, scheduler, project, _ = setup(tmp_path)
    enable(scheduler, project, owner)
    with scheduler._db() as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="版本不受支持"):
        RetentionScheduler(manager, auth)
    with sqlite3.connect(scheduler.path) as db:
        assert db.execute("SELECT enabled FROM policies").fetchone()[0] == 1
    assert scheduler.runtime()[1] is not None


def test_explicit_database_keeps_policy_and_never_falls_back(tmp_path):
    manager, auth, owner, clock, original, project, _ = setup(tmp_path)
    path = tmp_path / "local-retention.sqlite3"
    scheduler = RetentionScheduler(manager, auth, path=path, clock=lambda: clock[0])
    enable(scheduler, project, owner)
    restarted = RetentionScheduler(manager, auth, path=path, clock=lambda: clock[0])
    assert restarted.status(project.folder)["policy"]["enabled"]
    assert original.status(project.folder)["policy"] is None
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="版本不受支持"):
        RetentionScheduler(manager, auth, path=path)
    with pytest.raises(sqlite3.OperationalError):
        RetentionScheduler(manager, auth, path=tmp_path / "absent" / "retention.sqlite3")
    assert original.status(project.folder)["policy"] is None
