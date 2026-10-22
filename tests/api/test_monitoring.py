"""Read-only monitoring, document evidence, conservative release gates and bounded history."""

import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from scMM.api.app import create_app
from scMM.application.auth import AuthError, AuthStore
from scMM.application.monitor_peer import validate_decision
from scMM.application.monitor_presence import update_readiness
from scMM.application.monitor_probe import task_scan
from scMM.application.monitor_store import MonitorStore
from scMM.application.storage import StorageRoot
from tests.support.auth import login_client


def decision(**kwargs):
    return update_readiness(pages=[], workspaces=[], tasks=[], sampled_at=time.time(), **kwargs)


@pytest.fixture
def monitor(tmp_path):
    raw, projects = tmp_path / "raw", tmp_path / "projects"
    raw.mkdir()
    projects.mkdir()
    auth, initial = AuthStore.initialize(tmp_path / "auth.sqlite3", "tester")
    app = create_app(
        [StorageRoot("Raw", raw)],
        project_root=projects,
        static_root=None,
        auth_store=auth,
        server_config=SimpleNamespace(cookie_name="test", cookie_secure=False, origins=()),
    )
    client = TestClient(app, headers={"X-SCMM-Client": "web"})
    login_client(client, initial)
    service = app.state.monitor
    service._snapshot.update(sampled_at=time.time(), incomplete=[])
    yield app, client, service
    app.state.workspaces.shutdown()
    client.close()


def page(client, route="/projects", visibility="visible"):
    body = {"id": uuid4().hex, "route": route, "visibility": visibility}
    lease = client.post("/api/v1/presence/register", json=body)
    assert lease.status_code == 200, lease.text
    return {**body, "token": lease.json()["token"]}


def test_hidden_pages_close_evidence_and_no_credential_exposure(monitor):
    _, client, service = monitor
    ordinary = page(client, visibility="hidden")
    readonly = page(client, route="/admin/monitor")
    state = client.get("/api/v1/admin/monitor").json()
    assert state["update_readiness"]["state"] == "blocked"
    assert state["update_readiness"]["active_pages"] == 1
    assert state["update_readiness"]["monitor_pages"] == 1
    assert ordinary["id"] not in json.dumps(state)
    assert ordinary["token"] not in json.dumps(state)
    assert "secret_hash" not in json.dumps(state)
    client.post("/api/v1/presence/heartbeat", json={**ordinary, "closed": True}).raise_for_status()
    assert client.get("/api/v1/admin/monitor").json()["update_readiness"]["state"] == "ready"
    assert client.post("/api/v1/presence/heartbeat", json=ordinary).status_code == 409
    assert len(service.store.pages()) == 1
    assert (
        client.post(
            "/api/v1/presence/heartbeat", json={**readonly, "token": "wrong" * 10}
        ).status_code
        == 403
    )


def test_stale_and_previous_instance_pages_remain_unconfirmed(monitor):
    _, client, service = monitor
    tracked = page(client, route="/admin/monitor")
    service.clock = lambda: time.time() + 100
    state = service.snapshot()
    assert state["update_readiness"]["state"] == "unknown"
    assert state["pages"][0]["state"] == "unconfirmed"
    service.clock = time.time
    service.instance = uuid4().hex
    assert service.snapshot()["update_readiness"]["state"] == "unknown"
    client.post("/api/v1/presence/heartbeat", json=tracked).raise_for_status()
    assert service.snapshot()["update_readiness"]["state"] == "ready"


def test_public_login_page_is_tracked_without_extending_authentication(monitor):
    app, client, service = monitor
    token = client.cookies.get("test")
    with app.state.auth.connect() as db:
        before = db.execute("SELECT touched FROM sessions").fetchone()[0]
    body = page(client, route="/admin/monitor")
    client.post("/api/v1/presence/heartbeat", json=body).raise_for_status()
    client.get("/api/v1/admin/monitor").raise_for_status()
    with app.state.auth.connect() as db:
        assert db.execute("SELECT touched FROM sessions").fetchone()[0] == before
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/admin/monitor").status_code == 401
        assert (
            anonymous.post(
                "/api/v1/presence/register",
                json={"id": uuid4().hex, "route": "/login", "visibility": "visible"},
            ).status_code
            == 403
        )
        anonymous.headers["X-SCMM-Client"] = "web"
        login_page = page(anonymous, route="/login")
        assert service.snapshot()["update_readiness"]["active_pages"] == 1
        assert (
            anonymous.post(
                "/api/v1/presence/heartbeat",
                json=login_page,
                headers={"Origin": "https://invalid.example"},
            ).status_code
            == 403
        )
    assert app.state.auth.authenticate(token)


def test_member_cannot_read_monitor_history_or_events(monitor):
    app, client, _ = monitor
    auth = app.state.auth
    created = auth.create_user("member")
    _, principal = auth.login("member", created["initial_credential"], "local")
    password = secrets.token_urlsafe(24)
    auth.change_password(principal, "", password)
    response = client.post("/api/v1/auth/login", json={"username": "member", "password": password})
    response.raise_for_status()
    for suffix in ("", "/history", "/events"):
        assert client.get("/api/v1/admin/monitor" + suffix).status_code == 403


def test_busy_workspace_does_not_block_monitor_or_touch_idle_clock(monitor):
    app, client, service = monitor
    tracked = page(client, route="/admin/monitor")
    client.headers["X-SCMM-Page-ID"] = tracked["id"]
    identity = client.post("/api/v1/workspaces").json()["workspace_id"]
    workspace = app.state.workspaces._workspaces[identity]
    touched = workspace.touched
    ready, release = threading.Event(), threading.Event()

    def hold():
        with workspace.lock:
            ready.set()
            release.wait(5)

    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(hold)
        assert ready.wait(2)
        try:
            start = time.monotonic()
            state = client.get("/api/v1/admin/monitor").json()
            assert time.monotonic() - start < 1
            assert state["update_readiness"]["state"] == "blocked"
            assert state["workspaces"][0]["unsaved"] is None
            assert state["workspaces"][0]["busy"]
            assert workspace.touched == touched
        finally:
            release.set()
            pending.result()
    assert service.snapshot()["update_readiness"]["state"] == "ready"


def test_inflight_legacy_requests_and_scan_failure_prevent_green(monitor, monkeypatch):
    _, client, service = monitor
    tracked = page(client, route="/admin/monitor")
    principal = {"id": service.auth.users()[0]["id"]}
    pending = service.begin(principal, "/analysis", tracked["id"])
    assert service.snapshot()["update_readiness"]["state"] == "blocked"
    service.end(pending, 500)
    assert service.snapshot()["update_readiness"]["state"] == "ready"
    pending = service.begin(principal, "/analysis", None)
    service.end(pending, 200)
    assert service.snapshot()["update_readiness"]["state"] == "unknown"
    monkeypatch.setattr(
        service, "probe", lambda *_: (_ for _ in ()).throw(OSError("private path must not escape"))
    )
    service.sample()
    state = service.snapshot()
    assert state["update_readiness"]["state"] == "unknown"
    assert "private path" not in json.dumps(state)


def test_persistent_history_rollup_retention_and_page_close_race(tmp_path):
    path = tmp_path / "monitor.sqlite3"
    store = MonitorStore.initialize(path)
    tick = [120000.0]
    store.clock = lambda: tick[0]
    lease = store.register(uuid4().hex, "old", None, "/login", "visible", None)
    store.write_history("old", {"host_cpu": 10, "invalid": float("nan"), "missing": None})
    store.write_history("old", {"host_cpu": 30})
    assert store.history()[0]["metrics"] == {"host_cpu": {"mean": 20, "peak": 30}}
    reopened = MonitorStore(path, clock=store.clock)
    assert len(reopened.pages()) == 1
    tick[0] += 86461
    reopened.write_history("new", {"host_cpu": 40})
    assert len(reopened.history()) == 1
    assert len(reopened.pages()) == 1  # Stale pages are never silently declared closed.
    reopened.heartbeat(lease["id"], lease["token"], "new", None, "/login", "hidden", None, True)
    with pytest.raises(AuthError):
        reopened.heartbeat(lease["id"], lease["token"], "new", None, "/login", "visible", None)
    assert not reopened.pages()
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"sampled_at": time.time() - 60},
        {"checked_at": float("nan")},
        {"active_pages": True},
        {"active_tasks": 1},
        {"unknown": ["unconfirmed"]},
        {"open_projects": 1},
        {"state": "surprise"},
    ],
)
def test_malformed_or_stale_peer_readiness_cannot_be_ready(changes):
    sample = decision()
    sample.update(changes)
    with pytest.raises(ValueError):
        validate_decision(sample, 1)


def test_task_metadata_scanning_never_reads_matrices_and_keeps_orphans_blocking(tmp_path):
    job = tmp_path / "project/processing/job"
    job.mkdir(parents=True)
    (job.parent.parent / "project.json").write_text(json.dumps({"name": "Synthetic"}))
    (job / "state.json").write_text(
        json.dumps({"status": "running", "pid": 99999999, "samples": []})
    )
    (job / "request.json").write_text(json.dumps({"submitted_by": "user"}))
    (job.parent.parent / "data.h5ad").write_bytes(b"not a matrix; must never be opened")
    result = task_scan([str(tmp_path)])
    assert result["tasks"][0]["process_alive"] is False
    assert result["tasks"][0]["user_id"] == "user"
    result = update_readiness(
        pages=[], workspaces=[], tasks=result["tasks"], sampled_at=time.time()
    )
    assert result["state"] == "blocked"
    (job / "state.json").write_text(json.dumps({"status": "completed", "samples": []}))
    terminal = task_scan([str(tmp_path)])
    assert terminal["tasks"][0]["status"] == "completed"
    assert not terminal["incomplete"]


def test_monitor_works_at_workspace_capacity_and_filters_security_events(monitor):
    app, client, service = monitor
    app.state.workspaces.capacity = 0
    tracked = page(client, route="/admin/monitor")
    assert not app.state.workspaces._workspaces
    principal = service.auth.users()[0]["id"]
    service.auth.audit(principal, "monitor_test", "synthetic", 200)
    client.get("/api/v1/admin/monitor").raise_for_status()
    client.get("/api/v1/admin/monitor/history").raise_for_status()
    events = client.get("/api/v1/admin/monitor/events?username=tester&action=monitor_test").json()
    assert len(events["items"]) == 1
    assert events["items"][0]["resource"] == "synthetic"
    assert not app.state.workspaces._workspaces
    assert service.snapshot()["update_readiness"]["monitor_pages"] == 1
    assert (
        client.post(
            "/api/v1/presence/heartbeat", json={**tracked, "route": "/anything"}
        ).status_code
        == 422
    )


def test_legacy_peer_never_uses_zero_workspaces_as_page_evidence(monkeypatch):
    from io import BytesIO

    from scMM.application.monitor_peer import peer_readiness

    replies = [{"frontend": "vue"}, {"unsaved_workspaces": 0, "busy_workspaces": 0}]

    class Opener:
        def open(self, *_args, **_kwargs):
            return BytesIO(json.dumps(replies.pop(0)).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    result = peer_readiness("http://127.0.0.1:5006")
    assert result["state"] == "unknown"
    assert "旧版" in result["reason"]


def test_streaming_download_remains_inflight_until_body_finishes(monitor):
    from starlette.responses import StreamingResponse

    app, client, service = monitor
    tracked = page(client, route="/admin/monitor")
    client.headers["X-SCMM-Page-ID"] = tracked["id"]
    started, release = threading.Event(), threading.Event()

    def chunks():
        started.set()
        yield b"synthetic"
        release.wait(3)
        yield b"end"

    @app.get("/api/v1/test/download")
    def download():
        return StreamingResponse(chunks())

    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(client.get, "/api/v1/test/download")
        assert started.wait(2)
        try:
            assert service.snapshot()["update_readiness"]["inflight_requests"] == 1
        finally:
            release.set()
            pending.result().raise_for_status()
    assert service.snapshot()["update_readiness"]["inflight_requests"] == 0


@pytest.mark.parametrize("close_first", [True, False])
def test_unload_close_and_workspace_release_can_arrive_in_either_order(monitor, close_first):
    app, client, service = monitor
    tracked = page(client, route="/admin/monitor")
    client.headers["X-SCMM-Page-ID"] = tracked["id"]
    identity = client.post("/api/v1/workspaces").json()["workspace_id"]

    def close():
        client.post(
            "/api/v1/presence/heartbeat", json={**tracked, "closed": True}
        ).raise_for_status()

    if close_first:
        close()
    client.delete("/api/v1/workspace", headers={"X-SCMM-Workspace": identity}).raise_for_status()
    if not close_first:
        close()
    assert not app.state.workspaces._workspaces
    assert service.snapshot()["update_readiness"]["state"] == "ready"


def test_registration_closure_proof_is_idempotent_and_wins_both_arrival_orders(monitor):
    _, client, service = monitor
    for closed_first in (True, False):
        identity, secret = uuid4().hex, secrets.token_hex(32)
        body = {
            "id": identity,
            "route": "/login",
            "visibility": "visible",
            "registration_secret": secret,
        }
        if not closed_first:
            first = client.post("/api/v1/presence/register", json=body)
            assert first.status_code == 200
            assert client.post("/api/v1/presence/register", json=body).status_code == 200
        closing = client.post("/api/v1/presence/register", json={**body, "closed": True})
        assert closing.status_code == 200, closing.text
        assert client.post("/api/v1/presence/register", json=body).status_code == 409
        assert (
            client.post("/api/v1/presence/register", json={**body, "closed": True}).status_code
            == 200
        )
        forged = client.post(
            "/api/v1/presence/register",
            json={**body, "closed": True, "registration_secret": secrets.token_hex(32)},
        )
        assert forged.status_code == 403
        assert not service.store.observed(identity)
    assert not service.store.pages()
    response = client.post(
        "/api/v1/presence/register",
        json={
            "id": uuid4().hex,
            "route": "/login",
            "visibility": "visible",
            "closed": True,
        },
    )
    assert response.status_code == 422
