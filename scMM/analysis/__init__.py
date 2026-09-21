"""Optional downstream analysis for AnnData or CyESIData.to_anndata()."""

from .quality import quality_metrics, render_quality_report
from .statistics import differential_features, marker_features
from .supervised import PLSDAClassifier, SupervisedAnalyzer

__all__ = [
    "PLSDAClassifier",
    "SupervisedAnalyzer",
    "differential_features",
    "marker_features",
    "quality_metrics",
    "render_quality_report",
]
