"""Authenticated administrator resource configuration and maintenance control."""

import json
from typing import Literal

from fastapi import APIRouter, Query, Request

from ..workflow_schemas import Controls
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["maintenance"])
EDITABLE = {"storage", "project_root", "output", "cache_root", "temp_root", "lipid_database_dir"}


class Resources(Controls):
    storage: dict[str, str]
    project_root: str
    output: dict[str, str]
    cache_root: str
    temp_root: str
    lipid_database_dir: str | None


class Draft(Controls):
    nonce: str
    state: dict
    tab_id: str


class WorkspaceDraft(Controls):
    revision: int
    state: dict
    partial: bool = False


class Action(Controls):
    action: Literal["restart", "update"]
    version: str | None = None


class ClosedPages(Controls):
    review_id: str
    reason: str


@router.get("/maintenance/status")
def status(request: Request):
    service = request.app.state.maintenance
    return {
        "request": service.request if service else None,
        "completed": bool(service and service.completed),
    }


@router.get("/admin/maintenance/status")
def admin_status(request: Request):
    return request.app.state.maintenance.status()


@router.put("/workspace/maintenance/draft")
def draft(body: Draft, request: Request, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        request.app.state.maintenance.acknowledge(
            request.headers.get("x-scmm-page-id"),
            workspace,
            body.state,
            body.nonce,
            request.state.principal["id"],
            body.tab_id,
        )
    return {"saved": True}


@router.put("/maintenance/draft")
def standalone_draft(body: Draft, request: Request):
    request.app.state.maintenance.acknowledge(
        request.headers.get("x-scmm-page-id"),
        None,
        body.state,
        body.nonce,
        request.state.principal["id"],
        body.tab_id,
    )
    return {"saved": True}


@router.get("/maintenance/draft")
def standalone_restore(request: Request, tab_id: str = Query(max_length=64)):
    return getattr(request.app.state.workspaces, "maintenance_pages", {}).get(
        (request.state.principal["id"], tab_id), {}
    )


@router.put("/workspace/draft")
def save_workspace_draft(body: WorkspaceDraft, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        workspace.client_state = (
            {**getattr(workspace, "client_state", {}), **body.state} if body.partial else body.state
        )
    return {"saved": True}


@router.get("/workspace/maintenance/draft")
def restore(manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        return getattr(workspace, "client_state", {})


@router.get("/admin/resources")
def resources(request: Request):
    config = request.app.state.server_config
    pending = config.path.with_suffix(".pending.json")
    return {
        "active": {k: config.values[k] for k in EDITABLE},
        "pending": json.loads(pending.read_text()) if pending.exists() else None,
    }


@router.put("/admin/resources")
def edit_resources(body: Resources, request: Request):
    from scMM.application.projects import write_json
    from scMM.application.server_config import ServerConfig

    config = request.app.state.server_config
    values = {**config.values, **body.model_dump()}
    ServerConfig(values, config.path).validate()
    write_json(config.path.with_suffix(".pending.json"), body.model_dump())
    return {"saved": True, "requires_restart": True}


@router.post("/admin/database/update")
def database_update():
    from scMM.application.lipid_database import prepare_database

    return prepare_database(force=True)


@router.post("/admin/maintenance/prepare")
def prepare(request: Request):
    return request.app.state.maintenance.prepare()


@router.post("/admin/maintenance/checkpoint")
def checkpoint(request: Request):
    return request.app.state.maintenance.checkpoint()


@router.post("/admin/maintenance/closed-pages/review")
def review_closed_pages(request: Request):
    return request.app.state.maintenance.review_closed_pages()


@router.post("/admin/maintenance/closed-pages/confirm")
def confirm_closed_pages(body: ClosedPages, request: Request):
    return request.app.state.maintenance.confirm_closed_pages(
        body.review_id, body.reason, request.state.principal["id"]
    )


@router.post("/admin/maintenance/cancel")
def cancel(request: Request):
    request.app.state.maintenance.cancel()
    return {"cancelled": True}


@router.post("/admin/maintenance/execute")
def execute(body: Action, request: Request):
    return request.app.state.maintenance.execute(body.action, body.version)
