"""Analysis pages sharing one revision-aware application workspace."""
# ruff: noqa: RUF001

from __future__ import annotations

import json
from html import escape
from io import BytesIO

import pandas as pd
import panel as pn
import plotly.express as px
import plotly.graph_objects as go

from scMM.application.parameters import ANALYSIS_SPECS
from scMM.application.workbench import AnalysisWorkspace, read_dataset

from .analysis_plots import (
    embedding_figure,
    network_figure,
    supervised_figures,
    violin_figure,
    volcano_figure,
)
from .file_browser import FileBrowser
from .layout import PlotWidth, fit_plot


def _plot(title):
    return fit_plot(
        pn.pane.Plotly(
            go.Figure(layout={"title": title}),
            height=380,
            config={"displaylogo": False, "toImageButtonOptions": {"format": "svg"}},
        ),
        "square" if title in {"嵌入", "特征相关网络"} else "analysis",
    )


def _csv(frame):
    return BytesIO(frame.to_csv(index=True).encode("utf-8-sig"))


class WorkbenchPanels:
    """No shared global data/model state: construct once per browser session."""

    def __init__(self, catalog, defaults, processing, on_replace=None):
        self.catalog = catalog
        self.defaults = defaults
        self.processing = processing
        self.on_replace = on_replace
        self.state = AnalysisWorkspace()
        self._refreshing = False
        self._rendered_token = None
        self.summary = pn.pane.Markdown("尚未读取处理结果。")
        self.status = pn.pane.Markdown("")
        self.notice = pn.pane.Markdown(
            "每次换数据或预处理都会使旧分析失效；已经保存的文件不会被删除。"
        )
        self.root = pn.widgets.Select(label="结果存储", options=[r.label for r in catalog.roots])
        self.path = pn.widgets.TextInput(
            label="结果目录 / H5AD 路径", placeholder="相对路径或服务器原生绝对路径"
        )
        self.browser = pn.Column()
        self.trust = pn.widgets.Checkbox(label="我信任所选旧目录中的 pickle 文件（可能执行代码）")
        self.load_button = pn.widgets.Button(label="读取并替换工作数据", color="primary")
        self.import_task = pn.widgets.Button(label="载入当前已完成任务的数据")
        self.root.param.watch(self._browse, "value")
        self.load_button.on_click(lambda _: self.run(self._load))
        self.import_task.on_click(lambda _: self.run(self._load_task))
        self._browse()
        self.data_page = pn.Column(
            "## 数据与处理",
            self.root,
            self.path,
            self.browser,
            self.trust,
            pn.Row(self.load_button, self.import_task),
            self.summary,
            self.notice,
            self.status,
        )
        self._preprocessing_page()
        self._embedding_page()
        self._differential_page()
        self._supervised_page()
        self._results_page()
        self.refresh()

    def field(self, name):
        default, kind, limits, _ = ANALYSIS_SPECS[name]
        value = self.defaults.analysis.get(name, default)
        if kind is str:
            return pn.widgets.Select(label=name, options=list(limits), value=value)
        widget = pn.widgets.IntInput if kind is int else pn.widgets.FloatInput
        return widget(label=name, value=value, start=limits[0], end=limits[1])

    @staticmethod
    def help(*names):
        return pn.pane.Markdown(
            "\n\n".join(f"**{name}**：{ANALYSIS_SPECS[name][3]}" for name in names)
        )

    def _browse(self, _event=None):
        selector = FileBrowser(self.catalog, self.root.value, results=True)
        selector.param.watch(
            lambda e: setattr(self.path, "value", str(e.new[0]) if len(e.new) == 1 else ""), "value"
        )
        self.browser[:] = [selector]

    def run(self, action):
        self.status.object = "计算中；大样本分析可能需要较长时间。"
        try:
            action()
            self.refresh()
            self.status.object = "操作完成。"
        except Exception as exc:
            self.refresh()
            self.status.object = f"❌ {escape(str(exc))}"

    def _load(self):
        if not self.path.value.strip():
            raise ValueError("请选择一个结果目录或 H5AD")
        data = read_dataset(
            self.catalog, self.root.value, self.path.value, trust_pickle=self.trust.value
        )
        self.state.replace(data, source=str(self.catalog.resolve(self.root.value, self.path.value)))
        if self.on_replace:
            self.on_replace()

    def _load_task(self):
        task_id = self.processing._active_task_id
        if task_id is None:
            raise ValueError("先在任务页选择一个已完成任务")
        task = self.processing.tasks.get(task_id)
        if task.status != "succeeded" or task.discarded_at:
            raise ValueError("任务尚未成功完成或已放弃")
        path = self.processing._safe_result_path(task.result_path)
        for root in self.catalog.roots:
            if path.is_relative_to(root.path):
                data = read_dataset(self.catalog, root.label, path, trust_pickle=True)
                self.state.replace(data, source=str(path))
                if self.on_replace:
                    self.on_replace()
                return
        raise PermissionError("任务结果不在开放的存储目录内")

    def _button(self, label, action):
        button = pn.widgets.Button(label=label, color="primary")
        button.on_click(lambda _: self.run(action))
        return button

    def _preprocessing_page(self):
        self.normalization = self.field("normalization")
        self.imputation = self.field("imputation")
        self.history_layer = pn.widgets.Select(label="恢复历史层", options=[])
        self.min_total = pn.widgets.FloatInput(label="最小细胞总强度", value=0.0, start=0.0)
        self.min_detected = pn.widgets.IntInput(label="最小检出特征数", value=0, start=0)
        self.feature_fraction = pn.widgets.FloatInput(
            label="最小特征检出比例", value=0.0, start=0.0, end=1.0
        )
        self.contamination = pn.widgets.FloatInput(
            label="异常值比例", value=0.05, start=0.001, end=0.5
        )
        self.history_table = pn.pane.DataFrame(pd.DataFrame(), height=200)
        self.qc_plot = _plot("每细胞总强度与检出数")
        self.qc_table = pn.pane.DataFrame(pd.DataFrame(), height=220)
        self.preprocess_page = pn.Column(
            "## 预处理与 QC",
            self.summary,
            self.status,
            "X 为当前版本；每步成功后保存历史层。行/列筛选会同步裁剪历史层；完整恢复请使用重置。",
            self.normalization,
            self._button("归一化", lambda: self.state.normalize(self.normalization.value)),
            self.imputation,
            self._button("插补零值", lambda: self.state.impute(self.imputation.value)),
            self.help("normalization", "imputation"),
            pn.Row(self.min_total, self.min_detected, self.feature_fraction),
            self._button(
                "应用 QC 筛选",
                lambda: self.state.filter(
                    min_total=self.min_total.value,
                    min_detected=self.min_detected.value,
                    min_feature_fraction=self.feature_fraction.value,
                ),
            ),
            self.contamination,
            self._button(
                "移除异常值", lambda: self.state.remove_outliers(self.contamination.value)
            ),
            self.history_layer,
            self._button("恢复所选层", lambda: self.state.restore(self.history_layer.value)),
            self._button("重置为本次载入的数据", self.state.reset),
            self.history_table,
            self.qc_plot,
            self.qc_table,
        )

    def _embedding_page(self):
        self.reduction = self.field("reduction")
        self.representation = pn.widgets.Select(label="降维/聚类输入", options=["X"])
        self.dimensions = self.field("n_components")
        self.neighbors = self.field("n_neighbors")
        self.perplexity = self.field("perplexity")
        self.seed = self.field("random_state")
        self.pca_input = pn.widgets.Checkbox(label="PCA preprocessing", value=True)
        self.pca_dimensions = pn.widgets.IntInput(label="PCA input dimensions", value=20, start=1)
        self.whiten = pn.widgets.Checkbox(label="whiten", value=False)
        self.min_dist = pn.widgets.FloatInput(label="min_dist", value=0.3, start=0, end=1)
        self.metric = pn.widgets.Select(
            label="metric", options=["euclidean", "manhattan", "cosine"]
        )
        self.learning_rate = pn.widgets.TextInput(label="learning_rate", value="auto")
        self.max_iter = pn.widgets.IntInput(label="max_iter", value=1000, start=250)
        self.reduction_options = pn.Column(
            self.pca_input,
            self.pca_dimensions,
            self.whiten,
            self.min_dist,
            self.metric,
            self.learning_rate,
            self.max_iter,
        )

        def reduction_visibility(_=None):
            method = self.reduction.value
            self.pca_input.visible = method == "umap"
            self.pca_dimensions.visible = method == "umap" and self.pca_input.value
            self.whiten.visible = method == "pca" or (method == "umap" and self.pca_input.value)
            self.min_dist.visible = method == "umap"
            self.metric.visible = method in {"umap", "tsne", "isomap"}
            self.learning_rate.visible = self.max_iter.visible = method == "tsne"

        self.reduction.param.watch(reduction_visibility, "value")
        self.pca_input.param.watch(reduction_visibility, "value")
        reduction_visibility()
        self.scale = pn.widgets.Checkbox(label="降维前标准化", value=False)
        self.embedding_key = pn.widgets.TextInput(
            label="新嵌入键（不覆盖已有键）", value=f"X_{self.reduction.value}"
        )
        self.reduction.param.watch(
            lambda e: setattr(self.embedding_key, "value", f"X_{e.new}"), "value"
        )
        self.embedding_view = pn.widgets.Select(label="查看嵌入", options=[])
        self.color = pn.widgets.Select(label="Color", options={"无": ""})
        self.color_search = pn.widgets.TextInput(label="Search annotation / feature")
        self.color_sort = pn.widgets.Select(
            label="Feature order", options=["mean", "total", "median", "detection", "mz", "name"]
        )
        self.color_descending = pn.widgets.Checkbox(label="Descending", value=True)
        for widget in (self.color_search, self.color_sort, self.color_descending):
            widget.param.watch(lambda _: self.refresh(), "value")
        self.embedding_plot = _plot("嵌入")
        self.cluster_method = self.field("clustering")
        self.clusters = self.field("n_clusters")
        self.cluster_key = pn.widgets.TextInput(label="新簇标签列", value="clusters")
        self.discovery_page = pn.Column(
            "## 降维与聚类",
            self.summary,
            self.status,
            self.representation,
            pn.Row(self.reduction, self.dimensions, self.scale),
            pn.Row(self.neighbors, self.perplexity, self.seed),
            self.embedding_key,
            self._button("运行降维", self._reduce),
            self.help("reduction", "n_components", "n_neighbors", "perplexity", "random_state"),
            pn.Row(self.cluster_method, self.clusters, self.cluster_key),
            self._button(
                "运行聚类",
                lambda: self.state.cluster(
                    self.cluster_method.value,
                    use_rep=self.representation.value,
                    key=self.cluster_key.value,
                    n_clusters=self.clusters.value,
                    n_neighbors=self.neighbors.value,
                    random_state=self.seed.value,
                ),
            ),
            self.help("clustering", "n_clusters"),
            pn.Row(self.embedding_view, self.color),
            self.embedding_plot,
            "实验轨迹方法继续暂缓，现有 Python 轨迹接口不变。",
        )
        for widget in (self.embedding_view, self.color):
            widget.param.watch(lambda _: self._draw_embedding(), "value")

    def _reduce(self):
        self.state.reduce(
            self.reduction.value,
            store_key=self.embedding_key.value,
            use_rep=self.representation.value,
            n_components=self.dimensions.value,
            scale=self.scale.value,
            random_state=self.seed.value,
            n_neighbors=self.neighbors.value,
            perplexity=self.perplexity.value,
            pca_components=self.pca_dimensions.value
            if self.reduction.value == "umap" and self.pca_input.value
            else None,
            whiten=self.whiten.value,
            min_dist=self.min_dist.value,
            metric=self.metric.value,
            learning_rate="auto"
            if self.learning_rate.value.strip() == "auto"
            else float(self.learning_rate.value),
            max_iter=self.max_iter.value,
        )

    def _color_choices(self, data, observations):
        import numpy as np

        from scMM.application.workbench import dense

        from .presentation import feature_label

        columns = sorted(
            observations,
            key=lambda c: (
                (["group", "sample", "batch"].index(c) if c in ["group", "sample", "batch"] else 3),
                c,
            ),
        )
        choices = {"无": "", **{f"Annotation · {c}": f"obs:{c}" for c in columns}}
        if data is not None:
            values = dense(data.X)
            method = self.color_sort.value
            scores = {
                "mean": lambda: values.mean(axis=0),
                "total": lambda: values.sum(axis=0),
                "median": lambda: np.median(values, axis=0),
                "detection": lambda: (values != 0).mean(axis=0),
                "mz": lambda: pd.to_numeric(
                    data.var.get("mz", pd.Series(data.var_names)), errors="coerce"
                ).to_numpy(),
                "name": lambda: np.asarray(data.var_names),
            }[method]()
            order = np.argsort(scores, kind="stable")
            if self.color_descending.value:
                order = order[::-1]
            choices.update(
                {
                    f"Feature · {feature_label(data.var_names[j], data.var.iloc[j].get('mz'))} · #{j + 1}": f"feature:{data.var_names[j]}"
                    for j in order
                }
            )
        query = self.color_search.value.strip().lower()
        return {
            key: value
            for key, value in choices.items()
            if not value or not query or query in key.lower() or value == self.color.value
        }

    def _draw_embedding(self):
        if self._refreshing or self.state.data is None or not self.embedding_view.value:
            return
        try:
            self.embedding_plot.object = embedding_figure(
                self.state.data, self.embedding_view.value, self.color.value
            )
        except Exception as exc:
            self.status.object = f"绘图失败：{escape(str(exc))}"

    def _differential_page(self):
        self.group = pn.widgets.Select(label="分组列", options=[])
        self.group_a = pn.widgets.Select(label="A 组（fold change 分子）", options=[])
        self.group_b = pn.widgets.Select(label="B 组", options=[])
        self.diff_layer = pn.widgets.Select(label="差异检验数据层", options={"当前 X": None})
        self.diff_method = self.field("differential_method")
        self.features = pn.widgets.MultiChoice(label="小提琴特征（最多 12 个）", options=[])
        self.hide_zero = pn.widgets.Checkbox(label="仅在小提琴图隐藏零值", value=False)
        self.volcano_fdr = pn.widgets.FloatInput(label="FDR threshold", value=0.05, start=0, end=1)
        self.volcano_effect = pn.widgets.FloatInput(label="abs(log2FC)", value=1.0, start=0)
        self.volcano_labels = pn.widgets.IntInput(label="Label count", value=10, start=0, end=100)
        self.volcano_order = pn.widgets.Select(
            label="Label order", options=["fdr", "effect", "p_value", "intensity"]
        )
        self.volcano_controls = pn.Row(
            self.volcano_fdr, self.volcano_effect, self.volcano_labels, self.volcano_order
        )
        self.volcano = _plot("全局 FDR 火山图")
        self.volcano.param.watch(self._volcano_click, "click_data")
        for widget in (
            self.volcano_fdr,
            self.volcano_effect,
            self.volcano_labels,
            self.volcano_order,
        ):
            widget.param.watch(lambda _: self._draw_volcano(), "value")
        self.violin_width = PlotWidth(height=1, sizing_mode="stretch_width")
        self.violin_width.param.watch(lambda _: self._draw_violin(), "pixels")
        self.violin = _plot("特征小提琴图")
        self.violin.param.update(sizing_mode="stretch_width", aspect_ratio=None, min_height=340)
        self.diff_table = pn.pane.DataFrame(pd.DataFrame(), height=240, index=False)
        self.marker_table = pn.pane.DataFrame(pd.DataFrame(), height=240, index=False)
        self.network_method = self.field("network_method")
        self.network_threshold = self.field("network_threshold")
        self.network_top_features = self.field("network_top_features")
        self.network_plot = _plot("特征相关网络")
        self.network_table = pn.pane.DataFrame(pd.DataFrame(), height=200, index=False)
        self.differential_page = pn.Column(
            "## 差异分析",
            self.summary,
            self.status,
            pn.Row(self.group, self.group_a, self.group_b),
            pn.Row(self.diff_layer, self.diff_method),
            self._button("比较全部特征", self._differentiate),
            self.help("differential_method"),
            "选取特征和隐藏零值不会重新检验；两张图共享全特征 BH-FDR。",
            self.volcano,
            self.features,
            self.hide_zero,
            self.violin,
            self.diff_table,
            "### Marker：每簇对其余已标记细胞",
            "沿用上方分组列、数据层与检验方法；每个比较内对全部特征做 BH-FDR，并非跨簇联合校正。",
            self._button(
                "计算全部簇 Marker",
                lambda: self.state.markers(
                    self.group.value, method=self.diff_method.value, layer=self.diff_layer.value
                ),
            ),
            self.marker_table,
            "### 特征相关网络",
            "沿用上方数据层。仅按方差筛选特征；相关不代表因果，不是轨迹分析。",
            pn.Row(self.network_method, self.network_threshold, self.network_top_features),
            self.help("network_method", "network_threshold", "network_top_features"),
            self._button("计算相关网络", self._network),
            self.network_plot,
            self.network_table,
        )
        self.group.param.watch(self._groups, "value")
        for widget in (self.group, self.group_a, self.group_b, self.diff_layer, self.diff_method):
            widget.param.watch(lambda _: self._invalidate("differential"), "value")
        for widget in (self.features, self.hide_zero):
            widget.param.watch(lambda _: self._draw_violin(), "value")
        for widget in (self.group, self.diff_layer, self.diff_method):
            widget.param.watch(lambda _: self._invalidate("markers"), "value")
        for widget in (
            self.diff_layer,
            self.network_method,
            self.network_threshold,
            self.network_top_features,
        ):
            widget.param.watch(lambda _: self._invalidate("network"), "value")

    def _network(self):
        self.state.network(
            method=self.network_method.value,
            min_abs_correlation=self.network_threshold.value,
            top_features=self.network_top_features.value,
            layer=self.diff_layer.value,
        )

    def _groups(self, _event=None):
        if self.state.data is None or not self.group.value:
            values = []
        else:
            values = sorted(self.state.data.obs[self.group.value].dropna().astype(str).unique())
        self._options(self.group_a, values)
        self._options(self.group_b, values)
        if len(values) > 1 and self.group_a.value == self.group_b.value:
            self.group_b.value = next(value for value in values if value != self.group_a.value)

    def _differentiate(self):
        self.state.differential(
            self.group.value,
            self.group_a.value,
            self.group_b.value,
            method=self.diff_method.value,
            layer=self.diff_layer.value,
        )

    def _draw_volcano(self):
        if "differential" in self.state.results:
            self.volcano.object = volcano_figure(
                self.state.result("differential")["table"],
                fdr=self.volcano_fdr.value,
                fold_change=self.volcano_effect.value,
                labels=self.volcano_labels.value,
                order=self.volcano_order.value,
            )

    def _volcano_click(self, event):
        points = (event.new or {}).get("points", [])
        if not points or "differential" not in self.state.results:
            return
        feature = points[0].get("customdata", [None])[0]
        if feature not in self.state.result("differential")["table"].feature_id.tolist():
            return
        selected = list(self.features.value)
        if feature in selected:
            selected.remove(feature)
        elif len(selected) < 12:
            selected.append(feature)
        else:
            self.status.object = "最多选择 12 个特征，请先取消一个。"
        self.features.value = selected

    def _draw_violin(self):
        if self._refreshing or "differential" not in self.state.results:
            return
        try:
            self.violin.object = violin_figure(
                self.state.data,
                self.state.result("differential"),
                self.features.value,
                hide_zero=self.hide_zero.value,
                columns=max(1, min(3, self.violin_width.pixels // 300)),
            )
            self.violin.height = self.violin.object.layout.height or 340
        except Exception as exc:
            self.violin.object = go.Figure()
            self.status.object = f"绘图失败：{escape(str(exc))}"

    def _supervised_page(self):
        self.label = pn.widgets.Select(label="分类标签列", options=[])
        self.sample_group = pn.widgets.Select(
            label="独立样本/批次列", options={"不分组（可能泄漏）": None}
        )
        self.model_layer = pn.widgets.Select(label="模型输入层", options={"当前 X": None})
        self.model = self.field("model")
        self.cv = self.field("cv")
        self.test_size = self.field("test_size")
        self.calibration_bins = self.field("calibration_bins")
        self.smote = pn.widgets.Checkbox(label="训练折内 SMOTE", value=False)
        self.lda_solver = pn.widgets.Select(label="LDA solver", options=["svd", "lsqr", "eigen"])
        self.latent_key = pn.widgets.TextInput(label="潜变量存储键", value="X_latent")
        self.latent_button = self._button(
            "保存潜变量和 train/test 标识", lambda: self.state.save_latent(self.latent_key.value)
        )
        self.model_report = pn.pane.JSON({}, depth=3)
        self.roc, self.pr, self.calibration = (_plot(title) for title in ("ROC", "PR", "校准"))
        self.shap_background = self.field("shap_background")
        self.shap_samples = self.field("shap_samples")
        self.shap_table = pn.pane.DataFrame(pd.DataFrame(), height=240, index=False)
        self.shap_plot = _plot("SHAP 特征重要性")
        self.shap_button = self._button(
            "解释当前模型（SHAP）",
            lambda: self.state.explain_shap(
                max_background=self.shap_background.value,
                max_samples=self.shap_samples.value,
                seed=self.seed.value,
            ),
        )
        self.supervised_page = pn.Column(
            "## 监督分析",
            self.summary,
            self.status,
            "训练/测试和各 CV 折均须包含全部类别。分组划分不能补救提前在全数据上插补/选特征造成的泄漏。",
            pn.Row(self.label, self.sample_group, self.model_layer),
            pn.Row(self.model, self.lda_solver),
            pn.Row(self.cv, self.test_size, self.calibration_bins),
            self.smote,
            self._button("训练并验证", self._train),
            self.help("model", "cv", "test_size", "calibration_bins"),
            self.model_report,
            self.roc,
            self.pr,
            self.calibration,
            self.latent_key,
            self.latent_button,
            "lsqr 可做分类但不支持潜变量；R2/Q2 继续暂缓。",
            "### SHAP",
            "使用训练集背景解释测试集样本；绝对贡献跨样本/类别取平均，不表示效应方向或因果。图显示前 30 项，下载包含全部。",
            pn.Row(self.shap_background, self.shap_samples),
            self.help("shap_background", "shap_samples"),
            self.shap_button,
            self.shap_plot,
            self.shap_table,
        )
        for widget in (self.shap_background, self.shap_samples):
            widget.param.watch(lambda _: self._invalidate("shap"), "value")
        for widget in (
            self.label,
            self.sample_group,
            self.model_layer,
            self.model,
            self.cv,
            self.test_size,
            self.calibration_bins,
            self.smote,
            self.lda_solver,
            self.seed,
        ):
            widget.param.watch(lambda _: self._invalidate("supervised"), "value")

    def _train(self):
        params = {"solver": self.lda_solver.value} if self.model.value == "lda" else {}
        self.state.train(
            self.label.value,
            group_key=self.sample_group.value,
            layer=self.model_layer.value,
            model=self.model.value,
            cv=self.cv.value,
            test_size=self.test_size.value,
            calibration_bins=self.calibration_bins.value,
            smote=self.smote.value,
            model_params=params,
            random_state=self.seed.value,
        )

    def _results_page(self):
        self.export_root = pn.widgets.Select(
            label="保存存储（含云盘）", options=[r.label for r in self.catalog.roots]
        )
        self.export_directory = pn.widgets.TextInput(label="保存目录", value=".")
        self.export_name = pn.widgets.TextInput(label="H5AD 文件名", value="analysis.h5ad")
        self.confirm_save = pn.widgets.Checkbox(
            label="确认保存当前修订（不覆盖已有文件）", value=False
        )
        for widget in (self.export_root, self.export_directory, self.export_name):
            widget.param.watch(lambda _: setattr(self.confirm_save, "value", False), "value")
        self.save_button = self._button("保存 H5AD（含历史层与嵌入）", self._save)
        self.diff_download = pn.widgets.FileDownload(
            label="下载完整差异表 CSV",
            filename="differential.csv",
            callback=lambda: _csv(self.state.result("differential")["table"]),
        )
        self.model_download = pn.widgets.FileDownload(
            label="下载监督诊断 JSON",
            filename="supervised.json",
            callback=lambda: BytesIO(
                json.dumps(
                    self.state.result("supervised").result_,
                    default=lambda v: v.tolist(),
                    ensure_ascii=False,
                ).encode()
            ),
        )
        self.matrix_download = pn.widgets.FileDownload(
            label="下载当前矩阵 CSV",
            filename="matrix.csv",
            callback=lambda: _csv(self.state.require_data().to_df()),
        )
        self.embedding_download = pn.widgets.FileDownload(
            label="下载当前嵌入 CSV",
            filename="embedding.csv",
            callback=lambda: _csv(
                pd.DataFrame(
                    self.state.require_data().obsm[self.embedding_view.value],
                    index=self.state.data.obs_names,
                )
            ),
        )
        self.qc_download = pn.widgets.FileDownload(
            label="下载细胞 QC CSV",
            filename="cell_qc.csv",
            callback=lambda: _csv(self.state.qc()["cell"]),
        )
        self.history_download = pn.widgets.FileDownload(
            label="下载处理记录 CSV",
            filename="history.csv",
            callback=lambda: _csv(pd.DataFrame(self.state.history())),
        )
        self.extra_downloads = {
            name: pn.widgets.FileDownload(
                label=f"下载 {name} CSV",
                filename=f"{name}.csv",
                callback=lambda name=name: _csv(self.state.result(name)["table"]),
            )
            for name in ("markers", "network", "shap")
        }
        self.results_page = pn.Column(
            "## 结果",
            self.summary,
            self.status,
            self.notice,
            pn.Row(self.diff_download, self.model_download, self.matrix_download),
            pn.Row(*self.extra_downloads.values()),
            self.export_root,
            self.export_directory,
            self.export_name,
            self.confirm_save,
            self.save_button,
            "H5AD 保留当前轴上的历史层及来源记录；CSV 不包含层和嵌入。云盘需可写挂载才能保存。",
        )

    def _save(self):
        if not self.confirm_save.value:
            raise ValueError("请先确认保存当前修订")
        self.state.save_h5ad(
            self.catalog,
            self.export_root.value,
            self.export_directory.value,
            self.export_name.value,
        )
        self.confirm_save.value = False

    def _invalidate(self, name):
        if self._refreshing:
            return
        self.state.results.pop(name, None)
        if name == "supervised":
            self.state.results.pop("shap", None)
        self.refresh()

    @staticmethod
    def _options(widget, options):
        values = list(options.values()) if isinstance(options, dict) else list(options)
        old = widget.value
        widget.options = options
        widget.value = old if old in values else (values[0] if values else None)

    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            data = self.state.data
            if self._rendered_token != self.state.token:
                self.confirm_save.value = False
                for download in (self.matrix_download, self.diff_download, self.model_download):
                    download.data = None
                for download in self.extra_downloads.values():
                    download.data = None
                self._rendered_token = self.state.token
            self.summary.object = (
                "尚未读取处理结果。"
                if data is None
                else f"**{data.n_obs} 细胞 × {data.n_vars} 特征** · 修订 {self.state.revision} · 来源 `{escape(self.state.source)}`"
            )
            layers = {} if data is None else {key: key for key in data.layers}
            observations = (
                []
                if data is None
                else sorted(
                    data.obs.columns,
                    key=lambda key: (
                        ["group", "sample", "batch"].index(key)
                        if key in ["group", "sample", "batch"]
                        else 3
                    ),
                )
            )
            embeddings = [] if data is None else list(data.obsm)
            self._options(self.history_layer, list(layers))
            self._options(self.diff_layer, {"当前 X": None, **layers})
            self._options(self.model_layer, {"当前 X": None, **layers})
            self._options(self.group, observations)
            self._groups()
            self._options(self.label, observations)
            self._options(
                self.sample_group, {"不分组（可能泄漏）": None, **{c: c for c in observations}}
            )
            self._options(self.representation, ["X", *embeddings])
            self._options(self.embedding_view, embeddings)
            colors = self._color_choices(data, observations)
            previous_color = self.color.value
            self._options(self.color, colors)
            if not previous_color:
                self.color.value = next(
                    (
                        f"obs:{key}"
                        for key in ("group", "sample")
                        if data is not None
                        and key in data.obs
                        and data.obs[key]
                        .astype(object)
                        .fillna("")
                        .astype(str)
                        .str.strip()
                        .ne("")
                        .any()
                        and f"obs:{key}" in colors.values()
                    ),
                    "",
                )
            self.embedding_download.disabled = data is None or not self.embedding_view.value
            self.qc_download.disabled = self.history_download.disabled = data is None
            for download in (self.embedding_download, self.qc_download, self.history_download):
                download.data = None
            self.matrix_download.disabled = data is None
            self.save_button.disabled = data is None
            if data is not None:
                self.history_table.object = pd.DataFrame(self.state.history())
                qc = self.state.qc()
                self.qc_table.object = qc["file"]
                self.qc_plot.object = px.scatter(
                    qc["cell"],
                    x="total_intensity",
                    y="detected_features",
                    color="source_file",
                    title="每细胞 QC",
                )
            if "differential" in self.state.results:
                result = self.state.result("differential")
                self.diff_table.object = result["table"]
                self._draw_volcano()
                choices = result["table"].feature_id.tolist()
                selected = [f for f in self.features.value if f in choices]
                from .presentation import mass_label

                self.features.options = {
                    f"{mass_label(feature)} · #{i + 1}": feature
                    for i, feature in enumerate(choices)
                }
                self.features.value = selected
                self._refreshing = False
                self._draw_violin()
                self._refreshing = True
            else:
                self.diff_table.object = pd.DataFrame()
                self.features.value = []
                self.features.options = []
                self.volcano.object = go.Figure(layout={"title": "请运行差异分析"})
                self.violin.object = go.Figure()
            self.diff_download.disabled = "differential" not in self.state.results
            self.model_download.disabled = "supervised" not in self.state.results
            if self.diff_download.disabled:
                self.diff_download.data = None
            if self.model_download.disabled:
                self.model_download.data = None
            self.latent_button.disabled = True
            self.shap_button.disabled = "supervised" not in self.state.results
            for name, pane in (
                ("markers", self.marker_table),
                ("network", self.network_table),
                ("shap", self.shap_table),
            ):
                present = name in self.state.results
                pane.object = self.state.result(name)["table"] if present else pd.DataFrame()
                self.extra_downloads[name].disabled = not present
                # Also clear cached downloads after recomputing at the same revision.
                self.extra_downloads[name].data = None
            self.network_plot.object = (
                network_figure(self.state.result("network")["graph"])
                if "network" in self.state.results
                else go.Figure()
            )
            self.shap_plot.object = (
                px.bar(
                    self.state.result("shap")["table"].head(30).iloc[::-1],
                    x="mean_abs_shap",
                    y="feature_id",
                    orientation="h",
                    title="平均绝对 SHAP（前 30 项）",
                )
                if "shap" in self.state.results
                else go.Figure()
            )
            if "supervised" in self.state.results:
                analyzer = self.state.result("supervised")
                self.model_report.object = json.loads(
                    json.dumps(analyzer.result_, default=lambda v: v.tolist())
                )
                for pane, figure in zip(
                    (self.roc, self.pr, self.calibration), supervised_figures(analyzer), strict=True
                ):
                    pane.object = figure
                self.latent_button.disabled = not analyzer.supports_latent_scores
            else:
                self.model_report.object = {}
                for pane in (self.roc, self.pr, self.calibration):
                    pane.object = go.Figure()
            if not embeddings:
                self.embedding_plot.object = go.Figure()
        finally:
            self._refreshing = False
        self._draw_embedding()
