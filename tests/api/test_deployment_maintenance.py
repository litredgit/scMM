"""Deployment deadlines, preservation isolation, authenticated control and safe writes."""

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scMM.application import deployment_maintenance as policy
from scMM.application.deployment_client import local_admin, stop_workers
from scMM.application.identity import actor
from tests.support.auth import login_client
from tests.support.maintenance import closure_app, stale_page


def wait_ready(service):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = service.status()
        if state["deployment"]["phase"] == "ready":
            return state["deployment"]
        time.sleep(0.01)
    raise AssertionError("checkpoint did not complete")


def test_lost_pages_do_not_block_and_saved_project_stays_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "GRACE_SECONDS", 0)
    build, _auth, credential = closure_app(tmp_path)
    app = build()
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        identity = client.post("/api/v1/workspaces").json()["workspace_id"]
        client.headers["X-SCMM-Workspace"] = identity
        created = client.post("/api/v1/workspace/project", json={"revision": 0, "name": "saved"})
        created.raise_for_status()
        saved = client.post("/api/v1/workspace/project/save", json={"revision": 1})
        saved.raise_for_status()
        manifest = (
            tmp_path / "projects" / Path(saved.json()["project"]["path"]).name / "project.json"
        )
        original = manifest.read_bytes()
        client.patch(
            "/api/v1/workspace/project",
            json={
                "revision": 2,
                "name": "temporary",
                "description": "not formally saved",
            },
        ).raise_for_status()
        stale_page(client, app)
        client.post("/api/v1/admin/maintenance/deployment/prepare").raise_for_status()
        assert client.post("/api/v1/workspaces").status_code == 503
        # User may save existing work during the notice period.
        assert not app.state.maintenance._deployment_requests
        client.post("/api/v1/admin/maintenance/deployment/checkpoint").raise_for_status()
        report = wait_ready(app.state.maintenance)
        assert len(report["preserved"]) == 1 and not report["failed"]
        assert manifest.read_bytes() == original
        cookies, headers = dict(client.cookies), dict(client.headers)
    restored = build()
    with TestClient(restored, cookies=cookies, headers=headers) as client:
        result = client.get("/api/v1/workspace")
        result.raise_for_status()
        assert result.json()["project"]["manifest"]["name"] == "temporary"
        assert result.json()["project"]["unsaved"]
        assert manifest.read_bytes() == original


def test_failed_workspace_and_corrupt_restore_are_isolated_per_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "GRACE_SECONDS", 0)
    build, auth, _credential = closure_app(tmp_path)
    app = build()
    users = [auth.users()[0]["id"], auth.create_user("member")["id"]]
    ids = []
    for owner in users:
        token = actor.set({"id": owner})
        try:
            ids.append(app.state.workspaces.create()["workspace_id"])
        finally:
            actor.reset(token)
    real = app.state.maintenance.recovery.snapshot

    def snapshot(manager, **kw):
        if ids[1] in manager._workspaces:
            raise ValueError("unsupported model")
        return real(manager, **kw)

    monkeypatch.setattr(app.state.maintenance.recovery, "snapshot", snapshot)
    policy.prepare(app.state.maintenance)
    policy.checkpoint(app.state.maintenance)
    report = wait_ready(app.state.maintenance)
    assert report["preserved"][0]["owner_id"] == users[0]
    assert report["failed"] == [{"id": ids[1], "owner_id": users[1], "reason": "snapshot_failed"}]
    rebuilt = build()
    assert list(rebuilt.state.workspaces._workspaces) == [ids[0]]
    assert rebuilt.state.workspaces._workspaces[ids[0]].owner_id == users[0]
    # Never permit member access to the restored administrator workspace.
    token = actor.set({"id": users[1]})
    try:
        with pytest.raises(Exception, match="不属于当前账号"):
            rebuilt.state.workspaces.current(ids[0])
    finally:
        actor.reset(token)
    # A corrupt temporary state must not break the next service startup.
    pointer = app.state.maintenance.recovery.root / "current.json"
    pointer.write_text('{"deployment":"invalid"}')
    assert not build().state.workspaces._workspaces


def test_late_snapshot_cannot_publish_after_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "GRACE_SECONDS", 0)
    monkeypatch.setattr(policy, "SNAPSHOT_SECONDS", 0.02)
    build, _, _ = closure_app(tmp_path)
    service = build().state.maintenance
    service.manager.create()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = service.recovery.snapshot

    def delayed(manager, **kw):
        entered.set()
        release.wait(5)
        try:
            return original(manager, **kw)
        finally:
            finished.set()

    monkeypatch.setattr(service.recovery, "snapshot", delayed)
    policy.prepare(service)
    policy.checkpoint(service)
    assert entered.wait(2)
    time.sleep(0.03)
    report = wait_ready(service)
    assert report["timed_out"] and not report["preserved"]
    pointer = service.recovery.root / "current.json"
    content = pointer.read_bytes()
    release.set()
    assert finished.wait(5)
    assert pointer.read_bytes() == content
    assert not build().state.workspaces._workspaces


def test_writes_block_checkpoint_but_computation_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "GRACE_SECONDS", 0)
    build, _, _ = closure_app(tmp_path)
    service = build().state.maintenance
    save = policy.admit(service, "/api/v1/workspace/project/save", "POST")
    compute = policy.admit(service, "/api/v1/workspace/analysis/operation", "POST")
    policy.prepare(service)
    with pytest.raises(ValueError, match="受保护请求"):
        policy.checkpoint(service)
    service._deployment_requests.pop(save)
    policy.checkpoint(service)
    assert compute in service._deployment_requests
    with pytest.raises(Exception, match="部署维护"):
        policy.admit(service, "/api/v1/workspace/project/save", "POST")
    wait_ready(service)


def test_notice_deadline_and_readonly_token_cannot_mutate(tmp_path):
    build, auth, credential = closure_app(tmp_path)
    app = build()
    token = auth.rotate_operations_token()
    with TestClient(
        app, headers={"X-SCMM-Client": "web", "Authorization": "Bearer " + token}
    ) as client:
        assert client.post("/api/v1/admin/maintenance/deployment/prepare").status_code == 401
        login_client(client, credential)
        result = client.post("/api/v1/admin/maintenance/deployment/prepare")
        result.raise_for_status()
        assert result.json()["request"]["deadline"] > time.time() + 55
        assert client.post("/api/v1/admin/maintenance/deployment/checkpoint").status_code == 400
        assert client.post("/api/v1/admin/maintenance/cancel").status_code == 200


def test_local_maintenance_session_is_revoked_and_audited(tmp_path):
    build, auth, credential = closure_app(tmp_path)
    app = build()
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
    config = app.state.server_config
    with auth.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    with local_admin(config) as headers:
        token = headers["Cookie"].split("=", 1)[1]
        assert auth.authenticate(token)["role"] == "admin"
    with pytest.raises(Exception, match="登录已失效"):
        auth.authenticate(token)
    with auth.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == before
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit WHERE action='local_deployment_session'"
            ).fetchone()[0]
            == 1
        )


def test_stale_task_pid_is_never_signalled(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    task = root / "p/processing/batch/state.json"
    task.parent.mkdir(parents=True)
    task.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 1,
                "samples": [
                    {"id": "a", "status": "succeeded"},
                    {"id": "b", "status": "running"},
                ],
            }
        )
    )
    monkeypatch.setattr("scMM.application.deployment_client.owned_workers", lambda _: [])
    config = SimpleNamespace(values={"project_root": str(root), "output": {}})
    assert stop_workers(config) == [str(task)]
    state = json.loads(task.read_text(encoding="utf-8"))
    assert state["status"] == "interrupted"
    assert state["samples"][0]["status"] == "succeeded"


def test_actual_worker_exit_and_completed_sample_preservation(tmp_path):
    import subprocess
    import sys

    root = tmp_path / "projects"
    state = root / "p/processing/batch/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"status": "running", "samples": [{"id": "done", "status": "succeeded"}]})
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            "scMM.application.project_batch",
            str(state),
        ]
    )
    try:
        config = SimpleNamespace(values={"project_root": str(root), "output": {}})
        stopped = stop_workers(config)
        assert process.wait(timeout=3) is not None
        assert stopped == [str(state)]
        result = json.loads(state.read_text(encoding="utf-8"))
        assert result["status"] == "interrupted"
        assert result["samples"][0]["status"] == "succeeded"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_recovery_decode_deadline_never_changes_live_state_late(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "GRACE_SECONDS", 0)
    build, _, _ = closure_app(tmp_path)
    original = build()
    original.state.workspaces.create()
    service = original.state.maintenance
    policy.prepare(service)
    policy.checkpoint(service)
    wait_ready(service)
    from scMM.application.recovery import RecoveryStore

    decode = RecoveryStore.restore
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def delayed(self, manager, **kw):
        entered.set()
        release.wait(5)
        try:
            return decode(self, manager, **kw)
        finally:
            finished.set()

    monkeypatch.setattr(RecoveryStore, "restore", delayed)
    monkeypatch.setattr(policy, "SNAPSHOT_SECONDS", 0.02)
    rebuilt = build()
    assert entered.is_set()
    assert rebuilt.state.maintenance.restoration_report["timed_out"]
    assert not rebuilt.state.workspaces._workspaces
    release.set()
    assert finished.wait(5)
    assert not rebuilt.state.workspaces._workspaces


@pytest.mark.parametrize("requests", [None, [{"business": True, "kind": "保存"}]])
def test_first_upgrade_requires_actual_protected_request_evidence(tmp_path, monkeypatch, requests):
    from contextlib import nullcontext
    from urllib.error import HTTPError

    from scMM.application import deployment_client as client

    calls = []

    def call(port, headers, path, body=None, **kw):
        calls.append(path)
        if path.endswith("/deployment/prepare"):
            raise HTTPError("http://localhost", 404, "old API", None, None)
        if path.endswith("/prepare"):
            return {"request": {"id": "old", "deadline": 0}}
        if path == "/admin/monitor":
            return {"requests": requests}
        raise AssertionError(path)

    monkeypatch.setattr(client, "local_admin", lambda _: nullcontext({}))
    monkeypatch.setattr(client, "worker_states", lambda _: [])
    monkeypatch.setattr(client, "stop_workers", lambda _: [])
    monkeypatch.setattr(client, "request", call)
    config = SimpleNamespace(path=tmp_path / "server.json")
    with pytest.raises(RuntimeError, match=r"正式请求明细|受保护请求"):
        client.prepare_service(config, 5006)
    assert "/admin/maintenance/checkpoint" not in calls


def test_scheduled_priority_restart_does_not_require_an_existing_checkpoint(tmp_path, monkeypatch):
    build, _, _ = closure_app(tmp_path)
    service = build().state.maintenance
    service.config.values["environment"] = "dev"
    commands = []
    monkeypatch.setattr(
        "scMM.application.maintenance.subprocess.run",
        lambda command, **kw: commands.append(command),
    )
    result = service.execute("restart", deployment_first=True)
    assert result == {"scheduled": True, "action": "restart", "checkpoint": None}
    assert "--deployment-first" in commands[0]
    assert commands[0][0] == "systemd-run"


def test_oversized_temporary_state_is_skipped_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "GRACE_SECONDS", 0)
    monkeypatch.setattr(policy, "MAX_SNAPSHOT_BYTES", 1)
    build, _, _ = closure_app(tmp_path)
    service = build().state.maintenance
    identity = service.manager.create()["workspace_id"]
    policy.prepare(service)
    policy.checkpoint(service)
    report = wait_ready(service)
    assert not report["preserved"]
    assert report["failed"][0]["id"] == identity
    assert not build().state.workspaces._workspaces
