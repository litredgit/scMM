"""Project-first six-step workbench; no legacy eight-tab application entry."""

from __future__ import annotations

import json
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path

import pandas as pd
import panel as pn
import plotly.express as px
import plotly.io as pio
from anndata import read_h5ad

from scMM.analysis.quality import quality_metrics
from scMM.application import OutputRoot, StorageCatalog, StorageRoot
from scMM.application.parameters import load_defaults
from scMM.application.project_batch import (
    batches,
    preflight,
    read_batch,
    reviewed_dataset,
    stop_after_current,
    submit,
)
from scMM.application.projects import PROJECT_ROOT, ProjectStore, child_path
from scMM.application.workbench import read_dataset

from .layout import CONTENT_STYLE, TaskDock, fit_plot
from .raw_components import PreviewWorkspace

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


class ProjectRawViews(PreviewWorkspace):
    def _invalidate_cells(self):
        if self.preview is None:
            return super()._invalidate_cells()
        self.cell_download.disabled = True
        self.cell_download.data = None
        self.cell_status.object = "参数已改变；下图为旧参数结果，请重新预览后确认。"

    def _invalidate_raw_plots(self):
        if self.preview is None:
            return super()._invalidate_raw_plots()
        for download in (self.tic_download, self.eic_download, self.spectrum_download):
            download.disabled = True
            download.data = None
        self.summary.object = "显示参数已改变；下图尚未刷新。"


class ProjectWorkspace:
    def __init__(self, roots, *, project_root=PROJECT_ROOT, defaults=None):
        self.store = ProjectStore(project_root)
        self.roots = tuple(roots)
        self.catalog = StorageCatalog(self.roots)
        self.defaults = defaults or load_defaults()
        self.project = None
        self.step = 0
        self._updating = False
        self._periodic = None
        self._checked = self._candidate = None
        self.header = pn.pane.Markdown("选择或新建一个实验项目。")
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
            pn.Row(self.header, self.save_button),
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
        self.activate(self.store.create(self.name.value, self.defaults))

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
        self._analysis_page()
        self._results_page()
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
        current = sample["parameters"] or self.project.manifest["parameters"]
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
            self.button("移出选中样本（不删除文件）", self._remove_samples),
            pn.Accordion(
                (
                    "添加多个原始文件",
                    pn.Column(
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
            "修改样本表不会改写已有数据，重新处理并审核后才替换。已有结果可直接进入预处理。",
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
        self.project.dirty = True
        self._update_samples()

    def _relocate_sample(self):
        if len(self.sample_table.selection) != 1 or len(self.files.value) != 1:
            raise ValueError("请选择一个样本和一个替代原始文件")
        path = self.catalog.resolve_raw_file(self.file_root.value, self.files.value[0])
        sample = self.project.samples[self.sample_table.selection[0]]
        if any(s["id"] != sample["id"] and s["path"] == str(path) for s in self.project.samples):
            raise ValueError("该文件已关联其他样本")
        sample.update(path=str(path), storage=self.file_root.value)
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
            self.project.samples[event.row][event.column] = str(event.value or "")
            self.project.dirty = True
            self._checked = None
            self.refresh_header()

    def _file_browser(self):
        root = self.catalog.root(self.file_root.value)
        self.files = pn.widgets.FileSelector(
            str(root.path),
            root_directory=str(root.path),
            file_pattern="*.mz*",
            only_files=True,
            height=250,
        )
        self.file_browser[:] = [self.files]

    def _update_samples(self):
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
        widgets = r.processing.parameter_widgets
        basic = ["extraction_method", "ref_mz", "mz_min", "mz_max", "cell_snr", "peak_snr"]
        self.raw_page = pn.Column(
            "## ② 原始谱检查",
            self.raw_sample,
            self.button("打开所选样本", self._open_raw),
            self.parameter_note,
            pn.Row(
                pn.Column(
                    r.summary,
                    pn.Tabs(
                        ("离子流", pn.Column(r.tic_pane, r.eic_pane)),
                        ("合并谱", r.spectrum_pane),
                        ("单扫描", pn.Column(r.scan_index, r.scan_button, r.scan_pane)),
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
        params = (sample["parameters"] if sample else None) or self.project.manifest["parameters"]
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
        r = self.components
        r.root_select.value = sample["storage"]
        r._selector.value = [sample["path"]]
        r._load_selected(None)
        if r.preview is None:
            raise ValueError("原始文件读取失败")

    def _apply_parameters(self, exception):
        params = asdict(self.components.processing._parameters())
        if exception:
            if self._sample() is None:
                raise ValueError("请选择样本")
            self._sample()["parameters"] = params
        else:
            self.project.manifest["parameters"] = params
        self.project.dirty = True
        self._checked = None
        self.parameter_note.object = "参数已应用；旧提取结果不会自动更新，请重新预览和处理。"
        self.sample_table.value = self._sample_frame()

    def _preview_cells(self):
        sample = self._sample()
        raw = self.components
        if sample is None or raw.preview is None or str(raw.preview.path) != sample["path"]:
            raise ValueError("先打开当前样本")
        raw._preview_cells()
        if raw.cell_download.disabled:
            raise ValueError(str(raw.cell_status.object))
        sample["preview"] = {"parameters": asdict(raw.processing._parameters()), "confirmed": False}
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
            self.strategy,
            "共同特征要求统一范围、合谱与对齐参数。单样本失败继续其他样本；共同特征构建失败则停止整批。",
            self.button("检查全部样本与实际参数", self._preflight),
            pn.Accordion(("本次预检的实际参数", self.preflight_details)),
            self.batch_confirm,
            self.button("确认并开始处理", self._submit),
            self.batch_select,
            self.button("刷新任务", self._refresh_batches),
            self.button("重试未成功样本（须先检查并确认，参数保持不变）", self._retry),
            self.batch_table,
            self.button("停止后续样本（当前样本继续）", self._stop),
            self.included,
            self.button("比较所选成功样本的 QC", self._batch_qc),
            self.batch_qc,
            self.replace_confirm,
            self.button("确认纳入并建立当前数据", self._review),
        )
        self._refresh_batches()

    def _preflight(self):
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
            self.task_status.object = f"任务：**{escape(TASK_LABELS.get(state['status'], state['status']))}** · {escape(state.get('message', ''))}"
            self.batch_table.object = pd.DataFrame(
                [
                    {
                        "样本": row["name"],
                        "状态": TASK_LABELS.get(row["status"], row["status"]),
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
            self.operation_controls[:] = {
                "filter": [a.min_total, a.min_detected, a.feature_fraction],
                "normalize": [a.normalization, a.help("normalization")],
                "impute": [a.imputation, a.help("imputation")],
                "outliers": [a.contamination],
            }[self.operation.value]

        self.operation.param.watch(controls, "value")
        controls()
        self.impact = pn.pane.DataFrame(pd.DataFrame(), index=False)
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
            a.qc_plot,
            a.qc_table,
            self.operation,
            self.operation_controls,
            "QC 检出按 >0 定义，建议在标准化或插补前筛选。全数据插补可能影响模型验证的独立性。",
            self.button("检查影响（不改变当前数据）", self._preview_operation),
            self.impact,
            self.impact_note,
            self.apply_confirm,
            self.button("应用到当前数据", self._apply_operation),
            a.history_table,
            self.reset_confirm,
            self.button("恢复到预处理起点", self._reset),
        )

    def _invalidate_impact(self, _event=None):
        self._candidate = None
        self.apply_confirm.value = False
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
        self.project.saved_reports = {}
        self.project.dirty = True
        self.apply_confirm.value = False
        self.analysis.refresh()
        self._sample_summary()

    def _reset(self):
        if not self.reset_confirm.value:
            raise ValueError("请先确认恢复起点的影响")
        self.project.workspace.reset()
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
        for name, label in labels.items():
            getattr(a, name).label = label
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
            a.color,
            a.embedding_plot,
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
        self.purpose = pn.widgets.Select(
            label="你希望了解什么？",
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
                        a.volcano,
                        a.features,
                        a.hide_zero,
                        a.violin,
                        a.diff_table,
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
                    ),
                    "分类模型与解释": pn.Column(
                        self.exploratory_split,
                        a._button("检查并训练当前模型", a._train),
                        a.supervised_page,
                    ),
                }[self.purpose.value]
            ]

        self.purpose.param.watch(show, "value")
        show()
        self.analysis_page = pn.Column(
            "## ⑤ 分析",
            "每组单一来源时仅作细胞级探索；细胞数不是独立生物重复，FDR 不能修复该问题。",
            self.purpose,
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
            "项目保存用于继续工作，下载不替代项目保存。模型对象不保存，继续模型运算需重新训练。",
            self.button("保存项目", self._save),
            pn.Row(a.matrix_download, a.diff_download, a.model_download),
            pn.Row(*a.extra_downloads.values()),
            self.h5ad_download,
            self.project_download,
            "图形右上角可导出 SVG；上次保存的下载不包含未保存修改。",
            pn.Accordion(("已保存的只读报告", pn.Column(self.reports, self.report_download))),
            self.saved_views,
        )
        self._refresh_reports()

    def _refresh_reports(self):
        if not hasattr(self, "reports"):
            return
        if self.project.saved_token != self.project.workspace.token:
            self.project.saved_reports = {}
            self.project.views = {}
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
        self.footer.visible = self.step != 0
        self.previous.disabled = self.step <= 1
        self.next.disabled = self.step == 6
        self.refresh_header()

    def refresh_header(self):
        self.save_button.disabled = self.project is None
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
        sidebar=[workspace.navigation],
        sidebar_width=230,
        main=[workspace.panel],
        accent_base_color="#0f766e",
        header_background="#0f766e",
    )
    pn.state.onload(workspace.start_polling)
    return template
