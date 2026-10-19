"""Typed annotation, review and filtering contracts."""

from typing import Literal

from pydantic import Field

from .schemas import RevisionRequest
from .workflow_schemas import Controls


class LipidNetworkOptions(Controls):
    method: Literal["spearman", "pearson"] = "spearman"
    support_all: float = Field(default=0.8, ge=0, le=1)
    support_joint: float = Field(default=0.7, ge=0, le=1)
    min_joint_cells: int = Field(default=30, ge=2)
    plot_threshold: float = Field(default=0.7, ge=0, le=1)
    consensus_fraction: float = Field(default=2 / 3, ge=0, le=1)
    min_support_samples: int = Field(default=2, ge=2)
    condition_field: str = ""
    samples: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    molecule_layer: str = "total"


class LipidChartOptions(Controls):
    classification_level: Literal["CATEGORY", "MAIN_CLASS", "SUB_CLASS"] = "MAIN_CLASS"
    graph: Literal["feature", "molecule"] = "feature"
    scope: str = ""
    sign: Literal["both", "positive", "negative"] = "both"
    node_limit: int = Field(default=100, ge=1, le=2000)
    search: str = Field(default="", max_length=1000)
    category: str = ""
    focus: str = ""


class LipidOptions(Controls):
    database: str = ""
    polarity: Literal["pos", "neg", "both"] = "pos"
    adducts: list[str] = Field(min_length=1, max_length=16)
    annotation_ppm: float = Field(default=10.0, ge=0, le=1000)
    isotope_ppm: float = Field(default=10.0, ge=0, le=1000)
    max_isotope_order: int = Field(default=3, ge=1, le=10)
    isotope_tolerance: float = Field(default=0.2, ge=0, le=1)
    min_valid_cells: int = Field(default=20, ge=1)
    intensity_layer: str = ""
    resolution: float = Field(gt=0, le=1e8)
    network: LipidNetworkOptions = Field(default_factory=LipidNetworkOptions)


class LipidRun(RevisionRequest):
    options: LipidOptions
    rules: dict = Field(default_factory=dict)
    label: str = Field(default="", max_length=200)


class LipidRulesImport(RevisionRequest):
    content: str = Field(max_length=5_000_000)
    format: Literal["json", "csv"] = "json"


class LipidRulesApply(RevisionRequest):
    version: str
    rules: dict


class LipidPreset(RevisionRequest):
    name: str = Field(min_length=1, max_length=200)
    rules: dict


class LipidActivate(RevisionRequest):
    version: str


class IsotopeSpectrum(LipidActivate):
    relation_id: str


class LipidReview(LipidActivate):
    feature_id: str | None = None
    candidate_ids: list[str] | None = Field(default=None, max_length=10000)
    relation_id: str | None = None
    review: Literal["pending", "accepted", "rejected"] = "pending"


class LipidFilters(Controls):
    query: str = Field(default="", max_length=1000)
    category: str = ""
    main_class: str = ""
    sub_class: str = ""
    candidates: Literal["all", "top", "manual"] = "all"
    isotopes: Literal["all", "hide", "only"] = "all"
    review: Literal["all", "accepted"] = "all"
    adduct_mode: Literal["all", "strongest", "specified"] = "all"
    adducts: list[str] = Field(default_factory=list, max_length=8)
    include_unannotated: bool = True


class LipidQuery(LipidActivate):
    filters: LipidFilters = Field(default_factory=LipidFilters)
    feature_id: str = ""
    offset: int = Field(default=0, ge=0)
    relation_offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class LipidCharts(LipidActivate):
    filters: LipidFilters = Field(default_factory=LipidFilters)
    view: LipidChartOptions = Field(default_factory=LipidChartOptions)


class LipidRepresentative(LipidActivate):
    database_id: str
    feature_id: str = ""


class LipidExport(LipidCharts):
    filters: LipidFilters = Field(default_factory=LipidFilters)
    kind: Literal[
        "matrix",
        "candidates",
        "isotopes",
        "rules",
        "charts",
        "pie",
        "feature_nodes",
        "feature_edges",
        "molecule_nodes",
        "molecule_edges",
        "network_evidence",
    ] = "matrix"
