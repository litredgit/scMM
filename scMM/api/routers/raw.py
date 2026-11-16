# ruff: noqa: RUF001
"""Feature routes for the remaining five workbench stages."""

from fastapi import APIRouter

from .. import workflow_schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["raw"])


@router.get("/workspace/parameters")
def parameters(manager: Service, identity: Identity, sample_id: str | None = None):
    return manager.parameters(identity, sample_id)


@router.put("/workspace/parameters")
def edit_parameters(body: s.Parameters, manager: Service, identity: Identity):
    return manager.edit_parameters(identity, **body.model_dump())


@router.post("/workspace/parameters/clear")
def clear_parameters(body: s.SampleRequest, manager: Service, identity: Identity):
    return manager.clear_parameters(identity, body.revision, body.sample_id)


@router.post("/workspace/raw/open")
def raw_open(body: s.SampleRequest, manager: Service, identity: Identity):
    return manager.raw_open(identity, body.revision, body.sample_id)


@router.post("/workspace/raw/range")
def detect_range(body: s.SampleRequest, manager: Service, identity: Identity):
    from scMM.application.parameters import automatic_mz_range
    from scMM.application.preview_cache import file_identity

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        sample = manager.sample(workspace.require_project(), body.sample_id)
        if not workspace.raw or workspace.raw["sample_id"] != body.sample_id:
            raise ValueError("请先打开当前样本的原始文件。")
        preview = workspace.raw["preview"]
        if preview.open_identity != file_identity(sample["path"]):
            raise ValueError("原始文件已改变，请重新打开。")
        summary = preview.summary
        bounds = automatic_mz_range(summary.mz_min, summary.mz_max)
        return {"workspace": manager.view(workspace), "value": {"range": bounds}}


@router.post("/workspace/raw/plot")
def raw_plot(body: s.RawPlot, manager: Service, identity: Identity):
    options = body.model_dump(exclude={"sample_id", "kind"})
    return manager.raw_plot(identity, body.sample_id, body.kind, options)


@router.post("/workspace/raw/preview")
def start_preview(body: s.PreviewRequest, manager: Service, identity: Identity):
    return manager.start_preview(identity, body.revision, body.sample_id, body.parameters)


@router.get("/workspace/raw/preview")
def preview_status(manager: Service, identity: Identity):
    return manager.preview_status(identity)


@router.post("/workspace/raw/preview/collect")
def collect_preview(body: s.PreviewCollect, manager: Service, identity: Identity):
    return manager.collect_preview(identity, body.revision, body.job_id)


@router.get("/workspace/raw/scans")
def scans(manager: Service, identity: Identity, sample_id: str, ms_level: int = 1):
    return manager.scan_catalog(identity, sample_id, ms_level)


@router.post("/workspace/raw/diagnostic")
def raw_diagnostic(body: s.RawDiagnostic, manager: Service, identity: Identity):
    return manager.raw_diagnostic(identity, **body.model_dump())


@router.get("/workspace/raw/diagnostic")
def saved_raw_diagnostic(manager: Service, identity: Identity, sample_id: str):
    return manager.saved_raw_diagnostic(identity, sample_id)


@router.get("/workspace/raw/acquisition")
def acquisition(manager: Service, identity: Identity, sample_id: str):
    from scMM.application.preview_cache import file_identity
    from scMM.file.acquisition import acquisition_hints

    with manager.access(identity) as workspace:
        sample = manager.sample(workspace.require_project(), sample_id)
        path = manager.storage.resolve_raw_file(sample["storage"], sample["path"])
        before = file_identity(path)
    result = acquisition_hints(path)
    if file_identity(path) != before:
        raise ValueError("原始文件在读取采集信息时发生改变，请重新打开。")
    return result
