"""Feature routes for the remaining five workbench stages."""

from fastapi import APIRouter

from scMM.application.preferences import load_preferences, save_preferences

from .. import workflow_schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["preferences"])


@router.get("/runtime")
def runtime(manager: Service):
    return manager.runtime()


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
