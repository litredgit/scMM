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


@router.get("/workspace/extraction/lists")
def lists(manager: Service, identity: Identity, list_id: str | None = None):
    return manager.extraction_lists(identity, list_id)


@router.post("/workspace/extraction/lists")
def upload_list(body: s.MzListUpload, manager: Service, identity: Identity):
    return manager.upload_extraction_list(identity, **body.model_dump())


@router.put("/workspace/extraction/feature-source")
def feature_source(body: s.FeatureSource, manager: Service, identity: Identity):
    return manager.set_feature_source(identity, **body.model_dump())


@router.post("/workspace/extraction/spectrum")
def batch_spectrum(body: s.BatchSpectrum, manager: Service, identity: Identity):
    return manager.extraction_spectrum(identity, **body.model_dump())


@router.post("/workspace/extraction/spectrum/save-list")
def save_batch_list(body: s.SaveBatchMzList, manager: Service, identity: Identity):
    return manager.save_extraction_list(identity, **body.model_dump())


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


@router.post("/workspace/extraction/compare")
def compare_batches(body: s.CompareBatches, manager: Service, identity: Identity):
    return manager.compare_extraction(identity, body.revision, body.path_a, body.path_b)
