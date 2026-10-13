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
    "ref_mz": "用于识别细胞窗口的参考离子 m/z，须依据实验明确选择且位于提取范围内。SNR reference_mz 留空时使用此值；与图形显示范围分别设置。",
    "ppm_tol": "扫描峰对齐到共同特征轴时允许的相对质量误差，单位 ppm（百万分之一）。值越大匹配越宽松；与参考离子的 reference_ppm_tol 分开设置。",
    "resolution": "仪器在 m/z 200 处的分辨率，用于构建随质量变化的高分辨率合谱网格。须为正数，应按实际仪器设置；不是最终 m/z 小数位数。",
    "resample_points_per_fwhm": "每个半峰全宽（FWHM）内的合谱网格点数，正数。较大值使网格更细并增加计算和内存；与仪器分辨率共同决定网格。",
    "ms_peak_snr_threshold": "合并谱挑选候选 m/z 特征峰的信噪比阈值，正数。提高会减少弱候选峰；与细胞窗口内的 feature_snr_threshold 属于不同筛选阶段。",
    "cell_snr": "参考通道信号除以局部基线的阈值，超过此值的连续扫描形成候选细胞窗口。它是信号/基线倍数，不是按噪声标准差定义的特征 SNR。",
    "peak_snr": "仅 legacy 使用的窗口强度与基线比值阈值，不是以噪声标准差定义的 SNR。",
    "baseline_filter_size": "沿扫描方向估计局部基线的中值滤波窗口宽度，正整数，单位扫描帧。帧数不是秒，实际覆盖时间取决于扫描间隔；过窄可能将细胞峰计入基线。",
    "max_zero_frac": "提取后一个特征允许的最大零值细胞比例，范围 0–1，例如 0.9 表示最多 90% 细胞为零。零值比例超过阈值会移除特征；与第四步 min_feature_fraction 的处理阶段不同。",
    "n_jobs": "并行进程数；-1 使用全部 CPU，特征块仍按顺序处理。",
    "mz_min": "正式提取的 m/z 下限（含边界），用于合谱、选峰与对齐。须小于上限，并覆盖参考离子；改变图形显示范围不会修改此值。",
    "mz_max": "正式提取的 m/z 上限（含边界），须大于下限并覆盖参考离子。范围越宽通常计算和内存越多；原始谱图的显示范围单独设置。",
    "extraction_method": "legacy 保留历史强度定义；snr_v1 使用扣除基线的丰度和背景噪声。",
    "reference_mz": "SNR 细胞窗口检测的参考离子 m/z 列表，逗号分隔；留空使用 ref_mz。各值须在提取范围内且在 reference_ppm_tol 内匹配到特征；多个离子按 reference_mode 合并。",
    "reference_mode": "多个参考通道的逐扫描判定如何合并：union 任一通道达标即可，intersection 需所有通道同时达标。只填写一个参考离子时两者等效；交集可能减少或清空细胞窗口。",
    "reference_ppm_tol": "参考离子与特征轴最近 m/z 匹配允许的最大相对质量误差，单位 ppm。超过阈值会明确报错；与扫描峰对齐 ppm_tol 不同，不会自动放宽。",
    "feature_snr_threshold": "仅 snr（内部标识 snr_v1）使用的特征检出阈值：细胞窗口内扣除基线后的峰顶强度除以背景噪声标准差，超过阈值才计为该细胞中的信号，否则置零。正数；与 cell_snr 的信号/基线倍数定义不同。",
    "noise_window": "SNR 局部噪声估计的扫描窗口宽度，整数且至少 2 帧；使用所有已检测细胞窗口之外的背景估计噪声标准差。单位为扫描帧，不是秒。",
    "feature_block_size": "SNR 分块处理时每块的特征个数，正整数。较小值降低临时内存，可能增加处理开销；不改变特征 SNR 阈值或科学定义。",
}


# default, accepted type, lower/upper bound or choices, explanation
ANALYSIS_SPECS = {
    "normalization": (
        "total",
        str,
        ("total", "max", "pqn", "zscore", "log", "minmax", "quantile"),
        "每次只执行选定的一种归一化或数值变换，不自动串联。total/max 按细胞，zscore/minmax/quantile 默认按特征列；具体公式和零值影响见方法说明。",
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
        "输入为当前 X 或所选嵌入：pca 为线性主成分；umap/tsne 展示邻域结构；isomap 使用邻域图测地距离；lle 根据局部线性关系嵌入。图上距离不直接证明生物学类别或轨迹。",
    ),
    "n_components": (
        2,
        int,
        (1, 1000),
        "新嵌入保留的维数，正整数，受细胞数、输入维数和算法限制。它不是细胞簇数；二维图仅展示嵌入前两个维度。",
    ),
    "n_neighbors": (
        15,
        int,
        (2, 100000),
        "UMAP/Isomap/LLE 或图聚类构建局部邻域时使用的细胞近邻数，整数且须小于细胞数。值影响局部与较大尺度结构，不是目标簇数。",
    ),
    "perplexity": (
        30.0,
        float,
        (1.0, 100000.0),
        "t-SNE 的有效邻域规模控制，正数且须小于细胞数；不是期望簇数。改变它会影响布局，建议结合随机种子核对稳定性。",
    ),
    "random_state": (42, int, (0, 2147483647), "随机种子，随分析溯源保存以便复现。"),
    "clustering": (
        "kmeans",
        str,
        ("kmeans", "dbscan", "hierarchical", "leiden", "louvain"),
        "kmeans 按中心分组，hierarchical 按层次关系分组，dbscan 按密度分组（-1 为噪声）；leiden/louvain 在近邻图上分组。当前 DBSCAN eps/min_samples 固定 0.5/5，图聚类 resolution 固定 1；标签不自动等于生物学类别。",
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
        "mannwhitney 为两组秩和比较，不应无条件解释为中位数检验；welch 为允许方差不同的两组均值比较。当前为细胞级探索，各比较内对全部特征做 BH-FDR；生物重复推断须先按重复聚合。",
    ),
    "model": (
        "logistic",
        str,
        ("logistic", "lda", "plsda", "random_forest"),
        "logistic 为逻辑回归，lda 为线性判别分析，plsda 为基于偏最小二乘的分类，random_forest 为随机森林。按独立来源划分训练/测试/CV；所有模型均不能消除上游全数据预处理泄漏。",
    ),
    "test_size": (
        0.2,
        float,
        (0.01, 0.99),
        "留出测试集的目标比例，0.01–0.99，例如 0.2 为 20%。分组验证按独立来源划分，实际细胞比例可能不同；训练与测试均须包含全部类别。",
    ),
    "cv": (
        5,
        int,
        (2, 100),
        "训练集内部交叉验证的折数，至少 2；每折训练/验证均须覆盖所有类别。分组验证以独立来源为单位，不能仅按细胞数量判断是否足够。",
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
        "pearson 衡量线性相关，spearman 衡量秩的单调关系，kendall 衡量秩的一致性。按跨细胞的特征对计算；相关性不代表因果、时间方向或代谢通路。",
    ),
    "network_threshold": (
        0.7,
        float,
        (0.0, 1.0),
        "仅保留相关系数绝对值达到此阈值的特征连边，范围 0–1，例如 0.7 包含 r≥0.7 和 r≤−0.7。它不是 p 值或 FDR 阈值。",
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
