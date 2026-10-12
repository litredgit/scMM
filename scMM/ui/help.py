"""Chinese hover help for stable parameter identifiers."""
# ruff: noqa: RUF001

from typing import ClassVar

import panel as pn
import param

from scMM.application.parameters import ANALYSIS_SPECS, PROCESSING_HELP


class HelpCheckbox(pn.widgets.Checkbox):
    description = param.String(default="")
    _rename: ClassVar[dict] = {**pn.widgets.Checkbox._rename, "description": None}

    def _get_model(self, doc, root=None, parent=None, comm=None):
        model = super()._get_model(doc, root, parent, comm)
        model.html_attributes = {**model.html_attributes, "title": self.description}
        return model


UI_HELP = {
    **PROCESSING_HELP,
    **{key: spec[3] for key, spec in ANALYSIS_SPECS.items()},
    "min_total": "细胞总强度下限；低于阈值的细胞会被筛除。",
    "min_detected": "细胞中强度大于零的最小特征数；低于阈值的细胞会被筛除。",
    "feature_fraction": "特征在细胞中的最小检出比例（0–1）；检出定义为强度大于零。",
    "contamination": "异常细胞检测的预期异常比例，范围 0.001–0.5。",
    "operation": "选择下一项预处理操作；应用会更新当前矩阵并清除下游分析结果。",
    "pca_input": "UMAP 前先进行 PCA，减少输入维度；所用参数随分析记录保存。",
    "pca_dimensions": "UMAP 输入的 PCA 维数，受细胞数和特征数限制。",
    "whiten": "对 PCA 各主成分进行白化，使其方差归一。",
    "min_dist": "UMAP 中点之间的最小距离；较小值通常使局部分布更紧密。",
    "metric": "计算样本间距离的方法：欧氏、曼哈顿或余弦距离。",
    "learning_rate": "t-SNE 学习率；auto 自动选择，也可填写正数。",
    "max_iter": "t-SNE 最大迭代次数，至少 250 次。",
    "scale": "降维前按特征标准化；会改变各特征对距离的贡献。",
    "embedding_key": "新嵌入在 AnnData.obsm 中的名称；已有同名结果不能覆盖。",
    "cluster_key": "新细胞簇标签在 AnnData.obs 中的列名；已有同名列不能覆盖。",
    "representation": "降维和聚类使用的输入：当前矩阵 X 或已有嵌入。",
    "embedding_view": "选择要展示的已有嵌入。",
    "color_source": "选择按细胞注释、特征强度着色，或不着色。",
    "color": "选择着色的注释列或特征；连续数值使用颜色条。",
    "color_search": "按列名、特征名或 m/z 筛选着色选项。",
    "color_sort": "特征着色选项的排序依据：均值、总量、中位数、检出比例、m/z 或名称。",
    "color_descending": "启用时将着色特征按所选指标降序排列。",
    "group": "探索性比较使用的分组字段；细胞数不等于独立生物重复。",
    "group_a": "比较的第一组，效应方向按第一组相对第二组解释。",
    "group_b": "比较的第二组，须与第一组不同。",
    "diff_layer": "差异分析使用的当前矩阵 X 或历史层。",
    "model_layer": "监督模型使用的当前矩阵 X 或历史层。",
    "label": "监督模型预测的类别标签列。",
    "sample_group": "用于训练、测试和交叉验证分组的独立来源字段；不分组时仅作细胞级探索。",
    "smote": "仅在训练折内进行 SMOTE；需满足各类别样本量要求。",
    "lda_solver": "LDA 求解器；svd 可生成潜在坐标，其他求解器按模型能力提供结果。",
    "latent_key": "监督模型潜在坐标的保存名称；已有同名嵌入不能覆盖。",
    "features": "选择小提琴图中展示的特征；数量受页面上限约束。",
    "hide_zero": "只在小提琴图显示时隐藏零值，不改变检验、矩阵或导出数据。",
    "volcano_fdr": "火山图的 FDR 阈值，仅控制显示和标签筛选。",
    "volcano_effect": "火山图的效应大小阈值，仅控制显示和标签筛选。",
    "volcano_labels": "火山图自动标注的特征数量上限。",
    "volcano_order": "火山图自动标签的排序依据。",
    "target_mz": "提取离子流图的目标 m/z，仅控制原始谱展示。",
    "ppm": "提取离子流图的质量容差，单位 ppm。",
    "ms_level": "原始谱展示使用的质谱级别。",
    "more_references": "额外显示的 EIC 参考 m/z，逗号分隔，不改变提取参数。",
    "validation_mode": "选择独立来源验证或细胞级探索；细胞级探索不代表独立来源泛化能力。",
}
ALIASES = {
    "dimensions": "n_components",
    "neighbors": "n_neighbors",
    "seed": "random_state",
    "cluster_method": "clustering",
    "clusters": "n_clusters",
    "diff_method": "differential_method",
    "ms_peak_snr": "ms_peak_snr_threshold",
    "points_per_fwhm": "resample_points_per_fwhm",
    "baseline_size": "baseline_filter_size",
}


def parameter_help(owner):
    for name, widget in vars(owner).items():
        key = ALIASES.get(name, name)
        if (
            isinstance(widget, pn.widgets.Widget)
            and "description" in widget.param
            and key in UI_HELP
        ):
            widget.description = UI_HELP[key]
    for key, widget in getattr(owner, "parameter_widgets", {}).items():
        widget.label = key
        if "description" in widget.param:
            widget.description = PROCESSING_HELP[key]


def task_message(message):
    """Translate known worker stages; preserve diagnostic errors and sample names."""
    stages = {
        "Worker no longer running": "处理进程已退出",
        "Waiting for worker": "等待处理进程",
        "Preparing features": "准备特征",
        "Preparing shared features": "准备共同特征",
        "Stopped before extraction": "已在提取前停止",
        "Stopped; completed samples retained": "已停止，保留完成的样本",
        "Review sample outcomes before building the dataset": "处理结束，请选择成功样本建立当前数据集",
        "Extracting cell features": "提取细胞特征",
        "Extracting SNR cell features": "提取 SNR 细胞特征",
        "Cell feature extraction complete": "细胞特征提取完成",
    }
    if message in stages:
        return stages[message]
    for prefix, translated in (
        ("Shared spectrum ", "共同合谱 "),
        ("Extracting ", "正在提取 "),
        ("Finished ", "已完成 "),
        ("Worker startup failed: ", "处理进程启动失败："),
    ):
        if message.startswith(prefix):
            return translated + message[len(prefix) :]
    prefix, separator, stage = message.rpartition("% ")
    if separator:
        return prefix + separator + stages.get(stage, stage)
    return message


TOOLTIP_STYLE = """
:host { white-space: normal; overflow-wrap: anywhere; box-sizing: border-box;
  max-width: min(360px, calc(100vw - 24px));
  max-height: calc(50vh - 36px); overflow: auto; }
"""


def configure_help(_view, root):
    """Keep Panel help in the viewport, including newly mounted pages."""
    from bokeh.events import DocumentReady
    from bokeh.models import Column, CustomJS, Tooltip
    from bokeh.models.widgets import InputWidget

    from .presentation import presentation_views

    widgets = []
    for view in presentation_views(_view):
        mounted = view._models.get(root.id)
        if mounted is None and root.document is not None:
            mounted = next(
                (pair for pair in view._models.values() if pair[0].document is root.document), None
            )
        if mounted is None or not isinstance(mounted[0], InputWidget):
            continue
        model = mounted[0]
        tooltip = model.description
        if not isinstance(tooltip, Tooltip):
            continue
        # Panel's default attachment is fixed to the right. Vertical attachment
        # flips above/below and clamps horizontally; the height cap guarantees
        # room on at least one side of the help button.
        tooltip.position = "top_center"
        tooltip.attachment = "vertical"
        tooltip.stylesheets = [TOOLTIP_STYLE]
        widgets.append(model)
    callbacks = root.js_event_callbacks.get("document_ready", [])
    callback = getattr(root.document, "_scmm_help_callback", None) or next(
        (cb for cb in callbacks if cb.name == "scmm-help-keyboard"), None
    )
    if not widgets:
        if callback is not None:
            callback.args = {"helper": callback, "widgets": []}
        return
    if callback is None:
        callback = CustomJS(
            name="scmm-help-keyboard",
            code="""
              requestAnimationFrame(async () => {
                const roots = Object.values(Bokeh.index);
                await Promise.all(roots.map(view => view.ready));
                for (const widget of helper.args.widgets) {
                  const field = widget.document?.views_manager?.find_one(widget) ||
                    roots.map(view => view.owner.find_one(widget)).find(Boolean);
                  if (!field || field.is_destroyed) continue;
                  const bind = () => {
                    const icon = field.desc_el;
                    if (!icon || icon.dataset.scmmHelp) return;
                    icon.dataset.scmmHelp = "true";
                    icon.tabIndex = 0;
                    icon.setAttribute("role", "button");
                    icon.setAttribute("aria-label", `${widget.title}：帮助`);
                    const tip = widget.description;
                    icon.addEventListener("focus", () => tip.visible = true);
                    icon.addEventListener("blur", () => tip.visible = false);
                    icon.addEventListener("keydown", event => {
                      if (event.key === "Escape") {
                        tip.visible = false;
                      } else if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        tip.visible = !tip.visible;
                        tip.closable = tip.visible;
                      }
                    });
                  };
                  bind();
                  if (!field.scmmHelpObserver) {
                    const observer = new MutationObserver(bind);
                    observer.observe(field.shadow_el, {childList: true, subtree: true});
                    field.scmmHelpObserver = observer;
                    field.removed.connect(() => observer.disconnect());
                  }
                }
              });
            """,
        )
        # Templates preprocess an unmounted synthetic root, so bind to real
        # models as well. Column changes also cover pages mounted after load.
        if root.document is not None:
            root.document._scmm_help_callback = callback
        root.js_on_event(DocumentReady, callback)
        widgets[0].js_on_event(DocumentReady, callback)
    for column in root.select({"type": Column}):
        if callback not in column.js_property_callbacks.get("change:children", []):
            column.js_on_change("children", callback)
    for model in root.references():
        if "collapsed" in model.properties() and callback not in model.js_property_callbacks.get(
            "change:collapsed", []
        ):
            model.js_on_change("collapsed", callback)
    callback.args = {"helper": callback, "widgets": widgets}
