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
