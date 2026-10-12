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
    "ref_mz": "参考离子 m/z，必须位于提取范围内；与图形显示范围分别设置。",
    "ppm_tol": "扫描峰对齐到共同特征时使用的质量容差，单位 ppm。",
    "resolution": "m/z 200 处的分辨率，用于构建随质量变化的合谱网格。",
    "resample_points_per_fwhm": "每个半峰全宽（FWHM）的网格点数；越大越消耗计算和内存。",
    "ms_peak_snr_threshold": "合谱中候选峰的信噪比阈值。",
    "cell_snr": "参考信号与基线的比值阈值，用于识别细胞窗口。",
    "peak_snr": "仅 legacy 使用的窗口强度与基线比值阈值，不是以噪声标准差定义的 SNR。",
    "baseline_filter_size": "基线窗口宽度，单位为扫描帧，不是秒。",
    "max_zero_frac": "特征允许的最大零值细胞比例，范围 0–1。",
    "n_jobs": "并行进程数；-1 使用全部 CPU，特征块仍按顺序处理。",
    "mz_min": "提取 m/z 下限（含边界），用于合谱、选峰和对齐。",
    "mz_max": "提取 m/z 上限（含边界），与图形显示范围分别设置。",
    "extraction_method": "legacy 保留历史强度定义；snr_v1 使用扣除基线的丰度和背景噪声。",
    "reference_mz": "SNR 参考离子 m/z 列表，逗号分隔；留空使用 ref_mz，均须在提取范围内。",
    "reference_mode": "多个参考离子的细胞窗口合并方式：union 为并集，intersection 为交集。",
    "reference_ppm_tol": "SNR 参考离子匹配的最大质量误差，单位 ppm。",
    "feature_snr_threshold": "仅 snr_v1 使用：扣除基线后的峰顶强度除以背景噪声标准差。",
    "noise_window": "局部背景噪声窗口宽度，单位为扫描帧，至少 2 帧。",
    "feature_block_size": "每块特征数，用于控制临时内存，不改变科学参数。",
}


# default, accepted type, lower/upper bound or choices, explanation
ANALYSIS_SPECS = {
    "normalization": (
        "total",
        str,
        ("total", "max", "pqn", "zscore", "log", "minmax", "quantile"),
        "归一化或数值变换方法；zscore 会产生负值，不适用于丰度差异检验。",
    ),
    "imputation": (
        "median",
        str,
        ("median", "mean", "knn"),
        "将零值视为缺失进行插补；全数据插补和变换可能造成监督学习的数据泄漏。",
    ),
    "reduction": (
        "pca",
        str,
        ("pca", "umap", "tsne", "isomap", "lle"),
        "降维方法；输入为当前矩阵 X 或所选嵌入。",
    ),
    "n_components": (
        2,
        int,
        (1, 1000),
        "输出维数，受细胞数、特征数和算法限制。",
    ),
    "n_neighbors": (
        15,
        int,
        (2, 100000),
        "流形或图方法的邻居数，须小于细胞数。",
    ),
    "perplexity": (30.0, float, (1.0, 100000.0), "t-SNE 的困惑度，须小于细胞数。"),
    "random_state": (42, int, (0, 2147483647), "随机种子，随分析溯源保存以便复现。"),
    "clustering": (
        "kmeans",
        str,
        ("kmeans", "dbscan", "hierarchical", "leiden", "louvain"),
        "聚类方法；DBSCAN 的 -1 标签表示噪声，不是生物学细胞簇。",
    ),
    "n_clusters": (
        3,
        int,
        (2, 10000),
        "KMeans 或层次聚类的目标簇数。",
    ),
    "differential_method": (
        "mannwhitney",
        str,
        ("mannwhitney", "welch"),
        "两组细胞的探索性比较；生物重复层面的推断需要先按重复聚合。",
    ),
    "model": (
        "logistic",
        str,
        ("logistic", "lda", "plsda", "random_forest"),
        "监督模型；按独立来源划分训练、测试及交叉验证，仍不能消除上游预处理泄漏。",
    ),
    "test_size": (
        0.2,
        float,
        (0.01, 0.99),
        "留出测试集的比例；训练集与测试集均须包含全部类别。",
    ),
    "cv": (
        5,
        int,
        (2, 100),
        "交叉验证折数，受各类别样本数和独立来源数限制。",
    ),
    "calibration_bins": (
        10,
        int,
        (2, 1000),
        "校准诊断使用的分位数分箱数；不对模型概率重新校准。",
    ),
    "network_method": (
        "pearson",
        str,
        ("pearson", "spearman", "kendall"),
        "特征相关系数方法；相关性不代表因果或轨迹。",
    ),
    "network_threshold": (
        0.7,
        float,
        (0.0, 1.0),
        "仅保留相关系数绝对值达到此阈值的连边。",
    ),
    "network_top_features": (
        50,
        int,
        (1, 1000),
        "按方差选择前 N 个特征，限制相关矩阵和图形大小。",
    ),
    "shap_background": (
        100,
        int,
        (1, 1000),
        "从训练数据抽取的 SHAP 背景样本上限；不重新训练模型。",
    ),
    "shap_samples": (
        100,
        int,
        (1, 1000),
        "解释的测试样本上限；汇总样本和类别的 SHAP 绝对值均值。",
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
            ref_mz=preferences["presets"][preferences["selected"]],
            n_jobs=cpu_default(),
            extraction_method="snr_v1",
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
