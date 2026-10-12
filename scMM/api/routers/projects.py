from typing import Annotated

from fastapi import APIRouter, Depends, Response

from scMM.application.web_workspace import WebWorkspaceService

from .. import schemas as s
from ..dependencies import service, workspace_id

router = APIRouter(prefix="/api/v1", tags=["projects"])
Service = Annotated[WebWorkspaceService, Depends(service)]
Identity = Annotated[str, Depends(workspace_id)]


@router.post("/workspaces", response_model=s.WorkspaceView, status_code=201)
def create_workspace(manager: Service):
    return manager.create()


@router.get("/workspace", response_model=s.WorkspaceView)
def get_workspace(manager: Service, identity: Identity):
    return manager.current(identity)


@router.delete("/workspace", status_code=204)
def close_workspace(manager: Service, identity: Identity):
    manager.close(identity)
    return Response(status_code=204)


@router.get("/projects", response_model=list[s.SavedProject])
def list_projects(manager: Service):
    return manager.store.list()


@router.post("/workspace/project", response_model=s.WorkspaceView, status_code=201)
def create_project(body: s.CreateProject, manager: Service, identity: Identity):
    return manager.create_project(identity, body.revision, body.name)


@router.post("/workspace/project/open", response_model=s.WorkspaceView)
def open_project(body: s.OpenProject, manager: Service, identity: Identity):
    return manager.open_project(identity, body.revision, body.path)


@router.post("/workspace/project/close", response_model=s.WorkspaceView)
def close_project(body: s.RevisionRequest, manager: Service, identity: Identity):
    return manager.close_project(identity, body.revision)


@router.patch("/workspace/project", response_model=s.WorkspaceView)
def edit_project(body: s.EditProject, manager: Service, identity: Identity):
    return manager.edit_project(identity, body.revision, body.name, body.description)


@router.post("/workspace/project/save", response_model=s.WorkspaceView)
def save_project(body: s.RevisionRequest, manager: Service, identity: Identity):
    return manager.save(identity, body.revision)
