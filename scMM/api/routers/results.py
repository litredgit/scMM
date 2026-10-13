"""Feature routes for the remaining five workbench stages."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from .. import workflow_schemas as s
from ..schemas import RevisionRequest
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["results"])


@router.post("/workspace/results/export")
def export(body: s.Export, manager: Service, identity: Identity):
    return manager.export_dataset(identity, body.revision, body.root, body.directory, body.filename)


@router.get("/workspace/results/download")
def download(
    manager: Service, identity: Identity, kind: str, key: str = "", filename: str = "scmm.csv"
):
    if (
        Path(filename).name != filename
        or any(c in filename for c in ("\\", "\r", "\n"))
        or not filename
    ):
        raise ValueError("Use a simple filename")
    content, media = manager.download_content(identity, kind, key)
    if isinstance(content, Path):
        return FileResponse(content, media_type=media, filename=filename)
    from urllib.parse import quote

    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/workspace/saved/trash")
def list_trash(manager: Service, identity: Identity):
    with manager.access(identity):
        return manager.saved_items().list_trash()


@router.post("/workspace/saved/plan")
def plan(body: s.SavedPlan, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        plan = manager.saved_items().plan(body.root, body.path)
        token = uuid4().hex
        workspace.trash_plan = (token, plan)
        from scMM.application.saved_catalog import ResultCatalog

        description = ResultCatalog(manager.store, Path(plan["root"])).describe(Path(plan["path"]))
        return {"token": token, **plan, **description}


@router.post("/workspace/saved/move")
def move(body: s.ExecutePlan, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if not workspace.trash_plan or workspace.trash_plan[0] != body.token:
            raise ValueError("请先生成有效的删除计划。")
        entry = manager.saved_items().move(workspace.trash_plan[1])
        workspace.trash_plan = None
        return {"entry": str(entry)}


@router.post("/workspace/saved/restore")
def restore(body: s.RestoreTrash, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        return {"path": str(manager.saved_items().restore(body.entry))}


@router.post("/workspace/saved/clear")
def clear(body: RevisionRequest, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        return manager.saved_items().clear()
