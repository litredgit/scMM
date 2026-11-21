"""Optional downstream analysis for AnnData or CyESIData.to_anndata()."""

from typing import TYPE_CHECKING

from .quality import quality_metrics, render_quality_report
from .statistics import differential_features, marker_features

if TYPE_CHECKING:
    from .supervised import PLSDAClassifier, SupervisedAnalyzer

__all__ = [
    "PLSDAClassifier",
    "SupervisedAnalyzer",
    "differential_features",
    "marker_features",
    "quality_metrics",
    "render_quality_report",
]


def __getattr__(name):
    if name in {"PLSDAClassifier", "SupervisedAnalyzer"}:
        from . import supervised

        return getattr(supervised, name)
    raise AttributeError(name)
