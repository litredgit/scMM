"""Typed annotation, review and filtering contracts."""

from typing import Literal

from pydantic import Field

from .schemas import RevisionRequest
from .workflow_schemas import Controls


class LipidOptions(Controls):
    database: str = ""
    polarity: Literal["pos", "neg", "both"] = "pos"
    adducts: list[str] = Field(min_length=1, max_length=8)
    annotation_ppm: float = Field(default=10.0, ge=0, le=1000)
    isotope_ppm: float = Field(default=10.0, ge=0, le=1000)
    max_isotope_order: int = Field(default=3, ge=1, le=10)
    isotope_tolerance: float = Field(default=0.2, ge=0, le=1)
    min_valid_cells: int = Field(default=20, ge=1)
    intensity_layer: str = ""
    resolution: float = Field(gt=0, le=1e8)


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


class LipidExport(LipidActivate):
    filters: LipidFilters = Field(default_factory=LipidFilters)
    kind: Literal["matrix", "candidates", "isotopes", "rules"] = "matrix"
