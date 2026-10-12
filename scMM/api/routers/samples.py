from fastapi import APIRouter

from .. import schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1/workspace", tags=["samples"])


@router.post("/samples", response_model=s.WorkspaceView)
def add_samples(body: s.AddSamples, manager: Service, identity: Identity):
    return manager.add_samples(identity, body.revision, body.root, body.paths)


@router.patch("/samples", response_model=s.WorkspaceView)
def edit_samples(body: s.EditSamples, manager: Service, identity: Identity):
    return manager.edit_samples(
        identity, body.revision, [sample.model_dump() for sample in body.samples]
    )


@router.post("/samples/remove", response_model=s.WorkspaceView)
def remove_samples(body: s.RemoveSamples, manager: Service, identity: Identity):
    return manager.remove_samples(identity, body.revision, body.ids)


@router.post("/samples/csv", response_model=s.WorkspaceView)
def import_csv(body: s.SampleCSV, manager: Service, identity: Identity):
    return manager.import_csv(identity, body.revision, body.csv)


@router.post("/samples/relocate", response_model=s.WorkspaceView)
def relocate_sample(body: s.RelocateSample, manager: Service, identity: Identity):
    return manager.relocate(identity, body.revision, body.sample_id, body.root, body.path)


@router.post("/dataset/import", response_model=s.WorkspaceView)
def import_dataset(body: s.ImportDataset, manager: Service, identity: Identity):
    return manager.import_dataset(identity, body.revision, body.root, body.path, body.trust_pickle)


@router.get("/samples/mapping", response_model=s.MappingView)
def get_mapping(manager: Service, identity: Identity, source_key: str | None = None):
    return manager.mapping(identity, source_key)


@router.put("/samples/mapping", response_model=s.WorkspaceView)
def map_samples(body: s.MapSamples, manager: Service, identity: Identity):
    return manager.map_samples(identity, body.revision, body.source_key, body.mapping)
