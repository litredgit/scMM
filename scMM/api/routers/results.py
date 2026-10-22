"""Feature routes for the remaining five workbench stages."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
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


@router.post("/workspace/saved/retention")
def retention(body: s.RetentionPlan, manager: Service, identity: Identity):
    from scMM.application.retention import retention_plan

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if body.root != "项目结果":
            raise ValueError("保留计划仅支持本环境项目根中的项目。")
        return retention_plan(
            manager.saved_items(),
            body.path,
            min_age_days=body.min_age_days,
            keep_latest=body.keep_latest,
        )


@router.post("/workspace/saved/move")
def move(body: s.ExecutePlan, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if not workspace.trash_plan or workspace.trash_plan[0] != body.token:
            raise ValueError("请先生成有效的删除计划。")
        entry = manager.saved_items().move(workspace.trash_plan[1])
        workspace.trash_plan = None
        return {"entry": str(entry)}


@router.post("/workspace/saved/retention-plan")
def plan_retention_cleanup(body: s.RetentionPlan, manager: Service, identity: Identity):
    from scMM.application.retention_cleanup import cleanup_plan

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if body.root != "项目结果":
            raise ValueError("清理计划仅支持本环境项目根中的项目。")
        plan = cleanup_plan(
            manager.saved_items(),
            body.path,
            min_age_days=body.min_age_days,
            keep_latest=body.keep_latest,
        )
        token = uuid4().hex
        workspace.retention_cleanup_plan = (token, plan)
        return {"token": token, **plan}


@router.post("/workspace/saved/retention-move")
def move_retention_cleanup(body: s.ExecutePlan, manager: Service, identity: Identity):
    from scMM.application.retention_cleanup import execute_cleanup

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        plan = workspace.retention_cleanup_plan
        if not plan or plan[0] != body.token:
            raise ValueError("请先生成有效的策略清理计划。")
        # Consume before executing: failures and uncertain responses must be inspected,
        # never automatically replayed under the old authorization.
        workspace.retention_cleanup_plan = None
        with manager.retention_operation(plan[1]["path"]):
            entry = execute_cleanup(manager.saved_items(), plan[1])
        return {"entry": str(entry)}


@router.post("/workspace/saved/restore")
def restore(body: s.RestoreTrash, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        return {"path": str(manager.restore_saved(body.entry))}


@router.post("/workspace/saved/retention-policy/review")
def review_retention_policy(body: s.RetentionSchedule, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if body.root != "项目结果":
            raise ValueError("自动保留仅支持本环境项目根")
        review = manager.retention.review(
            body.path,
            {
                "min_age_days": body.min_age_days,
                "keep_latest": body.keep_latest,
            },
            body.interval_minutes,
        )
        token = uuid4().hex
        workspace.retention_policy_review = (token, review)
        return {"token": token, **review}


@router.post("/workspace/saved/retention-policy/enable")
def enable_retention_policy(
    body: s.ExecutePlan, request: Request, manager: Service, identity: Identity
):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        review = workspace.retention_policy_review
        if not review or review[0] != body.token:
            raise ValueError("请先审阅持续自动保留规则")
        workspace.retention_policy_review = None
        return manager.retention.enable(review[1], request.state.principal["id"])


@router.post("/workspace/saved/retention-policy/status")
def retention_policy_status(body: s.SavedPlan, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if body.root != "项目结果":
            raise ValueError("自动保留仅支持本环境项目根")
        return manager.retention.status(body.path)


@router.post("/workspace/saved/retention-policy/disable")
def disable_retention_policy(body: s.SavedPlan, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        if body.root != "项目结果":
            raise ValueError("自动保留仅支持本环境项目根")
        return manager.retention.disable(body.path)


@router.post("/workspace/saved/clear")
def clear(body: RevisionRequest, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        return manager.saved_items().clear()
