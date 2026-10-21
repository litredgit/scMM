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
