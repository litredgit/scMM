"""Versioned requests and responses shared through the OpenAPI contract."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RevisionRequest(RequestModel):
    revision: int = Field(ge=0)


class CreateProject(RevisionRequest):
    name: str = Field(min_length=1, max_length=200)


class OpenProject(RevisionRequest):
    path: str


class EditProject(RevisionRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=20000)


class AddSamples(RevisionRequest):
    root: str
    paths: list[str] = Field(min_length=1, max_length=10000)


class SampleEdit(RequestModel):
    id: str
    name: str = Field(min_length=1, max_length=200)
    group: str = Field(max_length=1000)
    subject: str = Field(max_length=1000)
    batch: str = Field(max_length=1000)


class EditSamples(RevisionRequest):
    samples: list[SampleEdit] = Field(min_length=1, max_length=10000)


class RemoveSamples(RevisionRequest):
    ids: list[str] = Field(min_length=1, max_length=10000)


class SampleCSV(RevisionRequest):
    csv: str = Field(max_length=5_000_000)


class RelocateSample(RevisionRequest):
    sample_id: str
    root: str
    path: str


class ImportDataset(RevisionRequest):
    root: str
    path: str
    trust_pickle: bool = False


class MapSamples(RevisionRequest):
    source_key: str
    mapping: dict[str, str]


class DatasetSummary(BaseModel):
    id: str
    revision: int
    cells: int
    features: int
    observation_columns: list[str]
    source: str


class ProjectView(BaseModel):
    path: str
    manifest: dict[str, Any]
    unsaved: bool
    dataset: DatasetSummary | None


class WorkspaceView(BaseModel):
    workspace_id: str
    revision: int
    project: ProjectView | None


class SavedProject(BaseModel):
    path: str
    name: str
    saved_at: str
    samples: int


class StorageView(BaseModel):
    label: str
    path: str


class FileEntry(BaseModel):
    name: str
    path: str
    directory: bool
    bytes: int | None


class DirectoryView(BaseModel):
    root: str
    path: str
    parent: str | None
    entries: list[FileEntry]
    total: int


class MappingView(BaseModel):
    source_key: str
    columns: list[str]
    rows: list[dict[str, str]]


class ParameterDefinition(BaseModel):
    name: str
    default: Any
    help: str


class ConfigurationView(BaseModel):
    api_version: Literal["v1"] = "v1"
    milestone: Literal["projects"] = "projects"
    storage: list[StorageView]
    results: list[StorageView]
    project_root: str
    processing: list[ParameterDefinition]
    analysis: list[ParameterDefinition]
    workspace_idle_seconds: int
