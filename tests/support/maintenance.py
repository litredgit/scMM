"""Private synthetic service and stale-page fixtures shared by maintenance checks."""

import json
from uuid import uuid4

from scMM.api.app import create_app
from scMM.application.auth import AuthStore
from scMM.application.monitor_store import MonitorStore
from scMM.application.server_config import DEFAULTS, ServerConfig
from scMM.application.storage import StorageRoot


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
