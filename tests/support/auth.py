"""Real authenticated HTTP fixtures with temporary databases and generated passwords."""

import secrets
from types import SimpleNamespace

from scMM.application.auth import AuthStore


def auth_options(tmp_path):
    path = tmp_path / "auth.sqlite3"
    if path.exists():
        store = AuthStore(path)
    else:
        store, _ = AuthStore.initialize(path, "tester")
    credential = store.update_user(store.users()[0]["id"], reset=True)["initial_credential"]
    return {
        "auth_store": store,
        "server_config": SimpleNamespace(
            cookie_name="scmm_test",
            cookie_secure=False,
            origins=(),
        ),
    }, credential


def login_client(client, credential):
    response = client.post(
        "/api/v1/auth/login", json={"username": "tester", "password": credential}
    )
    response.raise_for_status()
    client.headers["X-SCMM-CSRF"] = response.json()["csrf"]
    password = secrets.token_urlsafe(24)
    client.post("/api/v1/auth/password", json={"new_password": password}).raise_for_status()
    response = client.post("/api/v1/auth/login", json={"username": "tester", "password": password})
    response.raise_for_status()
    client.headers["X-SCMM-CSRF"] = response.json()["csrf"]
