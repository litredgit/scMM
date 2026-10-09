"""Validated workbench defaults. External JSON contains values, never code or paths."""
# ruff: noqa: RUF001

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .preferences import cpu_default, load_preferences
from .processing import ProcessingParameters

PROCESSING_HELP = {
    "ref_mz": "Reference ion m/z; must be within the extraction range, independent of plot limits.",
    "ppm_tol": "Mass tolerance (ppm) used to align scan peaks to common features.",
    "resolution": "Resolving power at m/z 200, used to construct the variable-resolution spectrum grid.",
    "resample_points_per_fwhm": "Grid points per full width at half maximum; higher values require more resources.",
    "ms_peak_snr_threshold": "Candidate-peak signal-to-noise threshold in the summed spectrum.",
    "cell_snr": "Reference signal-to-baseline ratio threshold defining cell windows.",
    "peak_snr": "Legacy window intensity-to-baseline threshold, not a noise-standard-deviation SNR.",
    "baseline_filter_size": "Baseline window width in scan frames, not seconds.",
    "max_zero_frac": "Maximum fraction of zero-valued cells allowed for a feature (0–1).",
    "n_jobs": "Parallel workers; -1 uses all CPUs. Feature blocks are still processed sequentially.",
    "mz_min": "Inclusive extraction lower m/z limit for spectrum merging, feature selection and alignment.",
    "mz_max": "Inclusive extraction upper m/z limit, independent of plot limits.",
    "extraction_method": "legacy retains historical intensities; snr_v1 uses baseline-subtracted abundance and background noise.",
    "reference_mz": "Additional SNR reference masses; empty uses ref_mz. All must be within the extraction range.",
    "reference_mode": "Combine reference windows by union or intersection.",
    "reference_ppm_tol": "Maximum SNR reference-ion matching error in ppm.",
    "feature_snr_threshold": "snr_v1 only: baseline-subtracted apex divided by background noise standard deviation.",
    "noise_window": "Local background noise window in scan frames (at least 2).",
    "feature_block_size": "Features per block; controls temporary memory without changing scientific parameters.",
}


# default, accepted type, lower/upper bound or choices, explanation
ANALYSIS_SPECS = {
    "normalization": (
        "total",
        str,
        ("total", "max", "pqn", "zscore", "log", "minmax", "quantile"),
        "Normalization method; zscore produces negative values unsuitable for abundance differential tests.",
    ),
    "imputation": (
        "median",
        str,
        ("median", "mean", "knn"),
        "Zeros are treated as missing; imputation and whole-dataset transforms can cause supervised-learning leakage.",
    ),
    "reduction": (
        "pca",
        str,
        ("pca", "umap", "tsne", "isomap", "lle"),
        "Reduction method; input is current X or an explicitly selected embedding.",
    ),
    "n_components": (
        2,
        int,
        (1, 1000),
        "Output dimensions, limited by observations, features and the algorithm.",
    ),
    "n_neighbors": (
        15,
        int,
        (2, 100000),
        "Neighbors for manifold/graph methods; must be fewer than cells.",
    ),
    "perplexity": (30.0, float, (1.0, 100000.0), "t-SNE perplexity; must be fewer than cells."),
    "random_state": (42, int, (0, 2147483647), "Random seed, saved with analysis provenance."),
    "clustering": (
        "kmeans",
        str,
        ("kmeans", "dbscan", "hierarchical", "leiden", "louvain"),
        "Clustering method; DBSCAN label -1 denotes noise, not a biological cluster.",
    ),
    "n_clusters": (
        3,
        int,
        (2, 10000),
        "Target number of clusters for KMeans or hierarchical clustering.",
    ),
    "differential_method": (
        "mannwhitney",
        str,
        ("mannwhitney", "welch"),
        "Two-group cell comparison; biological-replicate inference requires replicate-level aggregation.",
    ),
    "model": (
        "logistic",
        str,
        ("logistic", "lda", "plsda", "random_forest"),
        "Supervised model; group-disjoint split/CV does not eliminate upstream preprocessing leakage.",
    ),
    "test_size": (
        0.2,
        float,
        (0.01, 0.99),
        "Holdout fraction; train and test sets must both contain all classes.",
    ),
    "cv": (
        5,
        int,
        (2, 100),
        "Cross-validation folds, limited by class counts and independent groups.",
    ),
    "calibration_bins": (
        10,
        int,
        (2, 1000),
        "Quantile bins for calibration diagnostics; does not recalibrate probabilities.",
    ),
    "network_method": (
        "pearson",
        str,
        ("pearson", "spearman", "kendall"),
        "Feature correlation coefficient; does not imply causation or trajectories.",
    ),
    "network_threshold": (
        0.7,
        float,
        (0.0, 1.0),
        "Retain edges with absolute correlation at least this threshold.",
    ),
    "network_top_features": (
        50,
        int,
        (1, 1000),
        "Top N features by variance, limiting correlation matrix and plot size.",
    ),
    "shap_background": (
        100,
        int,
        (1, 1000),
        "SHAP background observations sampled from training data; no model refitting.",
    ),
    "shap_samples": (
        100,
        int,
        (1, 1000),
        "Maximum test observations explained; mean absolute SHAP across observations and classes.",
    ),
}


@dataclass(frozen=True)
class WorkbenchDefaults:
    processing: ProcessingParameters
    analysis: dict
    processing_overrides: frozenset[str] = frozenset()

    def to_dict(self):
        return {"processing": asdict(self.processing), "analysis": dict(self.analysis)}


def load_defaults(path: str | Path | None = None) -> WorkbenchDefaults:
    """CLI path wins over SCMM_UI_CONFIG; invalid/unknown keys fail explicitly."""
    path = path or os.environ.get("SCMM_UI_CONFIG")
    override = {} if path is None else json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(override, dict) or set(override) - {"processing", "analysis"}:
        raise ValueError("config sections must be processing and/or analysis")
    preferences = load_preferences()
    processing = asdict(
        ProcessingParameters(
            ref_mz=preferences["presets"][preferences["selected"]], n_jobs=cpu_default()
        )
    )
    updates = override.get("processing", {})
    if not isinstance(updates, dict) or set(updates) - set(processing):
        raise ValueError("unknown processing parameter or invalid section")
    for key, value in updates.items():
        default = processing[key]
        if key == "reference_mz":
            if not isinstance(value, list) or any(
                isinstance(v, bool) or not isinstance(v, (float, int)) for v in value
            ):
                raise ValueError("reference_mz must be a list of numbers")
            value = tuple(value)
        elif isinstance(default, str):
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be numeric")
        processing[key] = value
    parameters = ProcessingParameters(**processing)
    analysis = {key: spec[0] for key, spec in ANALYSIS_SPECS.items()}
    updates = override.get("analysis", {})
    if not isinstance(updates, dict) or set(updates) - set(analysis):
        raise ValueError("unknown analysis parameter or invalid section")
    for key, value in updates.items():
        _, kind, limits, _ = ANALYSIS_SPECS[key]
        if kind is str:
            valid = isinstance(value, str) and value in limits
        else:
            valid = (
                not isinstance(value, bool)
                and isinstance(value, (float, int) if kind is float else int)
                and math.isfinite(value)
                and limits[0] <= value <= limits[1]
            )
        if not valid:
            raise ValueError(f"invalid analysis parameter {key}: {value!r}")
        analysis[key] = value
    if set(PROCESSING_HELP) != {field.name for field in fields(ProcessingParameters)}:
        raise RuntimeError("processing parameter help is incomplete")
    return WorkbenchDefaults(parameters, analysis, frozenset(override.get("processing", {})))
