"""Private registrations for the three optional analyses shipped with scMM."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BundledAnalysis:
    label: str
    operations: tuple[str, ...]
    plots: tuple[str, ...]
    results: tuple[str, ...] = ()


BUNDLED = {
    "network": BundledAnalysis("相关网络", ("network",), ("network_plot",), ("network",)),
    "supervised": BundledAnalysis(
        "监督与 SHAP",
        ("train", "explain_shap", "save_latent"),
        (
            "roc",
            "pr",
            "calibration",
            "confusion",
            "shap_plot",
            "shap_beeswarm",
            "shap_waterfall",
            "shap_dependence",
        ),
        ("supervised", "shap"),
    ),
    "time": BundledAnalysis("伪时间与趋势", (), ("time_plot",)),
}
OPERATIONS = {operation: key for key, plugin in BUNDLED.items() for operation in plugin.operations}
PLOTS = {plot: key for key, plugin in BUNDLED.items() for plot in plugin.plots}
RESULTS = {result: key for key, plugin in BUNDLED.items() for result in plugin.results}
