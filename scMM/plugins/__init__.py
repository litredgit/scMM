"""Public scMM method plugin protocol, version 1."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

API_VERSION = 1
ENTRY_POINT_GROUP = "scmm.methods.v1"

MethodKind = Literal[
    "cell_detection",
    "cell_extraction",
    "annotation",
    "preprocessing",
    "reduction",
    "clustering",
    "statistics",
]
ParameterKind = Literal["integer", "number", "text", "boolean", "choice", "observation"]
Scalar = int | float | str | bool


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    kind: ParameterKind
    default: Scalar | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class Method:
    id: str
    label: str
    kind: MethodKind
    run: Callable
    parameters: tuple[Parameter, ...] = ()
    # Required for cell_extraction. Used for intensity provenance and batch compatibility.
    intensity_definition: str = ""


@dataclass(frozen=True)
class Plugin:
    methods: tuple[Method, ...]
    api_version: int = API_VERSION


@dataclass(frozen=True)
class AlignedScans:
    """Selected MS1 scans by aligned m/z, with metadata in the same row order."""

    signal: "pd.DataFrame"
    scans: "pd.DataFrame"


@dataclass(frozen=True)
class CellEvent:
    """Inclusive window and apex, zero-based on the aligned scan axis."""

    start: int
    apex: int
    stop: int


@dataclass(frozen=True)
class ExtractionInput:
    scans: AlignedScans
    events: tuple[CellEvent, ...]


@dataclass(frozen=True)
class MatrixInput:
    values: "np.ndarray"
    observation_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    observations: "pd.DataFrame"
    observation_kind: str
    source: str
    value_space: str


@dataclass(frozen=True)
class FeatureInput:
    features: "pd.DataFrame"


@dataclass(frozen=True)
class AnnotationCandidate:
    feature_id: str
    name: str
    theoretical_mz: float
    accession: str = ""
    formula: str = ""
    adduct: str = ""


@dataclass(frozen=True)
class StatisticalReport:
    table: "pd.DataFrame"
    # Optional Plotly figure specification with scientific labels and units.
    figure: dict | None = None
