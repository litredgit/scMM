"""Single-process ASGI host for the local scientific workbench."""
# ruff: noqa: RUF001

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from scMM.application.auth import AuthError
from scMM.application.identity import actor
from scMM.application.parameters import load_defaults
from scMM.application.projects import PROJECT_ROOT
from scMM.application.storage import StorageRoot
from scMM.application.web_workspace import WebWorkspaceService, WorkspaceError

from .routers import (
    ai,
    analysis,
    auth,
    extraction,
    lipids,
    maintenance,
    monitor,
    preferences,
    projects,
    raw,
    results,
    samples,
    storage,
)

STATIC_ROOT = Path(__file__).parent / "static"


def create_app(
    roots,
    output_roots=(),
    defaults=None,
    *,
    project_root=PROJECT_ROOT,
    static_root=STATIC_ROOT,
    auth_store=None,
    server_config=None,
):
    if auth_store is None or server_config is None:
        raise RuntimeError("认证配置缺失，请先执行 scmm-admin init；不支持匿名启动。")
    result_roots = (
        StorageRoot("项目结果", project_root),
        *(StorageRoot(root.label, root.path) for root in output_roots if root.label != "项目结果"),
    )
    manager = WebWorkspaceService(
        tuple(roots), result_roots, project_root, defaults or load_defaults()
    )

    from scMM.application.monitor import MonitorService

    monitoring = MonitorService(manager, auth_store, server_config)
    from scMM.application.retention_scheduler import RetentionScheduler

    manager.retention = RetentionScheduler(
        manager, auth_store, path=getattr(server_config, "values", {}).get("retention_db")
    )

    @asynccontextmanager
    async def lifespan(_app):
        monitoring.start()
        manager.retention.start()
        try:
            yield
        finally:
            manager.retention.stop()
            monitoring.stop()
            manager.shutdown()

    app = FastAPI(
        title="scMM Workbench API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    from scMM.application.ai_client import ChatClient, EndpointPolicy
    from scMM.application.ai_config import AIConfigStore, AIError

    values = getattr(server_config, "values", {})
    app.state.ai_config = (
        AIConfigStore(values["ai_db"], values["ai_key_file"])
        if values.get("ai_db") and values.get("ai_key_file")
        else None
    )
    app.state.ai_client = ChatClient(EndpointPolicy(values.get("ai_private_urls", [])))
    app.state.ai_active = set()
    app.state.monitor = monitoring
    from scMM.application.maintenance import Maintenance

    app.state.maintenance = (
        Maintenance(manager, monitoring, server_config) if hasattr(server_config, "path") else None
    )
    app.state.workspaces = manager
    app.state.auth, app.state.server_config = auth_store, server_config

    @app.middleware("http")
    async def browser_boundary(request: Request, call_next):
        path, principal, context_token = request.url.path, None, None
        operation = None
        deployment_operation = None
        status = 500
        try:
            if path.startswith("/api/"):
                mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
                if mutation:
                    origin = request.headers.get("origin")
                    allowed = (*server_config.origins, str(request.base_url).rstrip("/"))
                    if request.headers.get("x-scmm-client") != "web" or (
                        origin and origin not in allowed
                    ):
                        raise AuthError("请求来源不被接受。", 403, "origin_rejected")
                public = path == "/api/v1/health" or (
                    path
                    in {
                        "/api/v1/auth/login",
                        "/api/v1/presence/register",
                        "/api/v1/presence/heartbeat",
                    }
                    and request.method == "POST"
                )
                authorization = request.headers.get("authorization", "")
                operations = (
                    path == "/api/v1/runtime"
                    and request.method == "GET"
                    and (
                        authorization.startswith("Bearer ")
                        and auth_store.check_operations_token(authorization.removeprefix("Bearer "))
                    )
                )
                if not public and not operations:
                    principal = auth_store.authenticate(
                        request.cookies.get(server_config.cookie_name, ""),
                        activity=request.headers.get("x-scmm-activity") == "user",
                    )
                    monitoring.note(principal, request.headers.get("x-scmm-activity") == "user")
                    request.state.principal = principal
                    context_token = actor.set(principal)
                    if principal["must_change"] and path not in {
                        "/api/v1/auth/me",
                        "/api/v1/auth/password",
                        "/api/v1/auth/logout",
                    }:
                        raise AuthError("请先设置自己的密码。", 403, "password_change_required")
                    admin_only = (
                        path.startswith("/api/v1/admin/")
                        or path == "/api/v1/runtime"
                        or (path == "/api/v1/preferences" and mutation)
                        or (
                            path == "/api/v1/workspace/saved/clear"
                            or path.startswith("/api/v1/workspace/saved/retention-policy/")
                            or (path == "/api/v1/workspace/lipids/presets" and mutation)
                        )
                    )
                    if admin_only and principal["role"] != "admin":
                        raise AuthError("此操作需要管理员权限。", 403, "admin_required")
                    if mutation and not secrets.compare_digest(
                        request.headers.get("x-scmm-csrf", "").encode(), principal["csrf"].encode()
                    ):
                        raise AuthError("请求校验已失效，请重新登录。", 403, "csrf_rejected")
            maintenance_state = getattr(app.state, "maintenance", None)
            if maintenance_state:
                from scMM.application.deployment_maintenance import admit

                deployment_operation = admit(maintenance_state, path, request.method)
            if (
                maintenance_state
                and maintenance_state.request
                and maintenance_state.request.get("policy") != "deployment"
                and request.method not in {"GET", "HEAD", "OPTIONS"}
                and path.startswith("/api/")
                and path
                not in {
                    "/api/v1/presence/heartbeat",
                    "/api/v1/presence/register",
                    "/api/v1/ai/history",
                    "/api/v1/workspace/maintenance/draft",
                    "/api/v1/maintenance/draft",
                    "/api/v1/workspaces/resume",
                }
                and not path.startswith("/api/v1/admin/maintenance/")
                and not path.startswith("/api/v1/auth/")
            ):
                raise WorkspaceError(
                    "服务正在收集维护暂存，请等待完成或由管理员取消。",
                    code="maintenance",
                    status=503,
                )
            if (
                principal
                and path.startswith("/api/v1/")
                and not any(
                    part in path for part in ("/admin/", "/auth/", "/runtime", "/presence/")
                )
            ):
                operation = monitoring.begin(
                    principal,
                    path,
                    request.headers.get("x-scmm-page-id"),
                    closing=request.method == "DELETE" and path == "/api/v1/workspace",
                )
            response = await call_next(request)
            status = response.status_code
            if (
                principal
                and (
                    request.method in {"POST", "PATCH", "PUT", "DELETE"}
                    or path.endswith("/download")
                )
                and "/auth/" not in path
                and "/admin/" not in path
            ):
                auth_store.audit(principal["id"], request.method, path, response.status_code)
            if operation:
                tracked = operation
                iterator = response.body_iterator

                async def monitored_body():
                    outcome = status
                    try:
                        async for chunk in iterator:
                            yield chunk
                    except Exception:
                        outcome = 500
                        raise
                    finally:
                        monitoring.end(tracked, outcome)

                response.body_iterator = monitored_body()
                operation = None
        except (AuthError, WorkspaceError) as exc:
            if principal:
                auth_store.audit(principal["id"], "request_denied", path, exc.status)
            response = JSONResponse(
                {"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status
            )
        finally:
            if deployment_operation is not None:
                with maintenance_state._control_lock:
                    maintenance_state._deployment_requests.pop(deployment_operation, None)
            if operation:
                monitoring.end(operation, status)
            if context_token is not None:
                actor.reset(context_token)
        if request.url.path.startswith("/api/") or response.headers.get(
            "content-type", ""
        ).startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(AIError)
    async def ai_error(_request, exc):
        return error(exc.status, exc.code, str(exc))

    @app.exception_handler(AuthError)
    async def auth_error(_request, exc):
        return error(exc.status, exc.code, str(exc))

    def error(status, code, message, details=None):
        return JSONResponse(
            {"error": {"code": code, "message": message, "details": details}}, status_code=status
        )

    @app.exception_handler(WorkspaceError)
    async def workspace_error(_request, exc):
        return error(exc.status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        details = [
            {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
            for item in exc.errors()
        ]
        return error(422, "invalid_request", "请求参数不合法，请检查输入。", details)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(ValueError)
    async def value_error(_request, exc):
        return error(400, "invalid_value", str(exc))

    @app.exception_handler(KeyError)
    async def missing_key(_request, _exc):
        return error(400, "unknown_key", "所选存储或字段不存在。")

    @app.exception_handler(RuntimeError)
    async def operation_error(_request, exc):
        return error(409, "operation_conflict", str(exc))

    @app.exception_handler(ImportError)
    async def dependency_error(_request, exc):
        return error(400, "missing_dependency", str(exc))

    @app.exception_handler(OSError)
    async def storage_error(_request, exc):
        status = (
            403
            if isinstance(exc, PermissionError)
            else 404
            if isinstance(exc, FileNotFoundError)
            else 400
        )
        return error(status, "storage_error", str(exc))

    @app.get("/api/v1/health", tags=["health"])
    def health():
        return {"status": "ok", "frontend": "vue", "milestone": "workbench"}

    app.include_router(projects.router)
    app.include_router(auth.router)
    app.include_router(ai.router)
    app.include_router(monitor.router)
    app.include_router(maintenance.router)
    app.include_router(samples.router)
    app.include_router(storage.router)
    for router in (
        preferences.router,
        raw.router,
        extraction.router,
        analysis.router,
        lipids.router,
        results.router,
    ):
        app.include_router(router)

    if static_root is not None:
        static_root = Path(static_root)
        if not (static_root / "index.html").is_file():
            raise RuntimeError("Vue 前端尚未构建；请在 frontend/ 执行 npm ci 和 npm run build。")
        app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        @app.get("/projects", include_in_schema=False)
        @app.get("/samples", include_in_schema=False)
        @app.get("/parameters", include_in_schema=False)
        @app.get("/results", include_in_schema=False)
        @app.get("/raw", include_in_schema=False)
        @app.get("/extraction", include_in_schema=False)
        @app.get("/preprocess", include_in_schema=False)
        @app.get("/analysis", include_in_schema=False)
        @app.get("/admin/monitor", include_in_schema=False)
        @app.get("/account", include_in_schema=False)
        def index():
            return FileResponse(static_root / "index.html")

    return app
