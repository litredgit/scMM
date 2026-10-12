"""Project-first six-step workbench; no legacy eight-tab application entry."""

from __future__ import annotations

import json
import math
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from html import escape
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from weakref import WeakSet

import pandas as pd
import panel as pn
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from anndata import read_h5ad

from scMM.analysis.quality import quality_metrics
from scMM.application import OutputRoot, StorageCatalog, StorageRoot
from scMM.application.cell_preview import initialize_ranges, submit_preview
from scMM.application.naming import beijing_time, project_dataset_filename
from scMM.application.parameters import load_defaults
from scMM.application.preferences import BUILTIN_PRESETS, load_preferences, save_preferences
from scMM.application.preview_cache import file_identity
from scMM.application.project_batch import (
    batches,
    preflight,
    read_batch,
    reviewed_dataset,
    stop_after_current,
    submit,
)
from scMM.application.projects import PROJECT_ROOT, ProjectStore, child_path, sample_parameters
from scMM.application.workbench import read_dataset

from .downloads import FileDownload
from .file_browser import FileBrowser
from .layout import CONTENT_STYLE, TaskDock, UnsavedGuard, fit_plot, flow, form, style_button
from .preflight import request_view
from .presentation import QCDataFrame, apply_presentation, english_parameters, qc_file_table
from .project_views import ProjectRawViews
from .raw_components import PreviewWorkspace as PreviewWorkspace
from .raw_components import cell_detection_figure
from .saved_items import SavedItemsPanel

STEPS = [
    "项目首页",
    "① 项目与样本",
    "② 原始谱检查",
    "③ 提取与审核",
    "④ 预处理",
    "⑤ 分析",
    "⑥ 结果与保存",
]

ANALYSIS_FIELDS = (
    "pca_input",
    "pca_dimensions",
    "whiten",
    "min_dist",
    "metric",
    "learning_rate",
    "max_iter",
    "color_sort",
    "color_descending",
    "color_source",
    "volcano_fdr",
    "volcano_effect",
    "volcano_labels",
    "volcano_order",
    "group",
    "group_a",
    "group_b",
    "diff_layer",
    "diff_method",
    "features",
    "hide_zero",
    "reduction",
    "representation",
    "dimensions",
    "neighbors",
    "perplexity",
    "seed",
    "scale",
    "embedding_key",
    "embedding_view",
    "color",
    "cluster_method",
    "clusters",
    "cluster_key",
    "label",
    "sample_group",
    "model_layer",
    "model",
    "cv",
    "test_size",
    "calibration_bins",
    "smote",
    "lda_solver",
    "latent_key",
    "network_method",
    "network_threshold",
    "network_top_features",
    "shap_background",
    "shap_samples",
)
RESULT_PLOTS = {
    "differential": ("volcano", "violin"),
    "network": ("network_plot",),
    "supervised": ("roc", "pr", "calibration"),
    "shap": ("shap_plot",),
}
LIVE_WORKSPACES = WeakSet()


TASK_LABELS = {
    "queued": "等待启动",
    "running": "运行中",
    "waiting": "等待中",
    "succeeded": "成功",
    "completed": "处理结束，请审核",
    "failed": "失败",
    "stopped": "已停止后续样本",
    "interrupted": "已中断",
}


class ProjectWorkspace:
    def __init__(self, roots, *, project_root=PROJECT_ROOT, defaults=None):
        LIVE_WORKSPACES.add(self)
        self.store = ProjectStore(project_root)
        self.roots = tuple(roots)
        self.catalog = StorageCatalog(self.roots)
        self.defaults = defaults or load_defaults()
        self.project = None
        self.analysis_navigation = pn.Column(visible=False)
        self.image_format = pn.widgets.Select(
            label="Figure download format", options=["svg", "png"], value="svg", width=160
        )
        self.image_format.param.watch(lambda _: self._format_images(), "value")
        self.step = 0
        self._updating = False
        self._periodic = None
        self._cell_preview_job = None
        self.preview_status = pn.pane.Markdown("")
        self._checked = self._candidate = None
        self.header = pn.pane.Markdown("选择或新建一个实验项目。", styles={"flex": "1 1 280px"})
        self.unsaved_guard = UnsavedGuard(height=0, margin=0)
        self.message = pn.pane.Markdown("")
        self.task_status = pn.pane.Markdown("任务：尚未打开项目")
        self.events = []
        self.event_log = pn.widgets.TextAreaInput(
            label="操作记录（可选择复制）", disabled=True, height=180
        )
        self.log = pn.widgets.TextAreaInput(
            label="处理日志尾部（最近 30 KB，可选择复制）", disabled=True, height=260
        )
        self.follow_log = pn.widgets.Checkbox(
            label="实时更新日志（阅读旧内容时可暂停）", value=True
        )
        self.error_notice = pn.pane.Alert("", alert_type="danger", visible=False)
        self.task_dock = TaskDock(
            content=pn.Column(
                "### 任务与日志",
                self.task_status,
                self.message,
                self.error_notice,
                self.button("清除错误提示", self._clear_error, role="auxiliary"),
                self.event_log,
                self.follow_log,
                self.log,
                FileDownload(
                    label="下载完整任务日志", filename="worker.log", callback=self._download_log
                ),
                sizing_mode="stretch_width",
            )
        )
        self.body = pn.Column(sizing_mode="stretch_width")
        self.navigation = pn.widgets.RadioButtonGroup(
            options=STEPS, value=STEPS[0], orientation="vertical"
        )
        self.navigation.param.watch(self._navigate, "value")
        self.save_button = self.button("保存项目", self._save)
        self.previous = self.button("上一步", lambda: self.go(self.step - 1), role="auxiliary")
        self.next = self.button("下一步", self._next_step)
        self.next_note = pn.pane.Markdown("")
        self.leave = pn.widgets.Checkbox(label="确认放弃未保存修改，再新建或打开其他项目")
        self.name = pn.widgets.TextInput(label="新项目名称")
        self.project_select = pn.widgets.Select(label="已保存项目", options={})
        self.saved_items = SavedItemsPanel(
            self.store,
            self.roots,
            active_paths=self._active_saved_paths,
            changed=self._refresh_home,
        )
        self.close_button = self.button("关闭当前项目", self._close_project, role="auxiliary")
        self.home = pn.Column(
            "## 实验项目",
            f"项目位置：`{escape(str(self.store.root))}`",
            self.name,
            self.button("新建项目", self._create),
            self.project_select,
            self.button("打开所选项目", self._open),
            self.leave,
            self.close_button,
            pn.Accordion(("管理已保存项目、结果与回收区", self.saved_items)),
            "从已有结果开始：先新建项目，再导入结果目录或 H5AD。",
        )
        self.footer = flow(self.previous, self.next, self.next_note)
        self.panel = pn.Column(
            self.unsaved_guard,
            pn.FlexBox(
                self.header,
                self.image_format,
                self.save_button,
                flex_wrap="wrap",
                align_items="center",
            ),
            self.body,
            self.footer,
            self.task_dock,
            stylesheets=[CONTENT_STYLE],
        )
        apply_presentation(self.task_dock.content)
        self._refresh_home()
        self.render()
        if pn.state.curdoc is not None and pn.state.curdoc.session_context is not None:
            pn.state.on_session_destroyed(self._close_session)

    def button(self, label, action, *, role="action"):
        button = style_button(pn.widgets.Button(label=label), role)
        button.on_click(lambda _: self.run(action))
        return button

    def run(self, action):
        try:
            result = action()
            self.message.object = result if isinstance(result, str) else "操作完成。"
        except Exception as exc:
            self.message.object = f"❌ {escape(str(exc))}"
        self._record(self.message.object)
        if self.project is not None:
            self._refresh_reports()
        self.refresh_header()

    def _clear_error(self):
        self.error_notice.visible = False
        self.task_dock.label = "任务与日志（点击展开 / 收起）"

    def _download_log(self):
        if not self.project or not hasattr(self, "batch_select") or not self.batch_select.value:
            return BytesIO(b"")
        path = Path(self.batch_select.value).with_name("worker.log")
        return BytesIO(path.read_bytes() if path.exists() else b"")

    def _record(self, message):
        if not message:
            return
        self.events.append(f"{beijing_time().split()[1]} {message}")
        self.events = self.events[-100:]
        self.event_log.value = "\n".join(self.events)
        if "❌" in message or "失败" in message:
            self.error_notice.object = message
            self.error_notice.visible = True
            self.task_dock.label = "❌ 有错误待查看 — 点击展开任务日志"

    def _refresh_home(self):
        previous = self.project_select.value
        self.project_select.options = {
            f"{p['name']} · {p['samples']} 文件 · {beijing_time(p['saved_at'])}": p["path"]
            for p in self.store.list()
        }
        values = list(self.project_select.options.values())
        self.project_select.value = (
            previous if previous in values else (values[0] if values else None)
        )

    def _active_saved_paths(self):
        for ui in LIVE_WORKSPACES:
            if ui.project is not None:
                yield ui.project.folder
                if ui.project.workspace.source:
                    yield ui.project.workspace.source

    def _close_project(self):
        self._allow_leave()
        if self._cell_preview_job is not None:
            raise ValueError("细胞预览仍在运行，请等待完成后关闭项目")
        if self.project is not None:
            self.components.close()
        self.project = None
        self.leave.value = False
        self.step = 0
        self.saved_items.refresh()
        self.render()
        return "当前项目已关闭。"

    def _allow_leave(self):
        if self.project and self.project.unsaved and not self.leave.value:
            raise ValueError("请先保存项目，或明确勾选放弃未保存修改")

    def _create(self):
        self._allow_leave()
        preferences = load_preferences()
        defaults = self.defaults.to_dict()
        if "ref_mz" not in self.defaults.processing_overrides:
            defaults["processing"]["ref_mz"] = preferences["presets"][preferences["selected"]]
        from scMM.application.parameters import WorkbenchDefaults
        from scMM.application.processing import ProcessingParameters

        project = self.store.create(
            self.name.value,
            WorkbenchDefaults(ProcessingParameters(**defaults["processing"]), defaults["analysis"]),
        )
        project.manifest["cell_type"] = preferences["selected"]
        project.manifest["auto_ranges"] = not bool(
            {"mz_min", "mz_max"} & self.defaults.processing_overrides
        )
        project.manifest["manual_parameters"] = not project.manifest["auto_ranges"]
        self.activate(project)

    def _open(self):
        self._allow_leave()
        if not self.project_select.value:
            raise ValueError("请选择项目")
        self.activate(self.store.open(self.project_select.value))

    def activate(self, project):
        if hasattr(self, "components"):
            self.components.close()
        self.project = project
        self.leave.value = False
        self._checked = self._candidate = None
        roots = list(self.roots)
        if project.folder not in {r.path for r in roots}:
            roots.append(StorageRoot("当前项目", project.folder))
        self.components = ProjectRawViews(
            tuple(roots),
            (OutputRoot("项目任务", project.folder / "processing"),),
            defaults=self.defaults,
        )
        self.analysis = self.components.analysis
        for name in ("tic_pane", "eic_pane", "spectrum_pane", "scan_pane", "cell_pane"):
            fit_plot(getattr(self.components, name), "spectrum")
        self.analysis.status.param.watch(lambda e: self._record(e.new), "object")
        self.analysis.status.visible = False
        self.log.value = ""
        self.analysis.state = project.workspace
        self.analysis.refresh()
        settings = project.views.get("settings", {})
        if "color_source" not in settings and str(settings.get("color", "")).startswith("feature:"):
            self.analysis.color_source.value = "feature"
        for name, value in project.views.get("settings", {}).items():
            if name in ANALYSIS_FIELDS:
                with suppress(ValueError, TypeError):
                    getattr(self.analysis, name).value = value
        if (
            project.workspace.data is not None
            and "subject" in project.workspace.data.obs
            and "sample_group" not in project.views.get("settings", {})
            and project.workspace.data.obs["subject"].astype(str).str.strip().ne("").all()
        ):
            self.analysis.sample_group.value = "subject"
        original_run = self.analysis.run
        original_invalidate = self.analysis._invalidate

        def invalidate(name):
            if self.analysis._refreshing:
                return
            names = (name, "shap") if name == "supervised" else (name,)
            old_figures = {
                figure: deepcopy(getattr(self.analysis, figure).object)
                for result in names
                for figure in RESULT_PLOTS.get(result, ())
                if getattr(self.analysis, figure).object.data
            }
            for result in names:
                project.saved_reports.pop(result, None)
                for figure in RESULT_PLOTS.get(result, ()):
                    project.views.get("figures", {}).pop(figure, None)
            original_invalidate(name)
            for figure, value in old_figures.items():
                value.update_layout(title="旧参数结果（不可导出）— 请重新运行")
                getattr(self.analysis, figure).object = value
            self.analysis.status.object = (
                "参数已修改，旧图仅供参考；重新运行后替换，旧结果不可下载。"
            )
            project.dirty = True
            self._refresh_reports()
            self.refresh_header()

        self.analysis._invalidate = invalidate

        def analysis_run(action):
            original_run(action)
            project.dirty = True
            self._refresh_reports()
            self.refresh_header()

        self.analysis.run = analysis_run
        for name in ANALYSIS_FIELDS:
            getattr(self.analysis, name).param.watch(self._analysis_setting_changed, "value")
        original_train = self.analysis._train
        self.exploratory_split = pn.widgets.Checkbox(
            label="明确使用细胞级探索性划分：不将结果视为独立来源的泛化验证"
        )

        def train():
            if self.analysis.sample_group.value is None and not self.exploratory_split.value:
                raise ValueError("请选择独立样本字段，或明确确认细胞级探索性划分")
            original_train()

        self.analysis._train = train
        # The original training button captured a bound method at construction.
        for button in self.analysis.supervised_page.select(pn.widgets.Button):
            if button.label == "训练并验证":
                button.disabled = True
                button.visible = False
        self.replace_confirm = pn.widgets.Checkbox(
            label="确认替换当前数据并清除预处理和分析结果（不删除文件）"
        )
        self._project_page()
        self._raw_page()
        self._batch_page()
        self._preprocess_page()
        self.preprocess_page.extend(
            [
                self.analysis.matrix_download,
                self.analysis.qc_download,
                self.analysis.history_download,
            ]
        )
        self._analysis_page()
        self._results_page()
        for owner in (self, self.components, self.analysis):
            english_parameters(owner)
        apply_presentation(self.panel)
        self._prepare_sample_mapping()
        self._sample_summary()
        self.go(1)

    def _analysis_setting_changed(self, _event=None):
        if not self.analysis._refreshing:
            self.project.dirty = True
            self.refresh_header()

    def _sample_frame(self):
        frame = pd.DataFrame(
            self.project.samples,
            columns=["id", "name", "path", "storage", "group", "subject", "batch", "parameters"],
        )
        frame["参数来源"] = [
            "样本例外" if s["parameters"] else "项目默认" for s in self.project.samples
        ]
        frame["预览检查"] = [self._preview_status(s) for s in self.project.samples]
        return frame

    def _preview_status(self, sample):
        preview = sample.get("preview")
        current = sample_parameters(self.project, sample)
        if preview is None:
            return "尚未预览"
        if json.dumps(preview["parameters"], sort_keys=True) != json.dumps(current, sort_keys=True):
            return "参数已修改"
        return "已人工确认" if preview.get("confirmed") else "已预览，待确认"

    def _project_page(self):
        self.project_name = pn.widgets.TextInput(
            label="项目名称", value=self.project.manifest["name"], width=300
        )
        self.project_name.param.watch(lambda e: self._metadata("name", e.new), "value")
        self.description = pn.widgets.TextAreaInput(
            label="说明",
            value=self.project.manifest["description"],
            width=480,
            height=85,
            styles={"max-width": "100%"},
        )
        self.description.param.watch(lambda e: self._metadata("description", e.new), "value")
        self.sample_table = pn.widgets.Tabulator(
            self._sample_frame(),
            show_index=False,
            hidden_columns=["id", "storage", "parameters"],
            selectable="checkbox",
            height=min(360, max(130, 45 + 32 * len(self.project.samples))),
            editors={
                "path": None,
                "name": "input",
                "group": "input",
                "subject": "input",
                "batch": "input",
                "参数来源": None,
                "预览检查": None,
            },
        )
        self.sample_table.on_edit(self._edit_sample)
        self.sample_mapping = pn.widgets.Tabulator(
            pd.DataFrame(columns=["Result sample", "Project sample"]), show_index=False, height=180
        )
        self.mapping_source = pn.widgets.Select(label="Result sample field", options=[])
        self.mapping_source.param.watch(lambda e: self._change_mapping_source(e.new), "value")
        self.mapping_panel = pn.Column(
            self.mapping_source,
            "匹配已有结果中的样本；空白项保持未关联。",
            self.sample_mapping,
            self.button("应用样本映射", self._apply_sample_mapping),
            visible=False,
        )

        self.file_root = pn.widgets.Select(
            label="原始文件存储", options=[r.label for r in self.roots]
        )
        self.file_browser = pn.Column()
        self.file_root.param.watch(lambda _: self._file_browser(), "value")
        self._file_browser()
        self.sample_csv = pn.widgets.FileInput(label="导入样本信息 CSV", accept=".csv")
        self.sample_csv.param.watch(lambda _: self.run(self._import_sample_csv), "value")
        a = self.analysis
        self.file_picker = pn.Column(
            "支持 Thermo RAW（profile）、mzML 和 mzXML；其他文件不会被加入项目。",
            self.file_root,
            self.file_browser,
            self.button("添加所选文件", self._add_files),
            self.button("用所选文件重新定位一个选中样本", self._relocate_sample, role="auxiliary"),
            visible=False,
        )
        self.result_picker = pn.Column(
            a.root,
            a.path,
            a.browser,
            a.trust,
            self.replace_confirm,
            self.button("读取结果并建立当前数据", self._import_result),
            visible=False,
        )

        def toggle_picker(panel):
            show = not panel.visible
            self.file_picker.visible = self.result_picker.visible = False
            panel.visible = show

        self.remove_samples = self.button("移出选中样本（0）", self._remove_samples, role="danger")
        self.remove_samples.disabled = True

        def selected_samples(event):
            self.remove_samples.label = f"移出选中样本（{len(event.new)}）"
            self.remove_samples.disabled = not event.new
            style_button(self.remove_samples)

        self.sample_table.param.watch(selected_samples, "selection")
        self.project_actions = flow(
            self.button("添加原始文件", lambda: toggle_picker(self.file_picker), role="auxiliary"),
            self.button(
                "选择已有结果", lambda: toggle_picker(self.result_picker), role="auxiliary"
            ),
            self.remove_samples,
        )
        self.project_page = pn.Column(
            "## ① 项目与样本",
            self.project_actions,
            self.file_picker,
            self.result_picker,
            form(self.project_name, self.description),
            "group：实验分组；subject：独立生物来源，同一来源的多个文件填写相同 ID；batch：采集批次。",
            self.sample_table,
            self.sample_csv,
            self.mapping_panel,
            "移出样本只改变项目清单，不删除原始文件。",
            "修改样本信息即时更新下游分组；依赖分组的分析需重算，提取结果保留。离开前请保存项目。",
        )

    def _import_sample_csv(self):
        if not self.sample_csv.value:
            return
        frame = pd.read_csv(BytesIO(self.sample_csv.value), dtype=str, keep_default_na=False)
        allowed = {"name", "group", "subject", "batch"}
        if "name" not in frame or set(frame.columns) - allowed or frame.name.duplicated().any():
            raise ValueError(
                "CSV 必须含唯一 name 列，仅支持 name/group/subject/batch；name 对应当前样本名称"
            )
        samples = {s["name"]: s for s in self.project.samples}
        if set(frame.name) - samples.keys():
            raise ValueError("CSV 中存在项目未添加的样本名称")
        for _, row in frame.iterrows():
            samples[row["name"]].update(row.to_dict())
            samples[row["name"]]["metadata_unresolved"] = [
                key
                for key in samples[row["name"]].get("metadata_unresolved", [])
                if key not in frame.columns
            ]
        self.project.dirty = True
        self._update_samples()

    def _relocate_sample(self):
        if len(self.sample_table.selection) != 1 or len(self.files.value) != 1:
            raise ValueError("请选择一个样本和一个替代原始文件")
        path = self.catalog.resolve_raw_file(self.file_root.value, self.files.value[0])
        sample = self.project.samples[self.sample_table.selection[0]]
        if any(s["id"] != sample["id"] and s["path"] == str(path) for s in self.project.samples):
            raise ValueError("该文件已关联其他样本")
        sample.update(path=str(path), storage=self.file_root.value, result_only=False)
        sample.pop("preview", None)
        self.project.dirty = True
        self._update_samples()

    def _metadata(self, key, value):
        self.project.manifest[key] = value
        self.project.dirty = True
        self._invalidate_preflight()
        self.refresh_header()

    def _edit_sample(self, event):
        if event.column in {"name", "group", "subject", "batch"}:
            sample = self.project.samples[event.row]
            value = str(event.value or "").strip()
            if event.column == "name" and (
                not value
                or any(s["id"] != sample["id"] and s["name"] == value for s in self.project.samples)
            ):
                self.message.object = "样本名称必须非空且唯一。"
                self.sample_table.value = self._sample_frame()
                return
            sample[event.column] = value
            sample["metadata_unresolved"] = [
                key for key in sample.get("metadata_unresolved", []) if key != event.column
            ]
            self.project.dirty = True
            self._invalidate_preflight()
            self._update_samples()
            self.refresh_header()

    def _sync_metadata(self):
        before = set(self.project.workspace.results)
        changed = self.project.workspace.sync_sample_metadata(
            self.project.samples,
            self.project.manifest.get("sample_mapping"),
            self.project.manifest.get("sample_column", "sample"),
        )
        if changed:
            stale = before - set(self.project.workspace.results)
            for name, report in list(self.project.saved_reports.items()):
                dependencies = {report.get("group_key"), report.get("label_key")}
                if dependencies & changed or (
                    name in {"supervised", "shap"} and not dependencies - {None}
                ):
                    stale.add(name)
                    self.project.saved_reports.pop(name, None)
            if "supervised" in stale:
                stale.add("shap")
                self.project.saved_reports.pop("shap", None)
            for name in stale:
                for figure in RESULT_PLOTS.get(name, ()):
                    self.project.views.get("figures", {}).pop(figure, None)
            self.project.report_token = self.project.workspace.token
            self.analysis.refresh()
            self._sample_summary()
            self.analysis.status.object = "样本信息已更新；受影响分析已失效，请重新计算。"

    def _change_mapping_source(self, value):
        if not value or getattr(self, "_mapping_refreshing", False):
            return
        self.project.manifest["sample_column"] = value
        self.project.dirty = True
        self._prepare_sample_mapping()

    def _prepare_sample_mapping(self):
        data = self.project.workspace.data
        if data is None:
            self.mapping_panel.visible = False
            return
        source = self.project.manifest.get("sample_column")
        if source not in data.obs:
            source = next(
                (key for key in ("sample", "sample_id", "source_file") if key in data.obs), None
            )
        self._mapping_refreshing = True
        try:
            self.mapping_source.options = ["", *list(data.obs.columns)]
            self.mapping_source.value = source or ""
        finally:
            self._mapping_refreshing = False
        self.mapping_panel.visible = True
        if source is None:
            return
        self.project.manifest["sample_column"] = source
        names = data.obs[source].dropna().astype(str).unique().tolist()
        if not self.project.samples:
            for name in names:
                rows = data.obs.loc[data.obs[source].astype(str).eq(name)]
                values = {
                    key: str(rows[key].iloc[0])
                    if key in rows
                    and rows[key].nunique(dropna=False) == 1
                    and pd.notna(rows[key].iloc[0])
                    else ""
                    for key in ("group", "subject", "batch")
                }
                self.project.samples.append(
                    {
                        "id": uuid4().hex,
                        "name": name,
                        "path": "",
                        "storage": self.roots[0].label,
                        "parameters": None,
                        "result_only": True,
                        "metadata_unresolved": [
                            key
                            for key in ("group", "subject", "batch")
                            if key in rows and rows[key].nunique(dropna=False) > 1
                        ],
                        **values,
                    }
                )
        matches = {s["name"]: s["id"] for s in self.project.samples}
        mapping = self.project.manifest.setdefault("sample_mapping", {})
        mapping.update(
            {name: matches[name] for name in names if name in matches and name not in mapping}
        )
        labels = {s["id"]: s["name"] for s in self.project.samples}
        self.sample_mapping.value = pd.DataFrame(
            [
                {"Result sample": name, "Project sample": labels.get(mapping.get(name), "")}
                for name in names
            ]
        )
        self.sample_mapping.editors = {
            "Result sample": None,
            "Project sample": {"type": "list", "values": ["", *matches]},
        }
        self.mapping_panel.visible = True
        self._update_samples()

    def _apply_sample_mapping(self):
        by_name = {s["name"]: s["id"] for s in self.project.samples}
        mapping = {}
        for _, row in self.sample_mapping.value.iterrows():
            target = row["Project sample"]
            if target:
                if target not in by_name:
                    raise ValueError("请选择项目中现有样本")
                mapping[row["Result sample"]] = by_name[target]
        self.project.manifest["sample_mapping"] = mapping
        self.project.dirty = True
        self._sync_metadata()

    def _file_browser(self):
        self.files = FileBrowser(self.catalog, self.file_root.value)
        self.file_browser[:] = [self.files]

    def _update_samples(self):
        self._sync_metadata()
        self.sample_table.value = self._sample_frame()
        self.sample_table.height = min(360, max(130, 45 + 32 * len(self.project.samples)))
        previous = self.raw_sample.value
        self.raw_sample.options = {s["name"]: s["id"] for s in self.project.samples}
        values = list(self.raw_sample.options.values())
        self.raw_sample.value = previous if previous in values else (values[0] if values else None)
        self._invalidate_preflight()
        self.refresh_header()

    def _add_files(self):
        if not self.files.value:
            raise ValueError("请选择文件")
        self.project.add_files(self.catalog, self.file_root.value, self.files.value)
        self.files.value = []
        self.file_picker.visible = False
        self._update_samples()

    def _remove_samples(self):
        selected = set(self.sample_table.selection)
        self.project.manifest["samples"] = [
            s for i, s in enumerate(self.project.samples) if i not in selected
        ]
        self.sample_table.selection = []
        self.project.dirty = True
        self._update_samples()

    def _check_replacement(self):
        if self.project.workspace.data is not None and not self.replace_confirm.value:
            raise ValueError("请先明确确认替换当前数据的影响")

    def _import_result(self):
        self._check_replacement()
        a = self.analysis
        data = read_dataset(a.catalog, a.root.value, a.path.value, trust_pickle=a.trust.value)
        self.project.workspace.replace(data, source=a.path.value)
        self._prepare_sample_mapping()
        self._sync_metadata()
        self.project.saved_reports = {}
        self.project.dirty = True
        self.replace_confirm.value = False
        a.refresh()
        self.result_picker.visible = False
        self._sample_summary()

    def _raw_page(self):
        r = self.components
        self.preview_button = self.button("运行当前样本细胞检测预览", self._preview_cells)
        self.preview_button.disabled = self._cell_preview_job is not None
        self.preview_button.loading = self._cell_preview_job is not None
        self.raw_sample = pn.widgets.Select(
            label="当前样本", options={s["name"]: s["id"] for s in self.project.samples}
        )
        self.raw_sample.param.watch(lambda _: self._select_raw(), "value")
        self.parameter_note = pn.pane.Markdown("")
        r.setup_navigation()
        widgets = r.processing.parameter_widgets
        for widget in widgets.values():
            if isinstance(widget, (pn.widgets.FloatInput, pn.widgets.IntInput)):
                widget.width = 140
                widget.margin = (5, 3)
        basic = [
            "extraction_method",
            "ref_mz",
            "mz_min",
            "mz_max",
            "cell_snr",
            "peak_snr",
            "feature_snr_threshold",
        ]

        def algorithm_controls(_=None):
            snr = widgets["extraction_method"].value == "snr_v1"
            widgets["peak_snr"].visible = not snr
            for key in (
                "feature_snr_threshold",
                "reference_mz",
                "reference_mode",
                "reference_ppm_tol",
                "noise_window",
                "feature_block_size",
            ):
                widgets[key].visible = snr

        widgets["extraction_method"].param.watch(algorithm_controls, "value")
        algorithm_controls()
        prefs = load_preferences()
        self.cell_type = pn.widgets.Select(
            label="Cell type",
            options=list(prefs["presets"]),
            value=self.project.manifest.get("cell_type", prefs["selected"])
            if self.project.manifest.get("cell_type", prefs["selected"]) in prefs["presets"]
            else prefs["selected"],
        )
        self.preset_table = pn.widgets.Tabulator(
            pd.DataFrame(list(prefs["presets"].items()), columns=["Cell type", "Reference m/z"]),
            show_index=False,
            height=180,
        )
        self.preset_name = pn.widgets.TextInput(label="New cell type")

        def choose_preset(event):
            frame = self.preset_table.value
            match = frame.loc[frame["Cell type"] == event.new, "Reference m/z"]
            if len(match):
                widgets["ref_mz"].value = float(match.iloc[0])

        self.cell_type.param.watch(choose_preset, "value")

        def save_presets():
            frame = self.preset_table.value
            if frame["Cell type"].duplicated().any():
                raise ValueError("细胞类型名称不能重复")
            presets = dict(zip(frame["Cell type"], frame["Reference m/z"], strict=True))
            if not presets:
                raise ValueError("至少保留一个细胞类型预设")
            selected = (
                self.cell_type.value if self.cell_type.value in presets else next(iter(presets))
            )
            save_preferences(presets, selected)
            self.cell_type.options = list(presets)
            self.cell_type.value = selected

        def add_preset():
            if (
                not self.preset_name.value.strip()
                or self.preset_name.value in self.preset_table.value["Cell type"].tolist()
            ):
                raise ValueError("细胞类型名称必须非空且唯一")
            self.preset_table.value = pd.concat(
                [
                    self.preset_table.value,
                    pd.DataFrame(
                        [[self.preset_name.value, widgets["ref_mz"].value]],
                        columns=self.preset_table.value.columns,
                    ),
                ],
                ignore_index=True,
            )

        def delete_preset():
            self.preset_table.value = self.preset_table.value.loc[
                ~self.preset_table.value["Cell type"].eq(self.cell_type.value)
            ].reset_index(drop=True)

        preset_editor = pn.Accordion(
            (
                "编辑全局预设",
                pn.Column(
                    self.preset_table,
                    self.preset_name,
                    self.button("添加预设", add_preset, role="auxiliary"),
                    self.button("删除当前预设", delete_preset, role="danger"),
                    self.button(
                        "恢复内置值",
                        lambda: setattr(
                            self.preset_table,
                            "value",
                            pd.DataFrame(
                                list(BUILTIN_PRESETS.items()),
                                columns=["Cell type", "Reference m/z"],
                            ),
                        ),
                    ),
                    self.button("保存全局预设", save_presets, role="auxiliary"),
                ),
            )
        )
        self.raw_page = pn.Column(
            "## ② 原始谱检查",
            "打开文件和靠后 RAW 单扫描可能需要等待。细胞预览在后台执行完整提取；"
            "运行状态见下方。修改参数或切换样本后，旧任务结果不会应用；当前不能立即取消。",
            flow(self.raw_sample, self.button("打开所选样本", self._open_raw, role="auxiliary")),
            self.parameter_note,
            pn.FlexBox(
                pn.Column(
                    r.summary,
                    pn.Tabs(
                        (
                            "离子流",
                            pn.Column(
                                r.selection_mode,
                                r.tic_pane,
                                r.tic_download,
                                r.eic_pane,
                                r.eic_download,
                            ),
                        ),
                        (
                            "合并谱",
                            pn.Column(
                                flow(r.merge_start, r.merge_end),
                                r.average_spectrum,
                                r.merge_update,
                                r.merge_note,
                                r.spectrum_pane,
                                r.spectrum_download,
                            ),
                        ),
                        (
                            "单扫描",
                            pn.Column(
                                r.scan_slider,
                                flow(r.scan_time, r.scan_index),
                                flow(r.scan_previous, r.scan_next),
                                r.scan_status,
                                r.scan_pane,
                            ),
                        ),
                    ),
                    pn.Accordion(
                        (
                            "显示范围与 EIC（不改变提取范围）",
                            pn.Column(
                                r.ms_level,
                                r.rt_range,
                                r.mz_min,
                                r.mz_max,
                                r.target_mz,
                                r.ppm,
                                r.more_references,
                                r.refresh_button,
                            ),
                        )
                    ),
                    styles={"flex": "3 1 480px", "min-width": "0"},
                    sizing_mode="stretch_width",
                ),
                pn.Column(
                    self.cell_type,
                    preset_editor,
                    form(*[widgets[k] for k in basic]),
                    pn.Accordion(
                        (
                            "高级处理参数",
                            form(*[w for k, w in widgets.items() if k not in basic]),
                        )
                    ),
                    r.processing.parameter_help,
                    flow(
                        self.button("应用为项目默认", lambda: self._apply_parameters(False)),
                        self.button("仅应用于当前样本", lambda: self._apply_parameters(True)),
                    ),
                    styles={"flex": "2 1 320px", "min-width": "0"},
                    sizing_mode="stretch_width",
                ),
                flex_wrap="wrap",
                align_items="flex-start",
                sizing_mode="stretch_width",
            ),
            self.preview_button,
            self.preview_status,
            self.button("确认当前预览合理", self._confirm_preview),
            r.cell_status,
            r.cell_pane,
            r.cell_download,
        )
        for widget in widgets.values():
            widget.param.watch(
                lambda _: setattr(
                    self.parameter_note,
                    "object",
                    "参数已编辑，尚未应用到项目；预览使用控件当前值。",
                ),
                "value",
            )
        self._select_raw()

    def _sample(self):
        return next((s for s in self.project.samples if s["id"] == self.raw_sample.value), None)

    def _select_raw(self):
        sample = self._sample()
        self.components._clear_raw_view()
        params = sample_parameters(self.project, sample)
        for key, value in params.items():
            self.components.processing.parameter_widgets[key].value = (
                ", ".join(map(str, value)) if key == "reference_mz" else value
            )
        self.parameter_note.object = "参数来源：" + (
            "样本例外" if sample and sample["parameters"] else "项目默认"
        )

    def _open_raw(self):
        sample = self._sample()
        if sample is None:
            raise ValueError("请先添加并选择样本")
        if sample.get("result_only"):
            raise ValueError("此样本来自已有结果，请先重新定位原始文件再进行原始谱检查")
        r = self.components
        r.root_select.value = sample["storage"]
        r._selector.value = [sample["path"]]
        r._load_selected(None)
        if r.preview is None:
            raise ValueError("原始文件读取失败")
        r._selection_mode()
        if (
            not sample.get("range_initialized")
            and sample["parameters"] is None
            and not self.project.manifest.get("manual_parameters")
        ):
            summary = r.preview.summary
            if summary.mz_min is not None and summary.mz_max is not None:
                widgets = r.processing.parameter_widgets
                widgets["mz_min"].value = math.floor(summary.mz_min / 10) * 10
                widgets["mz_max"].value = math.ceil(summary.mz_max / 10) * 10
                sample["auto_mz_range"] = [widgets["mz_min"].value, widgets["mz_max"].value]
                sample["range_initialized"] = True
                self.project.dirty = True

    def _apply_parameters(self, exception):
        params = asdict(self.components.processing._parameters())
        self.project.manifest["cell_type"] = self.cell_type.value
        if exception:
            if self._sample() is None:
                raise ValueError("请选择样本")
            self._sample()["parameters"] = params
            self._sample()["manual_parameters"] = True
        else:
            self.project.manifest["parameters"] = params
            self.project.manifest["manual_parameters"] = True
        self.project.dirty = True
        self._invalidate_preflight()
        self.parameter_note.object = "参数已应用；旧提取结果不会自动更新，请重新预览和处理。"
        self.sample_table.value = self._sample_frame()

    def _preview_cells(self):
        if self._cell_preview_job is not None:
            raise ValueError("已有细胞预览正在运行，请等待完成")
        sample = self._sample()
        raw = self.components
        if sample is None or raw.preview is None or str(raw.preview.path) != sample["path"]:
            raise ValueError("先打开当前样本")
        parameters = asdict(raw.processing._parameters())
        inputs = {
            s["path"]: file_identity(s["path"])
            for s in (
                self.project.samples
                if self.project.manifest["feature_strategy"] == "shared"
                else [sample]
            )
            if not s.get("result_only")
        }
        if inputs[sample["path"]] != raw.preview.open_identity:
            raise ValueError("原始文件已改变，请重新打开当前样本")
        request = {
            "project_folder": str(self.project.folder),
            "manifest": deepcopy(self.project.manifest),
            "sample_id": sample["id"],
            "parameters": parameters,
            "roots": [(r.label, str(r.path)) for r in self.catalog.roots],
            "inputs": inputs,
        }
        raw._invalidate_cells()
        future, state_path = submit_preview(request)
        self._cell_preview_job = {
            "future": future,
            "state_path": state_path,
            "project": self.project,
            "raw": raw,
            "preview": raw.preview,
            "context": self._preview_context(),
            "inputs": inputs,
            "sample": sample,
        }
        self.preview_button.disabled = self.preview_button.loading = True
        self.preview_status.object = "细胞预览已启动，正在准备计算；可继续操作页面。"
        return self.preview_status.object

    def _preview_context(self):
        # Include only extraction inputs, so unrelated metadata edits remain usable.
        manifest = self.project.manifest
        return json.dumps(
            {
                "sample": self.raw_sample.value,
                "generation": getattr(self.components, "_cell_generation", 0),
                "controls": asdict(self.components.processing._parameters()),
                "project": {
                    key: manifest.get(key)
                    for key in (
                        "parameters",
                        "feature_strategy",
                        "feature_merge_ppm",
                        "auto_ranges",
                        "manual_parameters",
                    )
                },
                "samples": [
                    {
                        key: s.get(key)
                        for key in (
                            "id",
                            "path",
                            "storage",
                            "parameters",
                            "auto_mz_range",
                            "range_initialized",
                            "result_only",
                        )
                    }
                    for s in self.project.samples
                ],
            },
            sort_keys=True,
        )

    def _poll_cell_preview(self):
        job = self._cell_preview_job
        if job is None:
            return
        if not job["future"].done():
            try:
                state = json.loads(job["state_path"].read_text(encoding="utf-8"))
                self.preview_status.object = (
                    f"细胞预览：{escape(state['message'])}。可继续操作页面。"
                )
            except (OSError, ValueError, KeyError):
                pass  # The future remains authoritative if a status read fails.
            return
        try:
            result = job["future"].result()
            if (
                self.project is not job["project"]
                or self.components is not job["raw"]
                or self.components.preview is not job["preview"]
                or self._preview_context() != job["context"]
                or any(file_identity(p) != identity for p, identity in job["inputs"].items())
            ):
                self.preview_status.object = (
                    "旧细胞预览已完成；样本、参数或文件已改变，结果未应用，请重新预览。"
                )
            else:
                raw = self.components
                figure = cell_detection_figure(result["detection"])
                for sample in self.project.samples:
                    sample.update(result["ranges"][sample["id"]])
                for key in ("mz_min", "mz_max"):
                    raw.processing.parameter_widgets[key].value = result["parameters"][key]
                raw._show_cell_detection(result["detection"], figure=figure)
                if result["reused"]:
                    raw.cell_status.object += " 已复用持久化预览，无需重新提取。"
                job["sample"]["preview"] = {
                    "parameters": result["parameters"],
                    "confirmed": False,
                    "artifact": result["artifact"],
                }
                self.project.dirty = True
                self.sample_table.value = self._sample_frame()
                self.preview_status.object = "细胞预览完成，请检查下图并确认；项目仍需主动保存。"
        except Exception as exc:
            self.preview_status.object = f"❌ 细胞预览失败：{escape(str(exc))}；可重新运行。"
        finally:
            self._cell_preview_job = None
            self.preview_button.disabled = self.preview_button.loading = False
        self.message.object = self.preview_status.object
        self._record(self.message.object)
        self.refresh_header()

    def _close_session(self, _context):
        LIVE_WORKSPACES.discard(self)
        if hasattr(self, "components"):
            self.components.close()
        if self._cell_preview_job is not None:
            self._cell_preview_job["future"].cancel()
            self._cell_preview_job = None
        if self._periodic is not None:
            self._periodic.stop()

    def _confirm_preview(self):
        if self._cell_preview_job is not None:
            raise ValueError("请等待当前细胞预览完成")
        sample = self._sample()
        if (
            sample is None
            or self._preview_status(sample) not in {"已预览，待确认", "已人工确认"}
            or self.components.cell_download.disabled
        ):
            raise ValueError("先应用参数并重新运行当前样本预览")
        sample["preview"]["confirmed"] = True
        self.project.dirty = True
        self.sample_table.value = self._sample_frame()

    def _batch_page(self):
        self.strategy = pn.widgets.Select(
            label="特征建立方式",
            options={"共同特征（默认）": "shared", "独立选峰后合并（高级）": "independent"},
            value=self.project.manifest["feature_strategy"],
        )
        self.strategy.param.watch(lambda e: self._metadata("feature_strategy", e.new), "value")
        self.batch_confirm = pn.widgets.Checkbox(label="确认样本与参数；未逐样本预览时也明确继续")
        self.batch_select = pn.widgets.Select(label="处理批次", options={})
        self.batch_table = pn.pane.DataFrame(pd.DataFrame(), height=230, index=False)
        self.preflight_details = pn.Column("尚未预检。", sizing_mode="stretch_width")
        self.preflight_json = pn.pane.JSON({}, depth=1)
        self.preflight_download = FileDownload(
            label="下载本次预检参数 JSON",
            filename="preflight.json",
            disabled=True,
            callback=lambda: BytesIO(
                json.dumps(self.preflight_json.object, ensure_ascii=False, indent=2).encode()
            ),
        )
        self.included = pn.widgets.MultiChoice(label="审核纳入的成功样本", options={})
        self.batch_qc = pn.Column()
        self.batch_select.param.watch(lambda _: self.poll(), "value")
        self.batch_page = pn.Column(
            "## ③ 提取与审核",
            "处理结束不等于已建立当前数据：请检查各样本状态与 QC，选择成功样本，"
            "点击“确认纳入并建立当前数据”，再进入预处理或分析。",
            self.strategy,
            "共同特征要求统一合谱与对齐参数；自动范围取所有样本范围的并集。预览特征与整批共同特征一致才可复用；不一致时重新提取。单样本失败继续其他样本。",
            self.button("检查全部样本与实际参数", self._preflight),
            self.preflight_details,
            pn.Accordion(
                ("高级：本次预检原始参数", pn.Column(self.preflight_download, self.preflight_json))
            ),
            self.batch_confirm,
            self.button("确认并开始处理", self._submit),
            self.batch_select,
            flow(
                self.button("刷新任务", self._refresh_batches, role="auxiliary"),
                self.button("重试未成功样本", self._retry),
                self.button("停止后续样本（当前样本继续）", self._stop, role="danger"),
            ),
            "重试须重新预检并确认，参数与输入保持不变。",
            self.batch_table,
            "停止请求不会立即中断当前读取或计算；已完成样本保留，等待当前阶段结束后停止后续样本。",
            self.included,
            self.button("比较所选成功样本的 QC", self._batch_qc, role="auxiliary"),
            self.batch_qc,
            self.replace_confirm,
            self.button("确认纳入并建立当前数据", self._review),
        )
        self._refresh_batches()

    def _initialize_ranges(self):
        initialize_ranges(self.project, self.components.service)

    def _preflight(self):
        self._invalidate_preflight()
        self._initialize_ranges()
        request = preflight(self.project, self.catalog)
        self._checked = json.dumps(request, sort_keys=True)
        self.preflight_json.object = request
        self.preflight_download.disabled = False
        self.preflight_download.data = None
        self.preflight_details[:] = [
            request_view(
                request, automatic_range=not self.project.manifest.get("manual_parameters", False)
            )
        ]
        apply_presentation(self.preflight_details)
        self.batch_confirm.value = False

    def _invalidate_preflight(self):
        self._checked = None
        if hasattr(self, "preflight_details"):
            self.preflight_details[:] = ["配置尚未检查或已改变，请重新预检。"]
            self.preflight_json.object = {}
            self.preflight_download.disabled = True
            self.preflight_download.data = None
            self.batch_confirm.value = False

    def _submit(self):
        if not self.batch_confirm.value or self._checked != json.dumps(
            preflight(self.project, self.catalog), sort_keys=True
        ):
            raise ValueError("先重新检查配置并明确确认")
        self._save()
        path = submit(self.project, self.catalog)
        self._refresh_batches()
        self.batch_select.value = str(path)
        self.batch_confirm.value = False

    def _refresh_batches(self):
        previous = self.batch_select.value
        self.batch_select.options = {
            f"{beijing_time(read_batch(p)['created_at'])} · {p.parent.name[-8:]}": str(p)
            for p in batches(self.project)
        }
        values = list(self.batch_select.options.values())
        self.batch_select.value = (
            previous if previous in values else (values[0] if values else None)
        )
        self.poll()

    def _retry(self):
        if (
            not self.batch_select.value
            or not self.batch_confirm.value
            or self._checked != json.dumps(preflight(self.project, self.catalog), sort_keys=True)
        ):
            raise ValueError("请选择批次，重新检查配置并确认")
        self._save()
        path = submit(self.project, self.catalog, retry_path=self.batch_select.value)
        self._refresh_batches()
        self.batch_select.value = str(path)
        self.batch_confirm.value = False

    def _stop(self):
        if not self.batch_select.value:
            raise ValueError("请选择批次")
        stop_after_current(self.batch_select.value)

    def _review(self):
        self._check_replacement()
        if not self.batch_select.value:
            raise ValueError("请选择批次")
        data = reviewed_dataset(self.batch_select.value, self.included.value)
        self.project.workspace.replace(data, source=self.batch_select.value)
        self._sync_metadata()
        self.project.saved_reports = {}
        self.project.dirty = True
        self.replace_confirm.value = False
        self.analysis.refresh()
        self._sample_summary()

    def _batch_qc(self):
        if not self.batch_select.value or not self.included.value:
            raise ValueError("请选择处理批次及成功样本")
        path = Path(self.batch_select.value)
        state = read_batch(path)
        frames = []
        for row in state["samples"]:
            if row["id"] in self.included.value and row["status"] == "succeeded":
                data = read_h5ad(child_path(path.parent, row["output"]))
                cells = quality_metrics(data)["cell"]
                cells["sample"] = row["name"]
                frames.append(cells)
        if not frames:
            raise ValueError("无成功样本可比较")
        frame = pd.concat(frames, ignore_index=True)
        self.batch_qc[:] = [
            fit_plot(pn.pane.Plotly(px.box(frame, x="sample", y=field, points=False)))
            for field in ("total_intensity", "detected_features")
        ]

    def _sample_summary(self):
        if not hasattr(self, "source_summary"):
            return
        data = self.project.workspace.data
        rows = []
        if data is not None and "group" in data.obs:
            for group, obs in data.obs.groupby("group", observed=True, dropna=False):
                subjects = (
                    obs["subject"].dropna().astype(str)
                    if "subject" in obs
                    else pd.Series(dtype=str)
                )
                count = subjects[subjects.str.strip().ne("")].nunique()
                rows.append(
                    {
                        "分组": str(group),
                        "细胞数": len(obs),
                        "独立来源数": count,
                        "说明": "仅细胞探索，不支持来源层面推断"
                        if count < 2
                        else "仍需核对真实实验设计",
                    }
                )
        self.source_summary.object = pd.DataFrame(rows)

    def poll(self):
        self._poll_cell_preview()
        if not self.project or not hasattr(self, "batch_select") or not self.batch_select.value:
            self.task_status.object = "任务：无所选批次"
            self.log.value = ""
            return
        try:
            state = read_batch(self.batch_select.value)
            batch_id = Path(self.batch_select.value).parent.name
            self.task_status.object = f"任务：**{escape(TASK_LABELS.get(state['status'], state['status']))}** · {escape(state.get('message', ''))}\n\n批次 ID：`{escape(batch_id)}`。报错时请同时提供此 ID 和完整任务日志。"
            self.batch_table.object = pd.DataFrame(
                [
                    {
                        "样本": row["name"],
                        "状态": TASK_LABELS.get(row["status"], row["status"]),
                        "结果来源": "复用预览" if row.get("reused_preview") else "本批处理",
                        "细胞数": row.get("cells"),
                        "特征数": row.get("features"),
                        "错误": row.get("error", ""),
                    }
                    for row in state["samples"]
                ]
            )
            options = {r["name"]: r["id"] for r in state["samples"] if r["status"] == "succeeded"}
            selected = [s for s in self.included.value if s in options.values()]
            self.included.options = options
            self.included.value = selected
            path = Path(self.batch_select.value).with_name("worker.log")
            failures = "\n".join(
                f"{row['name']}: {row['error']}" for row in state["samples"] if row.get("error")
            )
            if state["status"] in {"failed", "interrupted"}:
                failures = f"{state['status']}: {state.get('message', '')}\n{failures}"
            if failures and failures != getattr(self, "_last_batch_error", None):
                self._record(f"任务失败：{escape(failures)}")
            self._last_batch_error = failures
            if path.exists() and self.follow_log.value:
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - 30000))
                    value = handle.read().decode(errors="replace")
                    if self.log.value != value:
                        self.log.value = value
        except Exception as exc:
            self.task_status.object = f"任务读取失败：{escape(str(exc))}"
            if self.task_status.object != getattr(self, "_last_poll_error", None):
                self._record(self.task_status.object)
            self._last_poll_error = self.task_status.object

    def _preprocess_page(self):
        a = self.analysis
        self.operation = pn.widgets.Select(
            label="下一项操作",
            options={
                "筛选细胞与特征": "filter",
                "归一化 / 数值变换": "normalize",
                "零值插补（可选）": "impute",
                "异常值处理（可选）": "outliers",
            },
        )
        self.operation_controls = form()

        def controls(_=None):
            self._candidate = None
            if hasattr(self, "impact_preview"):
                self._invalidate_impact()
            self.operation_controls[:] = {
                "filter": [a.min_total, a.min_detected, a.feature_fraction],
                "normalize": [a.normalization, a.help("normalization")],
                "impute": [a.imputation, a.help("imputation")],
                "outliers": [a.contamination],
            }[self.operation.value]

        self.operation.param.watch(controls, "value")
        controls()
        self.impact = pn.pane.DataFrame(pd.DataFrame(), index=False)
        self.impact_qc_table = QCDataFrame(pd.DataFrame(), index=False, height=240)
        self.impact_qc_plot = fit_plot(pn.pane.Plotly(go.Figure()), "analysis")
        self.impact_preview = pn.Column(
            "### 检查后的候选数据（尚未应用）",
            self.impact_qc_table,
            self.impact_qc_plot,
            visible=False,
        )
        self.apply_confirm = pn.widgets.Checkbox(
            label="确认应用并清除下游分析；样本或分组可能被筛除"
        )
        self.impact_note = pn.pane.Markdown("先检查影响；计算在副本执行，不改变当前数据。")
        for widget in (
            a.min_total,
            a.min_detected,
            a.feature_fraction,
            a.normalization,
            a.imputation,
            a.contamination,
        ):
            widget.param.watch(self._invalidate_impact, "value")
        self.reset_confirm = pn.widgets.Checkbox(label="确认恢复预处理起点并清除下游结果")
        self.preprocess_page = pn.Column(
            "## ④ 预处理",
            a.summary,
            a.qc_table,
            "参考强度按样本和实际参考 m/z 分行显示；不同参考离子不合并，空记录不展示。",
            self.operation,
            self.operation_controls,
            "QC 检出按 >0 定义，建议在标准化或插补前筛选。全数据插补可能影响模型验证的独立性。",
            self.button("检查影响（不改变当前数据）", self._preview_operation),
            self.impact,
            self.impact_note,
            self.impact_preview,
            self.apply_confirm,
            self.button("应用到当前数据", self._apply_operation),
            a.history_table,
            self.reset_confirm,
            self.button("恢复到预处理起点", self._reset, role="danger"),
        )

    def _invalidate_impact(self, _event=None):
        self._candidate = None
        self.apply_confirm.value = False
        self.impact_preview.visible = False
        self.impact_note.object = "参数已改变；下方旧影响摘要不再有效，请重新检查。"

    def _signature(self):
        a = self.analysis
        return (
            self.project.workspace.token,
            self.operation.value,
            a.min_total.value,
            a.min_detected.value,
            a.feature_fraction.value,
            a.normalization.value,
            a.imputation.value,
            a.contamination.value,
        )

    def _preview_operation(self):
        self._invalidate_impact()
        state = self.project.workspace
        state.require_data()
        candidate = deepcopy(state)
        a = self.analysis
        op = self.operation.value
        if op == "filter":
            candidate.filter(
                min_total=a.min_total.value,
                min_detected=a.min_detected.value,
                min_feature_fraction=a.feature_fraction.value,
            )
        elif op == "normalize":
            candidate.normalize(a.normalization.value)
        elif op == "impute":
            candidate.impute(a.imputation.value)
        else:
            candidate.remove_outliers(a.contamination.value)
        rows = [
            {"对象": "细胞", "操作前": state.data.n_obs, "操作后": candidate.data.n_obs},
            {"对象": "特征", "操作前": state.data.n_vars, "操作后": candidate.data.n_vars},
        ]
        if "sample" in state.data.obs:
            before, after = (
                state.data.obs["sample"].value_counts(),
                candidate.data.obs["sample"].value_counts(),
            )
            rows.extend(
                {"对象": str(name), "操作前": int(count), "操作后": int(after.get(name, 0))}
                for name, count in before.items()
            )
        self.impact.object = pd.DataFrame(rows)
        qc = candidate.qc()
        self.impact_qc_table.object = qc_file_table(qc["file"])
        self.impact_qc_plot.object = px.scatter(
            qc["cell"],
            x="total_intensity",
            y="detected_features",
            color="source_file",
            title="检查后每细胞 QC（尚未应用）",
        )
        self.impact_preview.visible = True
        self._candidate = (self._signature(), candidate)
        self.impact_note.object = "影响检查有效；确认后将应用上述操作并清除下游结果。"
        self.apply_confirm.value = False

    def _apply_operation(self):
        if (
            not self.apply_confirm.value
            or self._candidate is None
            or self._candidate[0] != self._signature()
        ):
            raise ValueError("参数或数据变化后须重新检查影响，并确认应用")
        self.project.workspace = self._candidate[1]
        self.analysis.state = self.project.workspace
        self._candidate = None
        self.impact_preview.visible = False
        self.project.saved_reports = {}
        self.project.dirty = True
        self.apply_confirm.value = False
        self.analysis.refresh()
        self._sample_summary()

    def _reset(self):
        if not self.reset_confirm.value:
            raise ValueError("请先确认恢复起点的影响")
        self.project.workspace.reset()
        self._invalidate_impact()
        self.project.saved_reports = {}
        self.project.dirty = True
        self.reset_confirm.value = False
        self.analysis.refresh()

    def _analysis_page(self):
        a = self.analysis
        labels = {
            "reduction": "降维方法",
            "dimensions": "输出维数",
            "neighbors": "邻居数",
            "perplexity": "t-SNE perplexity",
            "seed": "随机种子",
            "cluster_method": "聚类方法",
            "clusters": "簇数",
            "diff_method": "比较方法",
            "model": "分类模型",
            "cv": "交叉验证折数",
            "test_size": "测试集比例",
            "calibration_bins": "校准分箱数",
            "network_method": "相关系数方法",
            "network_threshold": "绝对相关阈值",
            "network_top_features": "按方差选择前 N 个特征",
            "shap_background": "SHAP 训练背景样本上限",
            "shap_samples": "SHAP 测试解释样本上限",
        }
        for name in labels:
            getattr(a, name).label = name
        discovery = pn.Column(
            "### 1. 确认输入",
            a.summary,
            a.status,
            a.representation,
            "### 2. 设置降维",
            flow(a.reduction, a.dimensions, a.scale),
            pn.Accordion(
                (
                    "高级参数与结果名称",
                    pn.Column(
                        a.reduction_options,
                        a.neighbors,
                        a.perplexity,
                        a.seed,
                        a.embedding_key,
                        a.help("reduction", "n_components", "n_neighbors", "perplexity"),
                    ),
                )
            ),
            a._button("运行降维", a._reduce),
            "### 3. 查看结果",
            a.embedding_view,
            a.color_source,
            flow(a.color_search, a.color_clear),
            flow(a.color_sort, a.color_descending),
            a.color,
            a.color_note,
            a.embedding_plot,
            a.embedding_download,
            pn.Accordion(
                (
                    "可选：细胞聚类",
                    pn.Column(
                        a.cluster_method,
                        a.clusters,
                        a.cluster_key,
                        "聚类使用上方选定输入。DBSCAN 当前使用 eps=0.5、min_samples=5；图聚类 resolution=1。",
                        a._button(
                            "运行细胞聚类",
                            a._cluster,
                        ),
                    ),
                )
            ),
            "添加新的坐标或簇标签不会清空无关统计结果；同名结果不静默覆盖。",
        )

        def relevant(_=None):
            a.perplexity.visible = a.reduction.value == "tsne"
            a.neighbors.visible = a.reduction.value in {
                "umap",
                "isomap",
                "lle",
            } or a.cluster_method.value in {"leiden", "louvain"}
            a.clusters.visible = a.cluster_method.value in {"kmeans", "hierarchical"}

        a.reduction.param.watch(relevant, "value")
        a.cluster_method.param.watch(relevant, "value")
        relevant()
        self.source_summary = pn.pane.DataFrame(pd.DataFrame(), index=False)
        self.purpose = pn.widgets.RadioButtonGroup(
            label="你希望了解什么？",
            orientation="vertical",
            options=[
                "整体分布与分群",
                "实验分组差异",
                "各细胞簇的代表特征",
                "特征相关性",
                "分类模型与解释",
            ],
        )
        self.analysis_body = pn.Column()

        def show(_=None):
            self.analysis_body[:] = [
                {
                    "整体分布与分群": discovery,
                    "实验分组差异": pn.Column(
                        "### 细胞级探索性比较",
                        a.status,
                        flow(a.group, a.group_a, a.group_b),
                        flow(a.diff_layer, a.diff_method),
                        a._button("运行比较", a._differentiate),
                        a.volcano_controls,
                        a.volcano,
                        a.features,
                        a._button(
                            "清空选择", lambda: setattr(a.features, "value", []), role="auxiliary"
                        ),
                        a.hide_zero,
                        a.violin_width,
                        a.violin,
                        a.diff_table,
                        a.diff_download,
                    ),
                    "各细胞簇的代表特征": pn.Column(
                        "### 每簇对其余细胞",
                        a.status,
                        a.group,
                        a.diff_layer,
                        a.diff_method,
                        a._button(
                            "计算 Marker",
                            lambda: a.state.markers(
                                a.group.value, method=a.diff_method.value, layer=a.diff_layer.value
                            ),
                        ),
                        "每个比较内对全部特征校正，不是跨簇联合校正。",
                        a.marker_table,
                        a.extra_downloads["markers"],
                    ),
                    "特征相关性": pn.Column(
                        "### 特征相关网络，不代表因果或轨迹",
                        a.status,
                        a.diff_layer,
                        a.network_method,
                        a.network_threshold,
                        a.network_top_features,
                        a._button("运行相关分析", a._network),
                        a.network_plot,
                        a.network_table,
                        a.extra_downloads["network"],
                    ),
                    "分类模型与解释": pn.Column(
                        self.exploratory_split,
                        a._button("检查并训练当前模型", a._train),
                        a.supervised_page,
                        a.model_download,
                        a.extra_downloads["shap"],
                    ),
                }[self.purpose.value]
            ]
            apply_presentation(self.analysis_body)
            self._format_images()

        self.analysis_navigation[:] = ["### 分析", self.purpose]
        self.purpose.param.watch(show, "value")
        show()
        self.analysis_page = pn.Column(
            "## ⑤ 分析",
            "分析在当前会话同步运行，大数据的降维或 SHAP 可能较慢；运行结束前请勿刷新页面。"
            "参数变化后旧图仅供对照，需重新计算才能下载对应结果。",
            "每组单一来源时仅作细胞级探索；细胞数不是独立生物重复，FDR 不能修复该问题。",
            self.source_summary,
            self.analysis_body,
        )

    def _results_page(self):
        a = self.analysis
        self.reports = pn.pane.JSON(self.project.saved_reports, depth=2)
        self.saved_views = pn.Column()
        self.report_download = FileDownload(
            label="下载保存的报告 JSON",
            filename="saved_reports.json",
            callback=lambda: BytesIO(
                json.dumps(self.project.saved_reports, ensure_ascii=False).encode()
            ),
        )
        self.h5ad_download = FileDownload(
            label="下载上次保存的 H5AD", filename="current.h5ad", callback=self._download_h5ad
        )
        self.h5ad_download_name = pn.widgets.TextInput(label="下载 H5AD 文件名", width=480)
        self.output_paths = pn.pane.Markdown("")
        self.download_name_note = pn.pane.Markdown("")
        self.h5ad_download_name.param.watch(lambda _: self._validate_download_name(), "value")
        self._suggested_download_name = ""
        self._suggested_export_name = a.export_name.value
        self._output_signature = None
        a.export_root.value = "当前项目"
        a.export_directory.value = "exports"
        self.export_path = pn.pane.Markdown("")
        self.export_status = pn.pane.Markdown("")
        self.export_button = self.button(
            "保存 H5AD（含历史层与嵌入）", self._export_h5ad, role="download"
        )
        for widget in (a.export_root, a.export_directory, a.export_name):
            widget.param.watch(lambda _: self._refresh_export_path(), "value")
        self.project_download = FileDownload(
            label="下载项目摘要 JSON",
            filename="project_summary.json",
            callback=lambda: BytesIO(
                json.dumps(
                    {
                        "project": self.project.manifest,
                        "unsaved_changes": self.project.unsaved,
                        "history": self.project.workspace.history()
                        if self.project.workspace.data is not None
                        else [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode()
            ),
        )
        self.results_page = pn.Column(
            "## ⑥ 结果与保存",
            "离开前请确认页顶显示“已保存”。关闭提醒由浏览器控制，不保证每次出现；"
            "尚未应用的表单编辑不等于已保存参数。保存大型数据到云盘可能需要等待。",
            "项目保存用于继续工作，下载不替代项目保存。模型对象不保存，继续模型运算需重新训练。",
            self.button("保存项目", self._save),
            self.output_paths,
            pn.Accordion(("管理已保存项目、结果与回收区", self.saved_items)),
            pn.Accordion(
                (
                    "单独导出当前数据 H5AD",
                    pn.Column(
                        "导出包含当前数据、历史层与嵌入；文件名默认含项目、批次、北京时间和修订号，可修改。",
                        form(a.export_root, a.export_directory),
                        a.export_name,
                        self.export_path,
                        a.confirm_save,
                        self.export_button,
                        self.export_status,
                    ),
                )
            ),
            "### 下载当前结果",
            flow(a.matrix_download, a.diff_download, a.model_download),
            flow(a.embedding_download, a.qc_download, a.history_download),
            flow(
                self.components.tic_download,
                self.components.eic_download,
                self.components.spectrum_download,
                self.components.cell_download,
            ),
            self._result_figures(),
            flow(*a.extra_downloads.values()),
            "### 下载上次保存的数据",
            self.h5ad_download_name,
            self.download_name_note,
            self.h5ad_download,
            self.project_download,
            "页顶选择 PNG/SVG，再使用图形右上角相机按钮下载；上次保存的下载不包含未保存修改。",
            pn.Accordion(("已保存的只读报告", pn.Column(self.reports, self.report_download))),
            self.saved_views,
        )
        self._refresh_reports()
        self._update_output_names()

    def _result_figures(self):
        # Keep result-page models separate from the analysis page. Mount only
        # the requested plot: mounting hidden shared Plotly views can race
        # Panel's purge/resize callbacks during navigation.
        a = self.analysis
        sources = (
            ("嵌入", a.embedding_plot),
            ("差异", a.volcano),
            ("小提琴", a.violin),
            ("网络", a.network_plot),
            ("ROC", a.roc),
            ("PR", a.pr),
            ("校准", a.calibration),
            ("SHAP", a.shap_plot),
        )
        content = pn.Column()
        accordion = pn.Accordion(("当前分析图形", content))

        def show(_=None):
            if not accordion.active:
                return
            if content.objects:
                for pane, (_name, source) in zip(content[0], sources, strict=True):
                    pane.object = go.Figure(source.object)
            else:
                tabs = pn.Tabs(
                    *(
                        (name, source.clone(object=go.Figure(source.object), tags=[]))
                        for name, source in sources
                    ),
                    dynamic=True,
                )
                apply_presentation(tabs)
                content[:] = [tabs]
            self._format_images()

        accordion.param.watch(show, "active")
        self._refresh_result_figures = show
        return accordion

    def _refresh_export_path(self):
        a = self.analysis
        try:
            folder = a.catalog.resolve_output_directory(
                a.export_root.value, a.export_directory.value
            )
            self.export_path.object = f"导出路径：`{escape(str(folder / a.export_name.value))}`"
        except (ValueError, PermissionError, OSError) as exc:
            self.export_path.object = f"导出路径不可用：{escape(str(exc))}"

    def _export_h5ad(self):
        try:
            self.analysis._save()
        except Exception as exc:
            self.export_status.object = f"❌ 导出失败：{escape(str(exc))}"
            raise
        self.export_status.object = "✓ H5AD 已导出。" + self.export_path.object
        return self.export_status.object

    def _validate_download_name(self):
        name = self.h5ad_download_name.value.strip()
        valid = (
            bool(name)
            and Path(name).name == name
            and not any(c in name for c in "/\\")
            and name.lower().endswith(".h5ad")
        )
        self.h5ad_download.disabled = not valid or not self.project.manifest["artifacts"].get(
            "current"
        )
        self.download_name_note.object = "" if valid else "请输入以 .h5ad 结尾的文件名，不含路径。"
        if valid:
            self.h5ad_download.filename = name
            self.h5ad_download.data = None

    def _update_output_names(self):
        if not hasattr(self, "output_paths"):
            return
        p, a = self.project, self.analysis
        signature = (
            p.manifest["name"],
            p.manifest["revision"],
            tuple(s.get("batch", "") for s in p.samples),
            p.workspace.token,
        )
        if signature != self._output_signature:
            suggested = project_dataset_filename(p)
            if not a.export_name.value or a.export_name.value == self._suggested_export_name:
                a.export_name.value = suggested
            self._suggested_export_name = suggested
            self._output_signature = signature
        current = p.manifest["artifacts"].get("current")
        download = (
            Path(current).name
            if current and Path(current).name != "current.h5ad"
            else project_dataset_filename(p, timestamp=p.manifest["saved_at"])
        )
        if (
            not self.h5ad_download_name.value
            or self.h5ad_download_name.value == self._suggested_download_name
        ):
            self.h5ad_download_name.value = download
        self._suggested_download_name = download
        self.output_paths.object = (
            f"项目目录：`{escape(str(p.folder))}`"
            + (
                f"\n\n上次保存的数据：`{escape(str(child_path(p.folder, current)))}`"
                if current
                else ""
            )
            + "\n\n默认名称中的时间均为北京时间。"
        )
        a.save_button.disabled = p.workspace.data is None
        self.export_button.disabled = p.workspace.data is None
        self._validate_download_name()
        self._refresh_export_path()

    def _refresh_reports(self):
        if not hasattr(self, "reports"):
            return
        if (self.project.report_token or self.project.saved_token) != self.project.workspace.token:
            self.project.saved_reports = {}
            self.project.views.pop("figures", None)
        self.reports.object = self.project.saved_reports
        self.report_download.data = None
        self.project_download.data = None
        self.saved_views[:] = [
            pn.Accordion(
                (
                    f"已保存图形：{name}",
                    fit_plot(
                        pn.pane.Plotly(pio.from_json(value)),
                        "square" if name in {"embedding_plot", "network_plot"} else "analysis",
                    ),
                )
            )
            for name, value in self.project.views.get("figures", {}).items()
        ]

    def _download_h5ad(self):
        path = self.project.manifest["artifacts"].get("current")
        if path is None:
            raise ValueError("请先保存含当前数据的项目")
        return child_path(self.project.folder, path).open("rb")

    def _save(self):
        if self.project is None:
            raise ValueError("先新建或打开项目")
        figures = (
            dict(self.project.views.get("figures", {}))
            if self.project.saved_token == self.project.workspace.token
            else {}
        )
        for result, names in RESULT_PLOTS.items():
            if result in self.project.workspace.results:
                for name in names:
                    figures[name] = getattr(self.analysis, name).object.to_json()
        if self.project.workspace.data is not None and self.project.workspace.data.obsm:
            figures["embedding"] = self.analysis.embedding_plot.object.to_json()
        self.project.views = {
            "settings": {name: getattr(self.analysis, name).value for name in ANALYSIS_FIELDS},
            "figures": figures,
        }
        self.store.save(self.project)
        self._refresh_reports()
        self.h5ad_download.data = None
        self._refresh_home()
        self.saved_items.refresh()

    def _navigate(self, event):
        if not self._updating:
            self.run(lambda: self.go(STEPS.index(event.new)))

    def _next_step(self):
        index = self.step + 1
        if (
            self.step == 1
            and self.project.workspace.data is not None
            and not any(not sample.get("result_only") for sample in self.project.samples)
        ):
            index = 4
        self.go(index)

    def go(self, index):
        try:
            if not 0 <= index < len(STEPS):
                return
            if index and self.project is None:
                raise ValueError("先新建或打开项目")
            if index >= 4 and self.project.workspace.data is None:
                raise ValueError("先审核建立数据集，或导入已有结果")
            if index in {2, 3} and not self.project.samples:
                raise ValueError("原始处理需要样本文件；已有结果可直接进入预处理")
            self.step = index
            self.render()
        finally:
            self._updating = True
            self.navigation.value = STEPS[self.step]
            self._updating = False

    def render(self):
        if self.project is not None and self.step == 6:
            self._refresh_result_figures()
        pages = (
            [self.home]
            if self.project is None
            else [
                self.home,
                self.project_page,
                self.raw_page,
                self.batch_page,
                self.preprocess_page,
                self.analysis_page,
                self.results_page,
            ]
        )
        # Configure tables before attaching their models. Updating columns while
        # a newly mounted Tabulator is initializing can race its DOM creation.
        apply_presentation(pages[self.step])
        self.body[:] = [pages[self.step]]
        self.analysis_navigation.visible = self.step == 5
        self._format_images()
        self.footer.visible = self.step != 0
        self.previous.disabled = self.step <= 1
        self.next.disabled = self.step == 6
        self.refresh_header()

    def _format_images(self):
        from bokeh.models import CustomJS

        for pane in self.body.select(pn.pane.Plotly):
            # Pages can attach panes before presentation callbacks are registered.
            # Install on live models as well as future models (presentation.py).
            for model, _parent in pane._models.values():
                if not model.js_property_callbacks.get("change:config"):
                    model.js_on_change(
                        "config", CustomJS(code="cb_obj.properties.frames.change.emit()")
                    )
            config = {
                **(pane.config or {}),
                "toImageButtonOptions": {"format": self.image_format.value},
            }
            if pane.config != config:
                pane.config = config

    def refresh_header(self):
        self.close_button.disabled = self.project is None
        self.save_button.disabled = self.project is None
        self.unsaved_guard.dirty = bool(self.project and self.project.unsaved)
        if self.project is None:
            self.header.object = "选择或新建一个实验项目。"
        if self.project:
            p = self.project
            self.header.object = f"### {escape(p.manifest['name'])}\n{'● 有未保存修改' if p.unsaved else '✓ 已保存'} · {beijing_time(p.manifest['saved_at'])}"
            self._update_output_names()
            needs_samples = self.step == 1 and not p.samples and p.workspace.data is None
            needs_review = self.step == 3 and p.workspace.data is None
            self.next.disabled = self.step == 6 or needs_samples or needs_review
            self.next_note.object = (
                "请先添加原始文件或读取已有结果。"
                if needs_samples
                else "请先审核纳入成功样本并建立当前数据。"
                if needs_review
                else ""
            )

    def start_polling(self):
        if self._periodic is None:
            self._periodic = pn.state.add_periodic_callback(self.poll, period=2000)


def create_app(roots, output_roots=(), defaults=None, *, project_root=PROJECT_ROOT):
    pn.extension("plotly", "tabulator", notifications=True)
    dock_css = "#main .pn-wrapper { contain: none !important; overflow: visible !important; }"
    if dock_css not in pn.config.raw_css:
        pn.config.raw_css.append(dock_css)
    workspace = ProjectWorkspace(roots, project_root=project_root, defaults=defaults)
    template = pn.template.FastListTemplate(
        title="scMM 实验项目",
        sidebar=[workspace.navigation, workspace.analysis_navigation],
        sidebar_width=230,
        main=[workspace.panel],
        accent_base_color="#0f766e",
        header_background="#0f766e",
    )
    pn.state.onload(workspace.start_polling)
    return template
