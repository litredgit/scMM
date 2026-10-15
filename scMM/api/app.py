"""Single-process ASGI host for the local scientific workbench."""
# ruff: noqa: RUF001

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from scMM.application.parameters import load_defaults
from scMM.application.projects import PROJECT_ROOT
from scMM.application.storage import StorageRoot
from scMM.application.web_workspace import WebWorkspaceService, WorkspaceError

from .routers import (
    analysis,
    extraction,
    lipids,
    preferences,
    projects,
    raw,
    results,
    samples,
    storage,
)

STATIC_ROOT = Path(__file__).parent / "static"


def create_app(
    roots, output_roots=(), defaults=None, *, project_root=PROJECT_ROOT, static_root=STATIC_ROOT
):
    result_roots = (
        StorageRoot("项目结果", project_root),
        *(StorageRoot(root.label, root.path) for root in output_roots if root.label != "项目结果"),
    )
    manager = WebWorkspaceService(
        tuple(roots), result_roots, project_root, defaults or load_defaults()
    )

    @asynccontextmanager
    async def lifespan(_app):
        yield
        manager.shutdown()

    app = FastAPI(title="scMM Workbench API", version="1.0.0", lifespan=lifespan)
    app.state.workspaces = manager

    @app.middleware("http")
    async def browser_boundary(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in {
            "POST",
            "PATCH",
            "PUT",
            "DELETE",
        }:
            origin = request.headers.get("origin")
            if request.headers.get("x-scmm-client") != "web" or (
                origin and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return JSONResponse(
                    {"error": {"code": "origin_rejected", "message": "请求来源不被接受。"}},
                    status_code=403,
                )
        response = await call_next(request)
        if request.url.path.startswith("/api/") or response.headers.get(
            "content-type", ""
        ).startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

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
        def index():
            return FileResponse(static_root / "index.html")

    return app
