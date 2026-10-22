"""Explicit merge choices; previews authorize no filesystem writes."""

from typing import Literal

from pydantic import Field

from .schemas import RequestModel, RevisionRequest


class MergeSource(RequestModel):
    kind: Literal["current", "file"]
    root: str = ""
    path: str = ""
    mass_key: str | None = None
    sample_key: str | None = None


class MergeInspect(RevisionRequest):
    source: MergeSource


class MergeMapping(RequestModel):
    input_id: str
    source_sample: str | None
    name: str = Field(min_length=1, max_length=200)
    group: str | None = Field(default=None, max_length=1000)
    subject: str | None = Field(default=None, max_length=1000)
    batch: str | None = Field(default=None, max_length=1000)


class MergePreview(RevisionRequest):
    sources: list[MergeSource] = Field(min_length=2, max_length=8)
    reference: int = Field(ge=0, le=7)
    mode: Literal["union", "ref"]
    ppm_tol: float = Field(ge=0, le=1000000, allow_inf_nan=False)
    ambiguity: Literal["reject", "legacy"] = "reject"
    common_observations: list[str] = Field(default_factory=list, max_length=100)
    mapping: list[MergeMapping] = Field(min_length=1, max_length=2000)


class MergeApply(RevisionRequest):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
