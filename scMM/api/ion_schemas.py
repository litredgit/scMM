"""Explicit ion workflow requests; no arbitrary operation names or filesystem paths."""

from typing import Any, Literal

from pydantic import Field

from .schemas import RequestModel, RevisionRequest


class Initialize(RevisionRequest):
    linearity: Literal["linear_abundance", "unknown"] = "unknown"
    origin_kind: Literal["extraction", "imported_feature", "composite"] = "imported_feature"


class Options(RequestModel):
    polarity: Literal["pos", "neg"] = "pos"
    ppm: float = Field(default=5.0, gt=0, le=100)
    species: list[str] = Field(
        default_factory=lambda: ["[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+", "[M+H-H2O]+"],
        min_length=1,
        max_length=30,
    )
    max_isotope_order: int = Field(default=3, ge=1, le=10)
    min_valid_cells: int = Field(default=20, ge=2)
    resolution_200: float | None = Field(default=None, gt=0)
    formula_hypotheses: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)


class Run(RevisionRequest):
    root_id: str
    request_id: str = Field(min_length=1, max_length=100)
    options: Options = Field(default_factory=Options)


class Job(RevisionRequest):
    job_id: str


class Review(RevisionRequest):
    version: str
    kind: Literal["relation", "group", "candidate", "evidence"]
    target_id: str
    decision: Literal["accepted", "rejected", "pending"]
    reason: str = Field(min_length=1, max_length=10000)
    hypothesis_id: str | None = None
    relation_ids: list[str] = Field(default_factory=list, max_length=1000)
    quantifier_feature_id: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)


class Represent(RevisionRequest):
    version: str
    mode: Literal["reviewed_v1", "exploratory_v1"] = "reviewed_v1"
    strategy: Literal["isotope_representatives", "ion_group_representatives"] = (
        "isotope_representatives"
    )
    include_singletons: bool = True


class Activate(RevisionRequest):
    view_id: str
    branch_id: str
    catalog_revision: int


class Availability(RevisionRequest):
    view_id: str
    cell_ids: list[str] | None = None
    variable_ids: list[str] | None = None


class Materialize(RevisionRequest):
    view_id: str
    preview: dict[str, Any]


class Annotate(RevisionRequest):
    version: str | None = None
    root_id: str
    polarity: Literal["pos", "neg"] = "pos"
    species: list[str] = Field(default_factory=lambda: ["[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+"])
    ppm: float = Field(default=5.0, gt=0, le=100)
    namespace: str = Field(min_length=1, max_length=200)
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=100000)
    content: str = Field(default="", max_length=10000000)
    format: Literal["json", "csv", "tsv", "sdf"] = "json"
    field_mapping: dict[str, str] | None = None
    formula_targets: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)


class Evidence(RevisionRequest):
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    content: str = Field(default="", max_length=10000000)
    format: Literal["json", "mgf", "msp"] = "json"
    source_name: str = Field(min_length=1, max_length=200)


class Compare(RevisionRequest):
    branch_ids: list[str] = Field(min_length=2, max_length=10)
    normalization_mode: Literal["shared", "independent"]
    shared_factors: dict[str, float] | None = None


class SharedNormalization(RevisionRequest):
    factors: dict[str, float]


class Replicate(RevisionRequest):
    replicate_key: str
    group_key: str | None = None
    layer: str | None = None
    statistic: Literal["mean", "median", "sum"] = "mean"


class Import(RevisionRequest):
    content_base64: str = Field(max_length=100000000)
    kind: Literal["bundle", "source_l2"]


class EvidenceLink(RevisionRequest):
    evidence_ids: list[str] = Field(min_length=1, max_length=10000)
    targets: list[dict[str, Any]] = Field(min_length=1, max_length=10000)
    mapping: dict[str, list[dict[str, Any]]] | None = None
    ppm: float = Field(default=5.0, gt=0, le=100)


class Assertion(RevisionRequest):
    target: dict[str, Any]
    scheme: str
    version: str
    level: str
    criteria: dict[str, Any]
    evidence_ids: list[str]
    scope: dict[str, Any]
    structure_level: str = "unresolved"


class CompoundMerge(RevisionRequest):
    view_ids: list[str] = Field(min_length=2, max_length=10)
    alignments: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
