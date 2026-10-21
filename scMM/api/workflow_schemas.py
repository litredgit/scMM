"""Strict contracts for scientific controls; algorithms use the shared application layer."""

from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator

from .schemas import RequestModel, RevisionRequest


class Controls(RequestModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Parameters(RevisionRequest):
    parameters: dict[str, Any]
    sample_id: str | None = None
    strategy: Literal["shared", "independent"] | None = None
    merge_ppm: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    auto_ranges: bool | None = None
    cell_type: str | None = None


class SampleRequest(RevisionRequest):
    sample_id: str


class PreviewRequest(SampleRequest):
    parameters: dict[str, Any]


class PreviewCollect(RevisionRequest):
    job_id: str


class RawPlot(Controls):
    sample_id: str
    kind: Literal["tic", "eic", "sum", "single"]
    ms_level: int = Field(default=1, ge=1)
    rt_range: list[float] | None = Field(default=None, min_length=2, max_length=2)
    mz_range: list[float] = Field(
        default_factory=lambda: [100.0, 1000.0], min_length=2, max_length=2
    )
    references: list[float] = Field(default_factory=list, max_length=100)
    ppm: float = Field(default=10.0, gt=0)
    scan_index: int = Field(default=0, ge=0)
    fast: bool = True
    bins: int = Field(default=20000, ge=2, le=1000000)
    resolution: float = Field(default=35000.0, gt=0)
    points_per_fwhm: float = Field(default=3.0, gt=0)
    normalize: bool = False


class BatchRequest(RevisionRequest):
    path: str


class StartBatch(RevisionRequest):
    retry_path: str | None = None


class ReviewBatch(BatchRequest):
    ids: list[str] = Field(min_length=1)
    compare: bool = False


class Operation(RevisionRequest):
    operation: Literal[
        "filter",
        "normalize",
        "impute",
        "remove_outliers",
        "restore",
        "reset",
        "reduce",
        "cluster",
        "differential",
        "markers",
        "network",
        "train",
        "explain_shap",
        "save_latent",
    ]
    options: dict[str, Any] = Field(default_factory=dict)
    preview: bool = False


class Filter(Controls):
    min_total: float = Field(default=0.0, ge=0)
    min_detected: float = Field(default=0.2, ge=0, le=1)
    min_feature_fraction: float = Field(default=0.0, ge=0, le=1)


class Normalize(Controls):
    method: Literal["total", "max", "pqn", "zscore", "log", "minmax", "quantile"]
    scale: float = Field(default=1.0, gt=0)
    axis: Literal[0, 1] | None = None
    reference: Literal["median", "mean"] = "median"
    pseudo: float = Field(default=1e-6, ge=0)

    @field_validator("axis", mode="before")
    @classmethod
    def strict_axis(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("axis must be an integer 0 or 1")
        return value


class Impute(Controls):
    method: Literal["mean", "median", "most_frequent", "knn"] = "median"
    n_neighbors: int = Field(default=5, ge=1)
    weights: Literal["uniform", "distance"] = "uniform"


class Outliers(Controls):
    contamination: float = Field(default=0.05, gt=0, le=0.5)
    random_state: int = Field(default=42, ge=0, le=2147483647)

    n_estimators: int = Field(default=100, ge=1, le=10000)
    max_samples: str | int | float = "auto"
    max_features: str | int | float = 1.0
    bootstrap: bool = False


class Restore(Controls):
    layer: str


class Reduction(Controls):
    method: Literal["pca", "umap", "tsne", "isomap", "lle"]
    store_key: str = Field(min_length=1, max_length=200)
    use_rep: str = "X"
    n_components: int = Field(default=2, ge=1, le=1000)
    scale: bool = False
    random_state: int = Field(default=42, ge=0, le=2147483647)
    n_neighbors: int = Field(default=15, ge=2)
    perplexity: float = Field(default=30.0, ge=1)
    pca_components: int | None = Field(default=None, ge=1)
    whiten: bool = False
    min_dist: float = Field(default=0.3, ge=0, le=1)
    metric: Literal["euclidean", "manhattan", "cosine"] = "euclidean"
    learning_rate: float | Literal["auto"] = "auto"
    max_iter: int = Field(default=1000, ge=250)


class Cluster(Controls):
    method: Literal["kmeans", "hierarchical", "dbscan", "leiden", "louvain"]
    use_rep: str = "X"
    key: str = Field(default="clusters", min_length=1, max_length=200)
    n_clusters: int = Field(default=3, ge=2)
    n_neighbors: int = Field(default=15, ge=1)
    random_state: int = Field(default=42, ge=0, le=2147483647)
    eps: float = Field(default=0.5, gt=0)
    min_samples: int = Field(default=5, ge=1)
    resolution: float = Field(default=1.0, gt=0)
    n_init: int = Field(default=10, ge=1)
    max_iter: int = Field(default=300, ge=1)
    tol: float = Field(default=1e-4, ge=0)
    linkage: Literal["ward", "complete", "average", "single"] = "ward"
    metric: Literal["euclidean", "manhattan", "cosine"] = "euclidean"
    n_iterations: int = Field(default=2, ge=-1)
    threshold: float = Field(default=1e-7, ge=0)
    max_level: int | None = Field(default=None, ge=1)


class Markers(Controls):
    group_key: str
    method: Literal["mannwhitney", "welch", "classifier"] = "mannwhitney"
    layer: str | None = None


class Differential(Markers):
    method: Literal["mannwhitney", "welch"] = "mannwhitney"
    group_a: str
    group_b: str


class Network(Controls):
    method: Literal["pearson", "spearman", "kendall"] = "pearson"
    min_abs_correlation: float = Field(default=0.7, ge=0, le=1)
    top_features: int = Field(default=50, ge=1, le=1000)
    layer: str | None = None


class Train(Controls):
    label_key: str
    group_key: str | None = None
    layer: str | None = None
    model: Literal["logistic", "lda", "plsda", "random_forest"] = "logistic"
    cv: int = Field(default=5, ge=2, le=100)
    test_size: float = Field(default=0.2, gt=0, lt=1)
    calibration_bins: int = Field(default=10, ge=2, le=1000)
    smote: bool = False
    model_params: dict[str, Any] = Field(default_factory=dict)
    random_state: int = Field(default=42, ge=0, le=2147483647)


class Shap(Controls):
    max_background: int = Field(default=100, ge=1, le=1000)
    max_samples: int = Field(default=100, ge=1, le=1000)
    seed: int = Field(default=42, ge=0, le=2147483647)


class Latent(Controls):
    key: str = Field(min_length=1, max_length=200)


class Invalidate(RevisionRequest):
    names: list[Literal["differential", "markers", "network", "supervised", "shap"]]


class Plot(RevisionRequest):
    kind: Literal[
        "embedding",
        "volcano",
        "violin",
        "network_plot",
        "shap_plot",
        "roc",
        "pr",
        "calibration",
        "confusion",
        "heatmap",
        "feature_scatter",
        "shap_beeswarm",
        "shap_waterfall",
        "shap_dependence",
    ]
    options: dict[str, Any] = Field(default_factory=dict)


class ConfusionPlot(Controls):
    normalize: bool = False


class FeatureScatterPlot(Controls):
    feature_a: str = Field(min_length=1)
    feature_b: str = Field(min_length=1)
    layer: str | None = None
    color_key: str | None = None
    regression: bool = True


class HeatmapPlot(Controls):
    features: list[str] = Field(min_length=1, max_length=1000)
    layer: str | None = None
    group_key: str | None = None
    sample_key: str | None = None
    equal_samples: bool = False
    zscore: bool = True
    cluster_rows: bool = True
    cluster_columns: bool = True


class ShapPlot(Controls):
    class_index: int = Field(default=0, ge=0)
    cell_index: int = Field(default=0, ge=0)
    feature: str | None = None
    top: int = Field(default=20, ge=1, le=100)


class EmbeddingPlot(Controls):
    key: str
    color: str | None = None
    dimensions: list[int] = Field(default_factory=lambda: [1, 2], min_length=2, max_length=3)


class CellSpectra(RevisionRequest):
    cells: list[str] = Field(min_length=1, max_length=2)
    source: Literal["matrix", "apex", "window"] = "matrix"
    normalization: Literal["raw", "max", "tic"] = "raw"
    mirror: bool = False
    average: bool = False


class FigureData(Controls):
    figure: dict[str, Any]


class FigurePDF(Controls):
    svg: str = Field(max_length=32 * 1024**2)
    width_mm: float = Field(default=89, ge=20, le=600)
    height_mm: float = Field(default=65, ge=20, le=600)


class BatchSignal(RevisionRequest):
    path: str
    sample_id: str


class VolcanoPlot(Controls):
    fdr: float = Field(default=0.05, ge=0, le=1)
    fold_change: float = Field(default=1.0, ge=0)
    labels: int = Field(default=10, ge=0, le=100)
    order: Literal["fdr", "effect", "p_value", "intensity"] = "fdr"


class ViolinPlot(Controls):
    features: list[str] = Field(max_length=12)
    hide_zero: bool = False
    columns: int = Field(default=3, ge=1, le=3)


class Export(RevisionRequest):
    root: str
    directory: str = "."
    filename: str


class ViewSettings(RevisionRequest):
    analysis: dict[str, Any]
    legend: Literal["right", "top_left", "top_right", "bottom_left", "bottom_right", "hidden"] = (
        "right"
    )


class SavedPlan(RevisionRequest):
    root: str
    path: str


class ExecutePlan(RevisionRequest):
    token: str


class RestoreTrash(RevisionRequest):
    entry: str


class Preferences(Controls):
    presets: dict[str, float]
    selected: str


OPERATIONS = {
    "filter": Filter,
    "normalize": Normalize,
    "impute": Impute,
    "remove_outliers": Outliers,
    "restore": Restore,
    "reset": Controls,
    "reduce": Reduction,
    "cluster": Cluster,
    "differential": Differential,
    "markers": Markers,
    "network": Network,
    "train": Train,
    "explain_shap": Shap,
    "save_latent": Latent,
}
PLOTS = {
    "confusion": ConfusionPlot,
    "heatmap": HeatmapPlot,
    "feature_scatter": FeatureScatterPlot,
    "shap_plot": ShapPlot,
    "shap_beeswarm": ShapPlot,
    "shap_waterfall": ShapPlot,
    "shap_dependence": ShapPlot,
    "embedding": EmbeddingPlot,
    "volcano": VolcanoPlot,
    "violin": ViolinPlot,
}


def options_for(model, options):
    try:
        return model.model_validate(options).model_dump()
    except ValidationError as exc:
        from fastapi.exceptions import RequestValidationError

        raise RequestValidationError(exc.errors()) from exc


class Presentation(RevisionRequest):
    key: str = Field(min_length=1, max_length=200)
    position: (
        Literal["right", "top_left", "top_right", "bottom_left", "bottom_right", "hidden"] | None
    ) = None
    order: list[str] | None = Field(default=None, max_length=5000)
