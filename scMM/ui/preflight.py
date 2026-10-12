"""Human-readable views of the frozen extraction request."""
# ruff: noqa: RUF001

from html import escape

import pandas as pd
import panel as pn

from scMM.application.parameters import PROCESSING_HELP

from .presentation import ordinary_number

GROUPS = {
    "提取": (
        "extraction_method",
        "ref_mz",
        "mz_min",
        "mz_max",
        "cell_snr",
        "peak_snr",
        "feature_snr_threshold",
        "max_zero_frac",
    ),
    "参考离子": ("reference_mz", "reference_mode", "reference_ppm_tol"),
    "合谱与对齐": (
        "ppm_tol",
        "resolution",
        "resample_points_per_fwhm",
        "ms_peak_snr_threshold",
    ),
    "基线与资源": (
        "baseline_filter_size",
        "noise_window",
        "n_jobs",
        "feature_block_size",
    ),
}
UNITS = {
    "ref_mz": "m/z",
    "mz_min": "m/z",
    "mz_max": "m/z",
    "reference_mz": "m/z",
    "ppm_tol": "ppm",
    "reference_ppm_tol": "ppm",
    "baseline_filter_size": "扫描帧",
    "noise_window": "扫描帧",
    "feature_block_size": "特征",
    "n_jobs": "进程",
}
SNR_ONLY = {
    "reference_mz",
    "reference_mode",
    "reference_ppm_tol",
    "feature_snr_threshold",
    "noise_window",
    "feature_block_size",
}


class ParameterTable(pn.pane.DataFrame):
    """Native cell tooltips keep explanations out of the table columns."""

    def _transform_object(self, obj):
        if not isinstance(obj, pd.DataFrame):
            return super()._transform_object(obj)
        displayed = obj.copy()
        displayed["参数"] = [
            f'<span title="{escape(PROCESSING_HELP[key], quote=True)}">{escape(key)}</span>'
            for key in obj["参数"]
        ]
        html = displayed.to_html(index=False, escape=False, classes="panel-df", border=0)
        return {"object": escape(html)}


def parameter_source(sample):
    if sample is None:
        return "项目默认"
    return {"sample": "样本覆盖", "project": "项目默认"}.get(
        sample.get("parameter_source"), "来源未记录"
    )


def parameter_value(key, value, parameters):
    if key == "peak_snr" and parameters["extraction_method"] != "legacy":
        return "不适用于 SNR"
    if key in SNR_ONLY and parameters["extraction_method"] == "legacy":
        return "不适用于 legacy"
    if isinstance(value, (tuple, list)):
        return ", ".join(f"{v:.4f}" for v in value) or "使用 ref_mz"
    if key in {"ref_mz", "mz_min", "mz_max"}:
        return f"{value:.4f}"
    if key == "n_jobs" and value == -1:
        return "全部 CPU"
    return ordinary_number(value) if isinstance(value, (int, float)) else str(value)


def parameter_table(parameters, *, sample=None):
    rows = []
    for group, keys in GROUPS.items():
        for key in keys:
            if key in parameters:
                source = parameter_source(sample)
                if key in {"mz_min", "mz_max"} and sample and source == "项目默认":
                    source = "自动计算" if sample.get("auto_mz_range") else source
                rows.append(
                    {
                        "类别": group,
                        "参数": key,
                        "值": parameter_value(key, parameters[key], parameters),
                        "单位": UNITS.get(key, "—"),
                        "来源": source,
                    }
                )
    return pd.DataFrame(rows)


def request_view(request, *, automatic_range=False):
    samples, base = request["samples"], request["parameters"]
    strategy = "共同特征" if request["feature_strategy"] == "shared" else "独立选峰后合并"
    algorithms = ", ".join(dict.fromkeys(s["parameters"]["extraction_method"] for s in samples))
    low = min(s["parameters"]["mz_min"] for s in samples)
    high = max(s["parameters"]["mz_max"] for s in samples)
    summary = (
        f"**预检通过 · {len(samples)} 个样本** · {strategy} · {escape(algorithms)}\n\n"
        f"实际提取范围：**{low:.4f}–{high:.4f} m/z**"
        + ("（各样本范围见下表）" if strategy != "共同特征" else "")
        + "。修改样本或参数后需重新检查。"
    )
    common = parameter_table(base)
    if automatic_range:
        common.loc[common["参数"].isin(["mz_min", "mz_max"]), "来源"] = "自动计算"
    differences, full = [], []
    for sample in samples:
        values = sample["parameters"]
        changed = [
            f"{key} = {parameter_value(key, value, values)}"
            for key, value in values.items()
            if value != base[key]
        ]
        source = parameter_source(sample)
        auto = source == "项目默认" and (sample.get("auto_mz_range") or automatic_range)
        differences.append(
            {
                "样本": sample["name"],
                "参数来源": source,
                "extraction_method": values["extraction_method"],
                "mz_min": values["mz_min"],
                "mz_max": values["mz_max"],
                "范围来源": "自动计算" if auto else "已配置",
                "与公共参数的差异": "；".join(changed) or "一致",
            }
        )
        full.append(
            (
                sample["name"],
                ParameterTable(
                    parameter_table(values, sample={**sample, "auto_mz_range": bool(auto)}),
                    index=False,
                    sizing_mode="stretch_width",
                ),
            )
        )
    view = pn.Column(
        summary,
        "### 公共参数",
        ParameterTable(common, index=False),
        "### 样本参数与差异",
        pn.pane.DataFrame(pd.DataFrame(differences), index=False),
        pn.Accordion(*full),
        sizing_mode="stretch_width",
    )
    return view
