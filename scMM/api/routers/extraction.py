"""Feature routes for the remaining five workbench stages."""

from fastapi import APIRouter

from .. import workflow_schemas as s
from ..schemas import RevisionRequest
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["extraction"])


@router.post("/workspace/extraction/preflight")
def preflight(body: RevisionRequest, manager: Service, identity: Identity):
    return manager.extraction_preflight(identity, body.revision)


@router.get("/workspace/extraction/batches")
def batches(manager: Service, identity: Identity):
    return manager.extraction_batches(identity)


@router.post("/workspace/extraction/start")
def start_batch(body: s.StartBatch, manager: Service, identity: Identity):
    return manager.start_extraction(identity, body.revision, body.retry_path)


@router.post("/workspace/extraction/stop")
def stop_batch(body: s.BatchRequest, manager: Service, identity: Identity):
    return manager.stop_extraction(identity, body.revision, body.path)


@router.post("/workspace/extraction/review")
def review_batch(body: s.ReviewBatch, manager: Service, identity: Identity):
    return manager.review_extraction(
        identity, body.revision, body.path, body.ids, compare=body.compare
    )


@router.post("/workspace/extraction/signal")
def batch_signal(body: s.BatchSignal, manager: Service, identity: Identity):
    return manager.batch_signal(identity, body.revision, body.path, body.sample_id)
