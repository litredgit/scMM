"""Authentication, revocation, shared projects and private workspaces over real HTTP."""

import secrets
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scMM.api.app import create_app
from scMM.application.auth import AuthError, AuthStore
from scMM.application.storage import StorageRoot


@pytest.fixture
def secured(tmp_path):
    raw, projects = tmp_path / "raw", tmp_path / "projects"
    raw.mkdir()
    projects.mkdir()
    store, initial = AuthStore.initialize(tmp_path / "auth.sqlite3", "admin")
    app = create_app(
        [StorageRoot("Raw", raw)],
        project_root=projects,
        static_root=None,
        auth_store=store,
        server_config=SimpleNamespace(cookie_name="scmm_test", cookie_secure=False, origins=()),
    )
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        yield app, store, client, initial


def enter(client, name, credential, *, initialize=False):
    response = client.post("/api/v1/auth/login", json={"username": name, "password": credential})
    assert response.status_code == 200, response.text
    client.headers["X-SCMM-CSRF"] = response.json()["csrf"]
    if initialize:
        credential = secrets.token_urlsafe(24)
        client.post("/api/v1/auth/password", json={"new_password": credential}).raise_for_status()
        enter(client, name, credential)
    return credential


@pytest.mark.parametrize(
    "path",
    [
        "/projects",
        "/configuration",
        "/storage/entries?root=Raw",
        "/preferences",
        "/runtime",
        "/workspace/results/download?kind=matrix",
        "/admin/users",
        "/admin/audit",
    ],
)
def test_all_business_reads_require_login(secured, path):
    _, _, client, _ = secured
    response = client.get("/api/v1" + path)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/health").status_code == 200


def test_missing_auth_cannot_start(tmp_path):
    with pytest.raises(RuntimeError, match="不支持匿名"):
        create_app([], project_root=tmp_path, static_root=None)
    with pytest.raises(RuntimeError, match="数据库缺失"):
        AuthStore(tmp_path / "missing.sqlite3")
    assert not (tmp_path / "missing.sqlite3").exists()


def test_initial_credential_consumption_password_revocation_and_cookie(secured):
    app, store, client, initial = secured
    enter(client, "admin", initial)
    assert client.post("/api/v1/workspaces").status_code == 403
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": initial}
        ).status_code
        == 401
    )
    old = client.cookies.get("scmm_test")
    new = secrets.token_urlsafe(24)
    client.post("/api/v1/auth/password", json={"new_password": new}).raise_for_status()
    with pytest.raises(AuthError):
        store.authenticate(old)
    enter(client, "admin", new)
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": new})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/docs").status_code == 404
    app.state.server_config.cookie_secure = True
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": new})
    assert "; secure" in response.headers["set-cookie"].lower()


def test_csrf_origin_and_explicit_logout(secured):
    _, store, client, initial = secured
    enter(client, "admin", initial, initialize=True)
    token = client.cookies.get("scmm_test")
    assert client.post("/api/v1/workspaces", headers={"X-SCMM-CSRF": "wrong"}).status_code == 403
    assert (
        client.post("/api/v1/workspaces", headers={"Origin": "https://testserver"}).status_code
        == 403
    )
    assert (
        client.post("/api/v1/workspaces", headers={"Origin": "http://evil.invalid"}).status_code
        == 403
    )
    assert (
        client.post("/api/v1/workspaces", headers={"Origin": "http://testserver"}).status_code
        == 201
    )
    client.post("/api/v1/auth/logout").raise_for_status()
    with pytest.raises(AuthError):
        store.authenticate(token)
    assert client.get("/api/v1/projects").status_code == 401


def test_shared_projects_but_workspace_owner_and_admin_boundaries(secured):
    app, store, admin, initial = secured
    enter(admin, "admin", initial, initialize=True)
    workspace = admin.post("/api/v1/workspaces").json()["workspace_id"]
    headers = {"X-SCMM-Workspace": workspace}
    project = admin.post(
        "/api/v1/workspace/project", headers=headers, json={"revision": 0, "name": "Shared"}
    ).json()["project"]
    member = admin.post("/api/v1/admin/users", json={"username": "member"}).json()
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        enter(client, "member", member["initial_credential"], initialize=True)
        assert client.get("/api/v1/projects").json()[0]["name"] == "Shared"
        assert client.get("/api/v1/workspace", headers=headers).status_code == 404
        assert client.delete("/api/v1/workspace", headers=headers).status_code == 404
        own = client.post("/api/v1/workspaces").json()["workspace_id"]
        h = {"X-SCMM-Workspace": own}
        client.post(
            "/api/v1/workspace/project/open",
            headers=h,
            json={"revision": 0, "path": project["path"]},
        ).raise_for_status()
        for path, method, body in [
            ("/admin/users", "GET", None),
            ("/runtime", "GET", None),
            ("/preferences", "PUT", {}),
            ("/workspace/saved/clear", "POST", {"revision": 1}),
            ("/workspace/lipids/presets", "POST", {}),
        ]:
            assert client.request(method, "/api/v1" + path, headers=h, json=body).status_code == 403
        before = client.get("/api/v1/workspace", headers=h).json()
        response = client.post(
            "/api/v1/workspace/dataset/import",
            headers=h,
            json={"revision": 1, "root": "项目结果", "path": ".", "trust_pickle": True},
        )
        assert response.status_code == 403
        assert client.get("/api/v1/workspace", headers=h).json() == before
        token = client.cookies.get("scmm_test")
        admin.patch(
            f"/api/v1/admin/users/{member['id']}", json={"active": False}
        ).raise_for_status()
        assert client.get("/api/v1/projects").status_code == 401
        with pytest.raises(AuthError):
            store.authenticate(token)


def test_reset_revokes_all_sessions_and_last_admin_guard(secured):
    _, store, client, initial = secured
    password = enter(client, "admin", initial, initialize=True)
    a, principal = store.login("admin", password, "a")
    b, _ = store.login("admin", password, "b")
    with pytest.raises(AuthError, match="最后一个"):
        store.update_user(principal["id"], active=False)
    fresh = store.update_user(principal["id"], reset=True)["initial_credential"]
    for token in (a, b):
        with pytest.raises(AuthError):
            store.authenticate(token)
    with pytest.raises(AuthError):
        store.login("admin", password, "c")
    store.login("admin", fresh, "c")
    with pytest.raises(AuthError):
        store.login("admin", fresh, "c")


def test_operations_token_is_scoped_rotatable_and_not_anonymous_bypass(secured):
    _, store, client, _ = secured
    token = store.rotate_operations_token()
    headers = {"Authorization": "Bearer " + token}
    assert client.get("/api/v1/runtime", headers=headers).status_code == 200
    assert client.get("/api/v1/projects", headers=headers).status_code == 401
    assert client.get("/api/v1/runtime", headers={"Authorization": token}).status_code == 401
    store.rotate_operations_token()
    assert client.get("/api/v1/runtime", headers=headers).status_code == 401


def test_heartbeat_does_not_extend_idle_and_absolute_expiry(secured):
    _, store, client, initial = secured
    password = enter(client, "admin", initial, initialize=True)
    now = store.clock()
    store.clock = lambda: now
    token, _ = store.login("admin", password, "local")
    store.clock = lambda: now + 3599
    store.authenticate(token)
    store.clock = lambda: now + 3600
    with pytest.raises(AuthError):
        store.authenticate(token)
    store.clock = lambda: now
    token, _ = store.login("admin", password, "local")
    for seconds in range(3500, 43200, 3500):
        store.clock = lambda s=seconds: now + s
        store.authenticate(token, activity=True)
    store.clock = lambda: now + 43200
    with pytest.raises(AuthError):
        store.authenticate(token, activity=True)


def test_login_budget_persists_and_audit_never_contains_credentials(secured):
    _, store, client, initial = secured
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "absent", "password": initial}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "absent", "password": initial}
        ).status_code
        == 429
    )
    assert initial not in str(store.audit_log())
    reopened = AuthStore(store.path)
    with pytest.raises(AuthError) as exc:
        reopened.login("absent", initial, "testclient")
    assert exc.value.status == 429
