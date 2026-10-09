"""Project-first six-step workbench; no legacy eight-tab application entry."""

from __future__ import annotations

import json
import math
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pandas as pd
import panel as pn
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from anndata import read_h5ad

from scMM.analysis.quality import quality_metrics
from scMM.application import OutputRoot, StorageCatalog, StorageRoot
from scMM.application.parameters import load_defaults
from scMM.application.preferences import BUILTIN_PRESETS, load_preferences, save_preferences
from scMM.application.preview_cache import (
    load_detection,
    prepare_shared_targets,
    reusable_preview,
    save_preview,
    signature,
)
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

from .file_browser import FileBrowser
from .layout import CONTENT_STYLE, TaskDock, UnsavedGuard, fit_plot
from .presentation import QCDataFrame, apply_presentation, english_parameters, qc_file_table
from .project_views import ProjectRawViews
from .raw_components import PreviewWorkspace as PreviewWorkspace

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
                self.button("清除错误提示", self._clear_error),
                self.event_log,
                self.follow_log,
                self.log,
                pn.widgets.FileDownload(
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
        self.previous = self.button("上一步", lambda: self.go(self.step - 1))
        self.next = self.button("下一步", lambda: self.go(self.step + 1))
        self.leave = pn.widgets.Checkbox(label="确认放弃未保存修改，再新建或打开其他项目")
        self.name = pn.widgets.TextInput(label="新项目名称")
        self.project_select = pn.widgets.Select(label="已保存项目", options={})
        self.home = pn.Column(
            "## 实验项目",
            f"项目位置：`{escape(str(self.store.root))}`",
            self.name,
            self.button("新建项目", self._create),
            self.project_select,
            self.button("打开所选项目", self._open),
            self.leave,
            "从已有结果开始：先新建项目，再导入结果目录或 H5AD。",
        )
        self.footer = pn.Row(self.previous, pn.Spacer(), self.next)
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
        self._refresh_home()
        self.render()

    def button(self, label, action):
        button = pn.widgets.Button(label=label, color="primary")
        button.on_click(lambda _: self.run(action))
        return button

    def run(self, action):
        try:
            action()
            self.message.object = "操作完成。"
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
        self.events.append(f"{datetime.now().strftime('%H:%M:%S')} {message}")
        self.events = self.events[-100:]
        self.event_log.value = "\n".join(self.events)
        if "❌" in message or "失败" in message:
            self.error_notice.object = message
            self.error_notice.visible = True
            self.task_dock.label = "❌ 有错误待查看 — 点击展开任务日志"

    def _refresh_home(self):
        previous = self.project_select.value
        self.project_select.options = {
            f"{p['name']} · {p['samples']} 文件 · {p['saved_at']}": p["path"]
            for p in self.store.list()
        }
        values = list(self.project_select.options.values())
        self.project_select.value = (
            previous if previous in values else (values[0] if values else None)
        )

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
            label="项目名称", value=self.project.manifest["name"]
        )
        self.project_name.param.watch(lambda e: self._metadata("name", e.new), "value")
        self.description = pn.widgets.TextAreaInput(
            label="说明", value=self.project.manifest["description"]
        )
        self.description.param.watch(lambda e: self._metadata("description", e.new), "value")
        self.sample_table = pn.widgets.Tabulator(
            self._sample_frame(),
            show_index=False,
            hidden_columns=["id", "storage", "parameters"],
            selectable="checkbox",
            height=260,
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
        self.project_page = pn.Column(
            "## ① 项目与样本",
            self.project_name,
            self.description,
            "group：实验分组；subject：独立生物来源，同一来源的多个文件填写相同 ID；batch：采集批次。",
            self.sample_table,
            self.sample_csv,
            self.mapping_panel,
            self.button("移出选中样本（不删除文件）", self._remove_samples),
            pn.Accordion(
                (
                    "添加多个原始文件",
                    pn.Column(
                        "支持 Thermo RAW（profile）、mzML 和 mzXML；其他文件不会被加入项目。",
                        self.file_root,
                        self.file_browser,
                        self.button("添加所选文件", self._add_files),
                        self.button("用所选文件重新定位一个选中样本", self._relocate_sample),
                    ),
                )
            ),
            pn.Accordion(
                (
                    "从已有结果开始",
                    pn.Column(
                        a.root,
                        a.path,
                        a.browser,
                        a.trust,
                        self.replace_confirm,
                        self.button("读取结果并建立当前数据", self._import_result),
                    ),
                )
            ),
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
        self._checked = None
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
            self._checked = None
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
        previous = self.raw_sample.value
        self.raw_sample.options = {s["name"]: s["id"] for s in self.project.samples}
        values = list(self.raw_sample.options.values())
        self.raw_sample.value = previous if previous in values else (values[0] if values else None)
        self._checked = None
        self.refresh_header()

    def _add_files(self):
        if not self.files.value:
            raise ValueError("请选择文件")
        self.project.add_files(self.catalog, self.file_root.value, self.files.value)
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
        self._sample_summary()

    def _raw_page(self):
        r = self.components
        self.raw_sample = pn.widgets.Select(
            label="当前样本", options={s["name"]: s["id"] for s in self.project.samples}
        )
        self.raw_sample.param.watch(lambda _: self._select_raw(), "value")
        self.parameter_note = pn.pane.Markdown("")
        r.setup_navigation()
        widgets = r.processing.parameter_widgets
        basic = ["extraction_method", "ref_mz", "mz_min", "mz_max", "cell_snr", "peak_snr"]
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
                    self.button("添加预设", add_preset),
                    self.button("删除当前预设", delete_preset),
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
                    self.button("保存全局预设", save_presets),
                ),
            )
        )
        self.raw_page = pn.Column(
            "## ② 原始谱检查",
            "打开文件、细胞检测和靠后 RAW 单扫描可能需要等待；细胞预览执行完整提取，"
            "不是快速估算。计算期间请勿重复点击，当前预览不能后台运行或立即取消。",
            self.raw_sample,
            self.button("打开所选样本", self._open_raw),
            self.parameter_note,
            pn.Row(
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
                                pn.Row(r.merge_start, r.merge_end),
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
                                pn.Row(r.scan_time, r.scan_index),
                                pn.Row(r.scan_previous, r.scan_next, r.scan_button),
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
                ),
                pn.Column(
                    self.cell_type,
                    preset_editor,
                    *[widgets[k] for k in basic],
                    pn.Accordion(
                        (
                            "高级处理参数",
                            pn.Column(*[w for k, w in widgets.items() if k not in basic]),
                        )
                    ),
                    r.processing.parameter_help,
                    self.button("应用为项目默认", lambda: self._apply_parameters(False)),
                    self.button("仅应用于当前样本", lambda: self._apply_parameters(True)),
                ),
            ),
            self.button("运行当前样本细胞检测预览", self._preview_cells),
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
        r._scan_catalog()
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
        self._checked = None
        self.parameter_note.object = "参数已应用；旧提取结果不会自动更新，请重新预览和处理。"
        self.sample_table.value = self._sample_frame()

    def _preview_cells(self):
        sample = self._sample()
        raw = self.components
        if sample is None or raw.preview is None or str(raw.preview.path) != sample["path"]:
            raise ValueError("先打开当前样本")
        targets = None
        if self.project.manifest["feature_strategy"] == "shared":
            self._initialize_ranges()
            request = preflight(self.project, self.catalog)
            if (
                self.project.manifest.get("auto_ranges")
                and not self.project.manifest.get("manual_parameters")
                and sample["parameters"] is None
            ):
                for key in ("mz_min", "mz_max"):
                    raw.processing.parameter_widgets[key].value = request["parameters"][key]
            from scMM.application.project_batch import SHARED_FIELDS

            current = asdict(raw.processing._parameters())
            if any(current[key] != request["parameters"][key] for key in SHARED_FIELDS):
                raise ValueError("共同特征参数已编辑，请先应用为项目默认再预览")
            targets = prepare_shared_targets(self.project, request)
        parameters = raw.processing._parameters()
        before = signature(sample["path"], parameters)
        cached = reusable_preview(
            self.project.folder, {**sample, "parameters": asdict(parameters)}, targets
        )
        raw._preview_cells(
            cached_result=load_detection(cached) if cached else None, targets=targets
        )
        if raw.cell_download.disabled:
            raise ValueError(str(raw.cell_status.object))
        raw._selection_mode()
        if cached:
            raw.cell_status.object += " 已复用持久化预览，无需重新提取。"
        sample["preview"] = {
            "parameters": asdict(parameters),
            "confirmed": False,
            "artifact": sample["preview"]["artifact"]
            if cached
            else save_preview(self.project, sample, raw.preview, parameters, before),
        }
        self.project.dirty = True
        self.sample_table.value = self._sample_frame()

    def _confirm_preview(self):
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
        self.preflight_details = pn.pane.JSON({}, depth=1)
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
            pn.Accordion(("本次预检的实际参数", self.preflight_details)),
            self.batch_confirm,
            self.button("确认并开始处理", self._submit),
            self.batch_select,
            self.button("刷新任务", self._refresh_batches),
            self.button("重试未成功样本（须先检查并确认，参数保持不变）", self._retry),
            self.batch_table,
            self.button("停止后续样本（当前样本继续）", self._stop),
            "停止请求不会立即中断当前读取或计算；已完成样本保留，等待当前阶段结束后停止后续样本。",
            self.included,
            self.button("比较所选成功样本的 QC", self._batch_qc),
            self.batch_qc,
            self.replace_confirm,
            self.button("确认纳入并建立当前数据", self._review),
        )
        self._refresh_batches()

    def _initialize_ranges(self):
        if self.project.manifest.get("auto_ranges") and not self.project.manifest.get(
            "manual_parameters"
        ):
            for sample in self.project.samples:
                if (
                    sample["parameters"] is not None
                    or sample.get("auto_mz_range")
                    or sample.get("result_only")
                ):
                    continue
                preview = self.components.service.open(sample["storage"], sample["path"])
                summary = preview.summary
                if summary.mz_min is not None and summary.mz_max is not None:
                    sample["auto_mz_range"] = [
                        math.floor(summary.mz_min / 10) * 10,
                        math.ceil(summary.mz_max / 10) * 10,
                    ]
                    sample["range_initialized"] = True
                    self.project.dirty = True

    def _preflight(self):
        self._initialize_ranges()
        request = preflight(self.project, self.catalog)
        self._checked = json.dumps(request, sort_keys=True)
        self.preflight_details.object = request
        self.batch_table.object = pd.DataFrame(
            [
                {"样本": s["name"], "实际参数": json.dumps(s["parameters"], ensure_ascii=False)}
                for s in request["samples"]
            ]
        )
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
            f"{read_batch(p).get('created_at', '')} · {p.parent.name[:8]}": str(p)
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
        self.operation_controls = pn.Column()

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
            self.button("恢复到预处理起点", self._reset),
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
            pn.Row(a.reduction, a.dimensions, a.scale),
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
            a.color_search,
            pn.Row(a.color_sort, a.color_descending),
            a.color,
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
                            lambda: a.state.cluster(
                                a.cluster_method.value,
                                use_rep=a.representation.value,
                                key=a.cluster_key.value,
                                n_clusters=a.clusters.value,
                                n_neighbors=a.neighbors.value,
                                random_state=a.seed.value,
                            ),
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
                        pn.Row(a.group, a.group_a, a.group_b),
                        pn.Row(a.diff_layer, a.diff_method),
                        a._button("运行比较", a._differentiate),
                        a.volcano_controls,
                        a.volcano,
                        a.features,
                        a._button("清空选择", lambda: setattr(a.features, "value", [])),
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
        self.report_download = pn.widgets.FileDownload(
            label="下载保存的报告 JSON",
            filename="saved_reports.json",
            callback=lambda: BytesIO(
                json.dumps(self.project.saved_reports, ensure_ascii=False).encode()
            ),
        )
        self.h5ad_download = pn.widgets.FileDownload(
            label="下载上次保存的 H5AD", filename="current.h5ad", callback=self._download_h5ad
        )
        self.project_download = pn.widgets.FileDownload(
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
            pn.Row(a.matrix_download, a.diff_download, a.model_download),
            pn.Row(a.embedding_download, a.qc_download, a.history_download),
            pn.Row(
                self.components.tic_download,
                self.components.eic_download,
                self.components.spectrum_download,
                self.components.cell_download,
            ),
            pn.Accordion(
                (
                    "当前分析图形",
                    pn.Column(
                        a.embedding_plot,
                        a.volcano,
                        a.violin_width,
                        a.violin,
                        a.network_plot,
                        a.roc,
                        a.pr,
                        a.calibration,
                        a.shap_plot,
                    ),
                )
            ),
            pn.Row(*a.extra_downloads.values()),
            self.h5ad_download,
            self.project_download,
            "页顶选择 PNG/SVG，再使用图形右上角相机按钮下载；上次保存的下载不包含未保存修改。",
            pn.Accordion(("已保存的只读报告", pn.Column(self.reports, self.report_download))),
            self.saved_views,
        )
        self._refresh_reports()

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

    def _navigate(self, event):
        if not self._updating:
            self.run(lambda: self.go(STEPS.index(event.new)))

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
        self.body[:] = [pages[self.step]]
        self.analysis_navigation.visible = self.step == 5
        apply_presentation(self.body)
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
        self.save_button.disabled = self.project is None
        self.unsaved_guard.dirty = bool(self.project and self.project.unsaved)
        if self.project:
            p = self.project
            self.header.object = f"### {escape(p.manifest['name'])}\n{'● 有未保存修改' if p.unsaved else '✓ 已保存'} · {p.manifest['saved_at']}"

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
