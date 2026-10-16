"""Feature routes for the remaining five workbench stages."""

from fastapi import APIRouter, Request

from scMM.application.preferences import load_preferences, save_preferences

from .. import workflow_schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["preferences"])


@router.get("/runtime")
async def runtime(request: Request):
    state = request.app.state.monitor.snapshot()
    decision = state["update_readiness"]
    return {
        "unsaved_workspaces": decision["unsaved_workspaces"],
        "busy_workspaces": decision["busy_workspaces"],
        "monitor_protocol": 1,
        "environment": state["environment"],
        "instance": state["instance"],
        "update_readiness": decision,
    }


@router.get("/preferences")
def preferences():
    return load_preferences()


@router.put("/preferences")
def update_preferences(body: s.Preferences):
    save_preferences(body.presets, body.selected)
    return load_preferences()


@router.put("/workspace/presentation")
def presentation(body: s.Presentation, manager: Service, identity: Identity):
    def action(workspace):
        workspace.project.views.setdefault("legend_positions", {})[body.key] = body.position
        workspace.project.dirty = True

    return manager.mutate(identity, body.revision, action)
