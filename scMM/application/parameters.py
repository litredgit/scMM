"""Validated workbench defaults. External JSON contains values, never code or paths."""
# ruff: noqa: RUF001

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .processing import ProcessingParameters

PROCESSING_HELP = {
    "ref_mz": "参考离子 m/z，必须位于提取范围内；不是 EIC 图的显示范围。",
    "ppm_tol": "扫描峰对齐到公共特征的质量容差（ppm）。",
    "resolution": "m/z 200 处分辨率，控制合谱的变分辨率网格。",
    "resample_points_per_fwhm": "每个半峰宽的网格点数；越大计算和内存开销越高。",
    "ms_peak_snr_threshold": "总谱候选峰的信噪阈值，不等同于细胞特征 SNR。",
    "cell_snr": "参考信号/基线比值阈值，用于划定细胞窗口。",
    "peak_snr": "仅 legacy 使用：窗口强度相对基线阈值，不是真实噪声标准差 SNR。",
    "baseline_filter_size": "基线窗口大小（扫描帧），不是秒。",
    "max_zero_frac": "允许特征在细胞中取零值的最大比例，范围 0–1。",
    "n_jobs": "并行任务数；-1 为全部 CPU；分块提取仍逐块执行。",
    "mz_min": "正式提取 m/z 下限（包含）；影响合谱、特征选择和后续对齐。",
    "mz_max": "正式提取 m/z 上限（包含）；与谱图显示范围独立。",
    "extraction_method": "legacy 保持旧强度定义；snr_v1 使用扣基线丰度和背景噪声标准差。",
    "reference_mz": "SNR 模式附加参考 m/z；空列表使用 ref_mz。所有参考须在提取范围内。",
    "reference_mode": "多个参考窗口取 union（并集）或 intersection（交集）。",
    "reference_ppm_tol": "SNR 参考离子匹配的最大质量误差（ppm）。",
    "feature_snr_threshold": "仅 snr_v1 使用：扣基线峰顶/背景噪声标准差的阈值。",
    "noise_window": "局部背景噪声估计窗口（扫描帧），至少 2。",
    "feature_block_size": "每块特征数；控制临时矩阵内存，不改变科学参数。",
}

# default, accepted type, lower/upper bound or choices, explanation
ANALYSIS_SPECS = {
    "normalization": (
        "total",
        str,
        ("total", "max", "pqn", "zscore", "log", "minmax", "quantile"),
        "归一化方法；zscore 会产生负值，不能直接做丰度差异检验。",
    ),
    "imputation": (
        "median",
        str,
        ("median", "mean", "knn"),
        "零值视为缺失；插补和全数据变换可能造成监督学习泄漏。",
    ),
    "reduction": (
        "pca",
        str,
        ("pca", "umap", "tsne", "isomap", "lle"),
        "降维方法；输入可为当前 X 或明确选择的 obsm。",
    ),
    "n_components": (2, int, (1, 1000), "输出维数，受样本数、特征数与算法限制。"),
    "n_neighbors": (15, int, (2, 100000), "流形/图方法邻居数，必须少于细胞数。"),
    "perplexity": (30.0, float, (1.0, 100000.0), "t-SNE perplexity，必须少于细胞数。"),
    "random_state": (42, int, (0, 2147483647), "随机种子，随分析来源记录保存。"),
    "clustering": (
        "kmeans",
        str,
        ("kmeans", "dbscan", "hierarchical", "leiden", "louvain"),
        "聚类方法；DBSCAN 的 -1 为噪声，不作为生物学簇。",
    ),
    "n_clusters": (3, int, (2, 10000), "KMeans/层次聚类目标簇数。"),
    "differential_method": (
        "mannwhitney",
        str,
        ("mannwhitney", "welch"),
        "两组细胞比较；生物重复推断需先按重复汇总。",
    ),
    "model": (
        "logistic",
        str,
        ("logistic", "lda", "plsda", "random_forest"),
        "监督模型；样本组互斥划分和 CV，不能消除上游预处理泄漏。",
    ),
    "test_size": (0.2, float, (0.01, 0.99), "holdout 比例；训练和测试均须包含所有类别。"),
    "cv": (5, int, (2, 100), "交叉验证折数，受每类样本数和独立组数限制。"),
    "calibration_bins": (10, int, (2, 1000), "校准曲线的 quantile 分箱数，不执行概率重新校准。"),
}


@dataclass(frozen=True)
class WorkbenchDefaults:
    processing: ProcessingParameters
    analysis: dict

    def to_dict(self):
        return {"processing": asdict(self.processing), "analysis": dict(self.analysis)}


def load_defaults(path: str | Path | None = None) -> WorkbenchDefaults:
    """CLI path wins over SCMM_UI_CONFIG; invalid/unknown keys fail explicitly."""
    path = path or os.environ.get("SCMM_UI_CONFIG")
    override = {} if path is None else json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(override, dict) or set(override) - {"processing", "analysis"}:
        raise ValueError("config sections must be processing and/or analysis")
    processing = asdict(ProcessingParameters(ref_mz=734.5929))
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
    return WorkbenchDefaults(parameters, analysis)
