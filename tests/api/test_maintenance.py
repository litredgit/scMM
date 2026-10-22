"""Authenticated full-session checkpoint, mutation freeze and restart recovery."""

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from scMM.api.app import create_app
from scMM.application.auth import AuthStore
from scMM.application.monitor_store import MonitorStore
from scMM.application.server_config import DEFAULTS, ServerConfig
from scMM.application.storage import StorageRoot
from tests.support.auth import login_client


def test_http_draft_freeze_and_owner_restoration(tmp_path):
    for name in ("raw", "projects", "cache", "temp", "recycle", "private"):
        (tmp_path / name).mkdir()
    auth, credential = AuthStore.initialize(tmp_path / "private/auth.sqlite3", "tester")
    MonitorStore.initialize(tmp_path / "private/monitor.sqlite3")
    values = {
        **DEFAULTS,
        "cookie_secure": False,
        "cookie_name": "test",
        "auth_db": str(auth.path),
        "monitor_db": str(tmp_path / "private/monitor.sqlite3"),
        "storage": {"Raw": str(tmp_path / "raw")},
        "project_root": str(tmp_path / "projects"),
        "cache_root": str(tmp_path / "cache"),
        "temp_root": str(tmp_path / "temp"),
        "recycle_root": str(tmp_path / "recycle"),
        "preferences": str(tmp_path / "private/preferences.json"),
    }
    config_path = tmp_path / "private/server.json"
    config_path.write_text(json.dumps(values))
    config_path.chmod(0o600)
    config = ServerConfig(values, config_path).validate()

    def app():
        return create_app(
            [StorageRoot("Raw", tmp_path / "raw")],
            project_root=tmp_path / "projects",
            static_root=None,
            auth_store=auth,
            server_config=config,
        )

    original = app()
    page = uuid4().hex
    with TestClient(original, headers={"X-SCMM-Client": "web", "X-SCMM-Page-ID": page}) as client:
        body = {"id": page, "route": "/login", "visibility": "visible", "workspace_id": None}
        lease = client.post("/api/v1/presence/register", json=body).json()
        login_client(client, credential)
        identity = client.post("/api/v1/workspaces").json()["workspace_id"]
        client.headers["X-SCMM-Workspace"] = identity
        client.post(
            "/api/v1/workspace/project", json={"revision": 0, "name": "unsaved draft"}
        ).raise_for_status()
        client.patch(
            "/api/v1/workspace/project",
            json={"revision": 1, "name": "unsaved edited", "description": "draft not on disk"},
        ).raise_for_status()
        client.post(
            "/api/v1/presence/heartbeat",
            json={**body, "route": "/analysis", "workspace_id": identity, "token": lease["token"]},
        ).raise_for_status()
        prepared = client.post("/api/v1/admin/maintenance/prepare")
        prepared.raise_for_status()
        nonce = prepared.json()["request"]["id"]
        blocked = client.post("/api/v1/workspace/project/save", json={"revision": 2})
        assert blocked.status_code == 503
        acknowledgement = client.put(
            "/api/v1/workspace/maintenance/draft",
            json={
                "nonce": nonce,
                "tab_id": page,
                "state": {"route": "/analysis", "draft": {"seed": 111}},
            },
        )
        assert acknowledgement.status_code == 200, acknowledgement.text
        original.state.monitor.probe("disks", original.state.monitor.disk_roots)
        original.state.monitor.sample()
        checkpoint = client.post("/api/v1/admin/maintenance/checkpoint")
        assert checkpoint.status_code == 200, checkpoint.text
        assert checkpoint.json()["completed"]["verified"]
        headers = dict(client.headers)
        cookies = dict(client.cookies)
    restored = app()
    with TestClient(restored, headers=headers, cookies=cookies) as client:
        response = client.get("/api/v1/workspace")
        response.raise_for_status()
        assert response.json()["workspace_id"] == identity
        assert response.json()["project"]["unsaved"]
        assert client.get("/api/v1/workspace/maintenance/draft").json()["draft"] == {"seed": 111}
        # Nonce from the previous instance is never reused for new acknowledgements.
        stale = client.put(
            "/api/v1/workspace/maintenance/draft",
            json={"nonce": nonce, "tab_id": page, "state": {}},
        )
        assert stale.status_code == 400


def closure_app(tmp_path):
    """Full private configuration, so the real signed recovery protocol is used."""
    for name in ("raw", "projects", "cache", "temp", "recycle", "private"):
        (tmp_path / name).mkdir()
    auth, credential = AuthStore.initialize(tmp_path / "private/auth.sqlite3", "tester")
    MonitorStore.initialize(tmp_path / "private/monitor.sqlite3")
    values = {
        **DEFAULTS,
        "cookie_secure": False,
        "cookie_name": "test",
        "auth_db": str(auth.path),
        "monitor_db": str(tmp_path / "private/monitor.sqlite3"),
        "storage": {"Raw": str(tmp_path / "raw")},
        "project_root": str(tmp_path / "projects"),
        "cache_root": str(tmp_path / "cache"),
        "temp_root": str(tmp_path / "temp"),
        "recycle_root": str(tmp_path / "recycle"),
        "preferences": str(tmp_path / "private/prefs.json"),
    }
    path = tmp_path / "private/server.json"
    path.write_text(json.dumps(values))
    path.chmod(0o600)
    config = ServerConfig(values, path).validate()

    def build():
        return create_app(
            [StorageRoot("Raw", tmp_path / "raw")],
            project_root=tmp_path / "projects",
            static_root=None,
            auth_store=auth,
            server_config=config,
        )

    return build, auth, credential


def stale_page(client, app):
    body = {"id": uuid4().hex, "route": "/analysis", "visibility": "visible"}
    lease = client.post("/api/v1/presence/register", json=body).json()
    with app.state.monitor.store.connect() as db:
        db.execute("UPDATE pages SET seen=seen-100 WHERE id=?", (body["id"],))
    return {**body, "token": lease["token"]}


def review(client):
    client.post("/api/v1/admin/maintenance/prepare").raise_for_status()
    response = client.post("/api/v1/admin/maintenance/closed-pages/review")
    response.raise_for_status()
    return response.json()


def confirm(client, reviewed):
    return client.post(
        "/api/v1/admin/maintenance/closed-pages/confirm",
        json={
            "review_id": reviewed["review_id"],
            "reason": "Operator confirmed all reviewed tabs closed",
        },
    )


def test_closed_confirmation_keeps_unsaved_workspaces_and_verifies_recovery(tmp_path):
    build, auth, credential = closure_app(tmp_path)
    original = build()
    with TestClient(original, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        identity = client.post("/api/v1/workspaces").json()["workspace_id"]
        client.headers["X-SCMM-Workspace"] = identity
        client.post(
            "/api/v1/workspace/project", json={"revision": 0, "name": "unsaved retained"}
        ).raise_for_status()
        workspace = original.state.workspaces._workspaces[identity]
        before = (workspace.owner_id, workspace.revision, workspace.project.unsaved)
        stale = stale_page(client, original)
        reviewed = review(client)
        assert reviewed["unconfirmed_pages"] == 1 and reviewed["legacy_requests"]
        assert stale["id"] not in json.dumps(reviewed) and stale["token"] not in json.dumps(
            reviewed
        )
        assert confirm(client, reviewed).json()["requires_checkpoint"]
        assert (workspace.owner_id, workspace.revision, workspace.project.unsaved) == before
        assert not original.state.monitor.store.pages() and not original.state.monitor._legacy_pages
        assert confirm(client, reviewed).status_code == 400
        assert client.post("/api/v1/presence/heartbeat", json=stale).status_code == 409
        original.state.monitor.probe("disks", original.state.monitor.disk_roots)
        original.state.monitor.sample()
        checkpoint = client.post("/api/v1/admin/maintenance/checkpoint")
        assert checkpoint.status_code == 200, checkpoint.text
        assert checkpoint.json()["completed"]["verified"]
        assert checkpoint.json()["completed"]["workspaces"] == 1
        with auth.connect() as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM audit WHERE action='maintenance_closed_pages'"
                ).fetchone()[0]
                == 1
            )
    restored_app = build()
    restored = restored_app.state.workspaces._workspaces[identity]
    assert (restored.owner_id, restored.revision, restored.project.unsaved) == before
    assert restored.project.manifest["name"] == "unsaved retained"
    restored_app.state.workspaces.shutdown()


def test_closure_review_cannot_cover_new_heartbeat_request_page_or_expiry(tmp_path):
    build, _, credential = closure_app(tmp_path)
    app = build()
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        identity = client.post("/api/v1/workspaces").json()["workspace_id"]
        client.headers["X-SCMM-Workspace"] = identity
        stale = stale_page(client, app)
        reviewed = review(client)
        client.post("/api/v1/presence/heartbeat", json=stale).raise_for_status()
        assert confirm(client, reviewed).status_code == 400
        assert app.state.monitor._legacy_pages
        reviewed = review(client)
        client.get("/api/v1/workspace").raise_for_status()  # new unregistered business request
        assert confirm(client, reviewed).status_code == 400
        reviewed = review(client)
        client.post(
            "/api/v1/presence/register",
            json={
                "id": uuid4().hex,
                "route": "/login",
                "visibility": "visible",
            },
        ).raise_for_status()
        assert confirm(client, reviewed).status_code == 400
        reviewed = review(client)
        app.state.maintenance.closure_review["created"] -= 301
        assert confirm(client, reviewed).status_code == 400
        assert len(app.state.monitor.store.pages()) == 2
        reviewed = review(client)
        client.post("/api/v1/admin/maintenance/cancel").raise_for_status()
        assert confirm(client, reviewed).status_code == 400


def test_closure_confirmation_does_not_retire_live_pages_or_bypass_requests(tmp_path):
    build, _, credential = closure_app(tmp_path)
    app = build()
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        stale_page(client, app)
        client.post(
            "/api/v1/presence/register",
            json={
                "id": uuid4().hex,
                "route": "/login",
                "visibility": "visible",
            },
        ).raise_for_status()
        reviewed = review(client)
        app.state.monitor._active["test"] = {"business": True}
        assert confirm(client, reviewed).status_code == 400
        assert len(app.state.monitor.store.pages()) == 2
        app.state.monitor._active.clear()
        reviewed = review(client)
        assert reviewed["active_pages"] == 1
        assert confirm(client, reviewed).status_code == 200
        assert len(app.state.monitor.store.pages()) == 1
        checkpoint = client.post("/api/v1/admin/maintenance/checkpoint")
        assert checkpoint.status_code == 400
        assert not getattr(app.state.workspaces, "maintenance_frozen", False)
