"""Guided processing controls backed by persistent server-side tasks."""

from __future__ import annotations

from dataclasses import asdict
from html import escape
from pathlib import Path

import panel as pn
import plotly.graph_objects as go

from scMM.application import (
    OutputCatalog,
    OutputRoot,
    ProcessingParameters,
    ProcessingPlanner,
    ProcessingRequest,
    ProcessingTaskManager,
    StorageCatalog,
    load_quality_report,
)
from scMM.application.parameters import PROCESSING_HELP
from scMM.application.tasks import background_tasks_supported

_PLOT_CONFIG = {"displaylogo": False, "responsive": True, "scrollZoom": True}
_DIRECTORY_ONLY_PATTERN = ".__scmm_directory_selector_no_files__"

_PRESETS = {
    "均衡（推荐起点）": "balanced",
    "灵敏（保留更多弱信号）": "sensitive",
    "严格（减少噪声特征）": "strict",
}
_STATUS_LABELS = {
    "queued": "等待启动",
    "running": "处理中",
    "succeeded": "已完成",
    "failed": "失败",
}


class GuidedProcessingPanel:
    """Collect, preflight, submit, and recover processing tasks."""

    def __init__(
        self, storage: StorageCatalog, output_roots: tuple[OutputRoot, ...], defaults=None
    ) -> None:
        self.storage = storage
        self.outputs = OutputCatalog(output_roots)
        self.planner = ProcessingPlanner(storage, self.outputs)
        self.tasks = ProcessingTaskManager(self.planner, self.outputs.roots[0].path / ".scmm-tasks")
        self._storage_label: str | None = None
        self._input_path: str | None = None
        self._request: ProcessingRequest | None = None
        self._active_task_id: str | None = None
        self._periodic = None
        self._output_selector: pn.widgets.FileSelector | None = None
        self._output_path: Path | None = None

        self.input_text = pn.pane.Markdown(
            "尚未选择输入文件。请先在左侧选择并预览原始数据。",
            css_classes=["scmm-card"],
        )
        self.preset = pn.widgets.Select(
            label="参数预设",
            options=_PRESETS,
            value="balanced",
            width=210,
            sizing_mode=None,
        )
        self.output_select = pn.widgets.Select(
            label="结果存储",
            options=[root.label for root in self.storage.roots],
            width=180,
            sizing_mode=None,
        )
        self.output_selector_area = pn.Column(sizing_mode="stretch_width")
        self.output_directory = pn.pane.Markdown(
            "尚未选择结果目录。", css_classes=["scmm-card"], sizing_mode="stretch_width"
        )
        self.use_current_directory = pn.widgets.Button(
            label="使用当前浏览目录",
            icon="folder-check",
            width=180,
            height=36,
            sizing_mode="fixed",
        )
        self.result_name = pn.widgets.TextInput(
            label="结果名称", placeholder="默认使用原始文件名", width=220, sizing_mode=None
        )
        self.ref_mz = _float_input("参考离子 m/z", 100.0, step=0.0001)
        self.ppm_tol = _float_input("对齐容差 ppm", 10.0, step=0.5)
        self.resolution = _float_input("m/z 200 分辨率", 35_000.0, step=1_000)
        self.cell_snr = _float_input("细胞 SNR", 5.0, step=0.5)
        self.peak_snr = _float_input("特征 SNR", 3.0, step=0.5)
        self.n_jobs = pn.widgets.IntInput(
            label="n_jobs", value=1, start=-1, width=140, sizing_mode=None
        )
        self.ms_peak_snr = _float_input("总谱 SNR", 10.0, step=1.0)
        self.points_per_fwhm = _float_input("每 FWHM 采样点", 5.0, step=0.5)
        self.baseline_size = pn.widgets.IntInput(
            label="基线窗口", value=50, start=1, end=100_000, width=140, sizing_mode=None
        )
        self.max_zero_frac = _float_input("最大零值比例", 0.9, step=0.01)
        self.extra_parameters = {
            "mz_min": pn.widgets.FloatInput(label="提取 m/z 下限", value=100.0),
            "mz_max": pn.widgets.FloatInput(label="提取 m/z 上限", value=1000.0),
            "extraction_method": pn.widgets.Select(label="提取算法", options=["legacy", "snr_v1"]),
            "reference_mz": pn.widgets.TextInput(label="SNR 参考 m/z（逗号分隔，空为 ref_mz）"),
            "reference_mode": pn.widgets.Select(
                label="参考组合", options=["union", "intersection"]
            ),
            "reference_ppm_tol": pn.widgets.FloatInput(label="参考匹配 ppm", value=10.0),
            "feature_snr_threshold": pn.widgets.FloatInput(label="SNR 特征阈值", value=3.0),
            "noise_window": pn.widgets.IntInput(label="噪声窗口（帧）", value=51, start=2),
            "feature_block_size": pn.widgets.IntInput(label="特征分块数", value=256, start=1),
        }
        self.parameter_widgets = {
            "ref_mz": self.ref_mz,
            "ppm_tol": self.ppm_tol,
            "resolution": self.resolution,
            "cell_snr": self.cell_snr,
            "peak_snr": self.peak_snr,
            "n_jobs": self.n_jobs,
            "ms_peak_snr_threshold": self.ms_peak_snr,
            "resample_points_per_fwhm": self.points_per_fwhm,
            "baseline_filter_size": self.baseline_size,
            "max_zero_frac": self.max_zero_frac,
            **self.extra_parameters,
        }
        for key, widget in self.parameter_widgets.items():
            widget.label = key
        for key in ("ref_mz", "mz_min", "mz_max"):
            self.parameter_widgets[key].format = "0.0000"
        self.defaults = defaults or ProcessingParameters(ref_mz=100.0)
        for key, value in asdict(self.defaults).items():
            self.parameter_widgets[key].value = (
                ", ".join(map(str, value)) if key == "reference_mz" else value
            )
        self.parameter_help = pn.Accordion(
            (
                "参数含义、单位与算法差异",
                pn.pane.Markdown(
                    "\n\n".join(f"**{key}**：{text}" for key, text in PROCESSING_HELP.items())
                ),
            ),
            active=[],
        )
        self.progress = pn.indicators.Progress(label="处理进度", value=0, max=100)
        self.advanced_toggle = pn.widgets.Toggle(
            label="显示高级参数", icon="adjustments", width=150, height=36, sizing_mode="fixed"
        )
        self.advanced = pn.FlexBox(
            self.ms_peak_snr,
            self.points_per_fwhm,
            self.baseline_size,
            self.max_zero_frac,
            *self.extra_parameters.values(),
            gap="10px",
            visible=False,
            sizing_mode="stretch_width",
        )
        self.overwrite = pn.widgets.Checkbox(label="允许写入已有同名结果", value=False)
        self.save_button = pn.widgets.Button(
            label="保存到所选目录",
            icon="device-floppy",
            color="success",
            width=170,
            height=38,
            sizing_mode="fixed",
        )
        self.confirm_discard = pn.widgets.Checkbox(label="确认删除未保存的临时结果", value=False)
        self.discard_button = pn.widgets.Button(
            label="放弃并删除临时结果",
            icon="trash",
            color="danger",
            width=190,
            height=38,
            sizing_mode="fixed",
            disabled=True,
        )
        self.save_status = pn.pane.Markdown(
            "处理完成并查看结果后，可决定是否永久保存。", css_classes=["scmm-card"]
        )
        self.preflight_button = pn.widgets.Button(
            label="检查参数与存储",
            icon="checklist",
            color="primary",
            width=170,
            height=38,
            sizing_mode="fixed",
        )
        self.confirm = pn.widgets.Checkbox(
            label="我已核对参考离子和处理参数",
            value=False,
            disabled=True,
        )
        self.submit_button = pn.widgets.Button(
            label="开始后台处理",
            icon="player-play",
            color="success",
            width=160,
            height=38,
            sizing_mode="fixed",
            disabled=True,
        )
        self.preflight_text = pn.pane.Markdown("修改参数后先执行预检。", css_classes=["scmm-card"])

        self.task_select = pn.widgets.Select(
            label="任务记录", options={"暂无任务": None}, value=None, sizing_mode="stretch_width"
        )
        self.refresh_button = pn.widgets.Button(
            label="刷新状态",
            icon="refresh",
            width=120,
            height=36,
            sizing_mode="fixed",
        )
        self.status_text = pn.pane.Markdown("暂无任务。", css_classes=["scmm-card"])
        self.log_text = pn.widgets.TextAreaInput(
            label="任务日志（最新 100 KB）",
            value="",
            disabled=True,
            height=220,
            sizing_mode="stretch_width",
        )
        self.quality_summary = pn.pane.Markdown(
            "任务完成后显示质量检查。", css_classes=["scmm-card"]
        )
        self.intensity_plot = pn.pane.Plotly(
            _empty_figure("每细胞总强度"),
            config=_PLOT_CONFIG,
            height=280,
            styles={"flex": "1 1 420px", "min-width": "0"},
        )
        self.detection_plot = pn.pane.Plotly(
            _empty_figure("特征检出率"),
            config=_PLOT_CONFIG,
            height=280,
            styles={"flex": "1 1 420px", "min-width": "0"},
        )
        self.pca_plot = pn.pane.Plotly(
            _empty_figure("PCA"),
            config=_PLOT_CONFIG,
            height=320,
            styles={"flex": "1 1 420px", "min-width": "0"},
        )
        self.umap_plot = pn.pane.Plotly(
            _empty_figure("UMAP"),
            config=_PLOT_CONFIG,
            height=320,
            styles={"flex": "1 1 420px", "min-width": "0"},
        )
        self.cell_table = pn.pane.DataFrame(height=260, sizing_mode="stretch_width", index=False)
        self.feature_table = pn.pane.DataFrame(height=260, sizing_mode="stretch_width", index=False)
        artifact_names = (
            ("处理矩阵 CSV", "data.csv"),
            ("细胞元数据 CSV", "peak_meta.csv"),
            ("特征元数据 CSV", "feature_meta.csv"),
            ("细胞质量 CSV", "cell-quality.csv"),
            ("特征质量 CSV", "feature-quality.csv"),
            ("PCA/UMAP CSV", "embedding.csv"),
            ("运行清单 JSON", "scmm-manifest.json"),
        )
        self.artifact_downloads = {
            filename: pn.widgets.FileDownload(
                label=label,
                icon="download",
                file=None,
                disabled=True,
                width=145,
                height=36,
                sizing_mode="fixed",
            )
            for label, filename in artifact_names
        }
        self.quality_section = pn.Column(
            "### 4. 质量检查与结果下载",
            self.quality_summary,
            pn.FlexBox(
                self.intensity_plot,
                self.detection_plot,
                gap="12px",
                sizing_mode="stretch_width",
            ),
            pn.FlexBox(
                self.pca_plot,
                self.umap_plot,
                gap="12px",
                sizing_mode="stretch_width",
            ),
            pn.Tabs(
                ("细胞质量（前 200 行）", self.cell_table),
                ("特征质量（前 200 行）", self.feature_table),
                dynamic=False,
                sizing_mode="stretch_width",
            ),
            pn.FlexBox(
                *self.artifact_downloads.values(),
                gap="8px",
                sizing_mode="stretch_width",
            ),
            pn.pane.Markdown(
                "单文件会下载到当前浏览器的默认下载目录，并自动加上结果名称前缀；"
                "如需在服务器上保留完整结果，请使用下方保存功能。",
                css_classes=["scmm-hint"],
            ),
            visible=False,
            sizing_mode="stretch_width",
        )
        self.save_section = pn.Column(
            "### 5. 是否保存结果",
            "结果当前位于任务临时区。请选择一个服务器文件夹；完整结果（包括质量 CSV/JSON）会保存到该文件夹下的结果名称子目录中。也可明确放弃。",
            self.output_select,
            self.output_selector_area,
            pn.FlexBox(
                self.use_current_directory,
                self.output_directory,
                gap="10px",
                align_items="center",
                sizing_mode="stretch_width",
            ),
            pn.FlexBox(
                self.result_name,
                self.overwrite,
                self.save_button,
                gap="10px",
                align_items="flex-end",
                sizing_mode="stretch_width",
            ),
            pn.FlexBox(
                self.confirm_discard,
                self.discard_button,
                gap="10px",
                align_items="center",
                sizing_mode="stretch_width",
            ),
            self.save_status,
            visible=False,
            sizing_mode="stretch_width",
        )
        self._quality_task_id: str | None = None

        self._wire_callbacks()
        self._replace_output_selector()
        self._set_output_path(self.storage.roots[0].path / "results")
        self._reload_tasks()
        if not background_tasks_supported():
            self.preflight_button.disabled = True
            self.submit_button.disabled = True
            self.preflight_text.object = (
                "此平台仅开放读取、预览和分析；后台提取任务暂只支持 Linux。"
            )

    def panel(self):
        """Return the processing and task-status page."""
        primary = pn.FlexBox(
            self.preset,
            self.ref_mz,
            self.ppm_tol,
            self.resolution,
            self.cell_snr,
            self.peak_snr,
            self.n_jobs,
            gap="10px",
            align_items="flex-end",
            sizing_mode="stretch_width",
        )
        actions = pn.FlexBox(
            self.preflight_button,
            self.confirm,
            self.submit_button,
            gap="12px",
            align_items="center",
            sizing_mode="stretch_width",
        )
        task_header = pn.FlexBox(
            self.task_select,
            self.refresh_button,
            gap="10px",
            align_items="flex-end",
            sizing_mode="stretch_width",
        )
        return pn.Column(
            "## 原始数据处理与审核保存",
            "按顺序完成参数设置、预检、明确确认和后台提交。关闭页面不会中止已提交任务。",
            self.input_text,
            "### 1. 处理参数",
            primary,
            self.advanced_toggle,
            self.advanced,
            self.parameter_help,
            "### 2. 提交前检查",
            self.preflight_text,
            actions,
            pn.layout.Divider(),
            "### 3. 任务状态",
            task_header,
            self.status_text,
            self.progress,
            self.log_text,
            self.quality_section,
            self.save_section,
            sizing_mode="stretch_both",
        )

    def set_input(self, storage_label: str | None, input_path: str | Path | None) -> None:
        """Use a raw-file selection from the preview workflow."""
        self._storage_label = storage_label
        self._input_path = None if input_path is None else str(input_path)
        if storage_label is None or input_path is None:
            self.input_text.object = "尚未选择输入文件。请先在左侧选择并预览原始数据。"
        else:
            source = self.storage.resolve_raw_file(storage_label, self._input_path)
            if self.output_select.value != storage_label:
                self.output_select.value = storage_label
            self._replace_output_selector(source.parent)
            self._set_output_path(source.parent / "results")
            self.result_name.value = source.stem
            self.input_text.object = (
                f"**输入存储：** {escape(storage_label)}  \n"
                f"**原始文件：** `{escape(self._input_path)}`"
            )
        self._invalidate_preflight()

    def start_polling(self) -> None:
        """Start session-local status polling after the Bokeh document loads."""
        if self._periodic is None:
            self._periodic = pn.state.add_periodic_callback(self.poll, period=2_000)

    def poll(self) -> None:
        """Refresh the selected task status and bounded log tail."""
        if self._active_task_id is None:
            return
        try:
            task = self.tasks.get(self._active_task_id)
        except KeyError:
            self.status_text.object = "所选任务记录已不存在。"
            return
        status = _STATUS_LABELS[task.status]
        details = [
            f"**状态：** {status}",
            f"**任务 ID：** `{task.task_id}`",
            f"**输入：** `{escape(task.input_path)}`",
            f"**结果：** `{escape(task.result_path)}`",
        ]
        if task.error:
            details.append(f"**错误：** {escape(task.error)}")
        self.status_text.object = "  \n".join(details)
        self.progress.value = round(100 * max(0.0, min(1.0, task.progress)))
        if task.progress_message:
            self.status_text.object += f"  \n**阶段：** {escape(task.progress_message)}"
        self.log_text.value = self.tasks.read_log(task.task_id)
        if task.status == "succeeded" and self._quality_task_id != task.task_id:
            self._load_quality(task)
        elif task.status != "succeeded" and self._quality_task_id != task.task_id:
            self.quality_section.visible = False
            self.save_section.visible = False

    def _wire_callbacks(self) -> None:
        self.preset.param.watch(self._apply_preset, "value")
        self.output_select.param.watch(self._on_output_root_change, "value")
        self.use_current_directory.on_click(self._use_current_output_directory)
        self.save_button.on_click(self._save_result)
        self.confirm_discard.param.watch(
            lambda event: setattr(self.discard_button, "disabled", not event.new), "value"
        )
        self.discard_button.on_click(self._discard_result)
        self.advanced_toggle.param.watch(
            lambda event: setattr(self.advanced, "visible", event.new), "value"
        )
        parameters = tuple(self.parameter_widgets.values())
        for widget in parameters:
            widget.param.watch(self._invalidate_preflight, "value")
        self.confirm.param.watch(self._update_submit_state, "value")
        self.preflight_button.on_click(self._preflight)
        self.submit_button.on_click(self._submit)
        self.refresh_button.on_click(lambda _event: self._refresh_tasks())
        self.task_select.param.watch(self._select_task, "value")

    def _replace_output_selector(self, directory: Path | None = None) -> None:
        root = self.storage.root(self.output_select.value)
        if directory is None or not directory.is_relative_to(root.path):
            directory = root.path
        selector = pn.widgets.FileSelector(
            directory=str(directory),
            root_directory=str(root.path),
            file_pattern=_DIRECTORY_ONLY_PATTERN,
            only_files=False,
            show_hidden=False,
            size=8,
            sizing_mode="stretch_width",
        )
        selector.param.watch(self._on_output_selection, "value")
        self._output_selector = selector
        self.output_selector_area[:] = [selector]

    def _on_output_root_change(self, _event) -> None:
        root = self.storage.root(self.output_select.value)
        self._replace_output_selector(root.path)
        self._set_output_path(root.path / "results")

    def _on_output_selection(self, _event) -> None:
        if self._output_selector is None or len(self._output_selector.value) != 1:
            return
        selected = Path(self._output_selector.value[0])
        if selected.is_dir():
            self._set_output_path(selected)

    def _use_current_output_directory(self, _event=None) -> None:
        if self._output_selector is not None:
            self._set_output_path(Path(self._output_selector.directory))

    def _set_output_path(self, path: Path) -> None:
        resolved = self.storage.resolve_output_directory(self.output_select.value, path)
        self._output_path = resolved
        relative = resolved.relative_to(self.storage.root(self.output_select.value).path)
        display = "." if relative == Path(".") else str(relative)
        self.output_directory.object = (
            f"**已选结果目录：** `{escape(self.output_select.value)}/{escape(display)}`  "
            f"\n服务器路径：`{escape(str(resolved))}`"
        )

    def _apply_preset(self, event) -> None:
        params = ProcessingParameters.from_preset(
            event.new,
            self.defaults.ref_mz,
            mz_min=self.defaults.mz_min,
            mz_max=self.defaults.mz_max,
        )
        self.ms_peak_snr.value = params.ms_peak_snr_threshold
        self.cell_snr.value = params.cell_snr
        self.peak_snr.value = params.peak_snr
        self.max_zero_frac.value = params.max_zero_frac
        self._invalidate_preflight()

    def _parameters(self) -> ProcessingParameters:
        values = {key: widget.value for key, widget in self.parameter_widgets.items()}
        text = values["reference_mz"].strip()
        values["reference_mz"] = (
            tuple(float(v.strip()) for v in text.replace("，", ",").split(",")) if text else ()
        )
        return ProcessingParameters(**values)

    def _build_request(self) -> ProcessingRequest:
        if self._storage_label is None or self._input_path is None:
            raise ValueError("请先选择一个原始数据文件")
        result_name = Path(self._input_path).stem
        return ProcessingRequest(
            storage_label=self._storage_label,
            input_path=self._input_path,
            output_label=self.outputs.roots[0].label,
            result_name=result_name,
            defer_save=True,
            parameters=self._parameters(),
        )

    def _preflight(self, _event=None) -> None:
        try:
            request = self._build_request()
            plan = self.planner.preflight(request)
        except Exception as exc:
            self._request = None
            self.preflight_text.object = f"❌ **预检未通过：** {escape(str(exc))}"
            self.confirm.disabled = True
            self.submit_button.disabled = True
            return
        self._request = request
        warnings = ""
        if plan.warnings:
            warnings = "  \n**提示：** " + "；".join(escape(item) for item in plan.warnings)
        self.preflight_text.object = (
            "✅ **预检通过**  \n"
            f"输入大小：{_human_size(plan.input_size_bytes)}　"
            f"输出可用：{_human_size(plan.free_bytes)}  \n"
            "处理结果将先保存在任务临时区，完成网页查看后再决定是否永久保存。"
            f"{warnings}"
        )
        self.confirm.disabled = False
        self.confirm.value = False
        self._update_submit_state()

    def _submit(self, _event=None) -> None:
        if self._request is None or not self.confirm.value:
            return
        self.submit_button.loading = True
        try:
            task = self.tasks.submit(self._request)
        except Exception as exc:  # Panel callbacks must report task/preflight errors in-session.
            self.status_text.object = f"❌ **无法提交：** {escape(str(exc))}"
            return
        finally:
            self.submit_button.loading = False
        self._active_task_id = task.task_id
        self._reload_tasks(select_id=task.task_id)
        self.poll()
        self._invalidate_preflight()

    def _invalidate_preflight(self, _event=None) -> None:
        self._request = None
        self.confirm.value = False
        self.confirm.disabled = True
        self.submit_button.disabled = True
        self.preflight_text.object = "输入或参数已变化，请重新执行预检。"

    def _update_submit_state(self, _event=None) -> None:
        self.submit_button.disabled = (
            not background_tasks_supported() or self._request is None or not self.confirm.value
        )

    def _refresh_tasks(self) -> None:
        self._reload_tasks(select_id=self._active_task_id)
        self.poll()

    def _reload_tasks(self, select_id: str | None = None) -> None:
        tasks = self.tasks.list()
        if not tasks:
            self.task_select.param.update(options={"暂无任务": None}, value=None)
            return
        options = {
            f"{task.created_at[:19]} · {_STATUS_LABELS[task.status]} · {Path(task.input_path).name}": task.task_id
            for task in tasks
        }
        value = select_id if select_id in options.values() else tasks[0].task_id
        self.task_select.param.update(options=options, value=value)
        self._active_task_id = value
        self.poll()

    def _select_task(self, event) -> None:
        self._active_task_id = event.new
        self.poll()

    def _load_quality(self, task) -> None:
        try:
            result_path = self._safe_result_path(task.result_path)
            report = load_quality_report(result_path)
        except Exception as exc:
            self.quality_section.visible = True
            self.quality_summary.object = f"质量检查文件暂不可用：{escape(str(exc))}"
            self._configure_save(task)
            return
        summary = report.summary
        warning_text = ""
        if summary.embedding_warnings:
            warning_text = "  \n**嵌入提示：** " + "；".join(
                escape(item) for item in summary.embedding_warnings
            )
        self.quality_summary.object = (
            f"**细胞事件：** {summary.cell_count:,}　"
            f"**特征：** {summary.feature_count:,}　"
            f"**整体零值：** {summary.zero_fraction:.1%}　"
            f"**中位总强度：** {summary.median_total_intensity:.4g}　"
            f"**中位检出特征：** {summary.median_detected_features:.0f}{warning_text}"
        )
        self.intensity_plot.object = _histogram_figure(
            report.cells.get("total_intensity", []), "每细胞总强度", "总强度"
        )
        self.detection_plot.object = _detection_figure(report.features)
        self.pca_plot.object = _embedding_figure(report, "PCA1", "PCA2", "PCA")
        self.umap_plot.object = _embedding_figure(report, "UMAP1", "UMAP2", "UMAP")
        self.cell_table.object = report.cells.head(200)
        self.feature_table.object = report.features.head(200)
        for filename, download in self.artifact_downloads.items():
            path = result_path / filename
            download.file = str(path) if path.is_file() else None
            download.filename = f"{result_path.name}_{filename}"
            download.disabled = not path.is_file()
        self._quality_task_id = task.task_id
        self.quality_section.visible = True
        self._configure_save(task)

    def _configure_save(self, task) -> None:
        self.save_section.visible = True
        if task.exported_path:
            self.save_status.object = (
                f"✅ **完整结果已永久保存：** `{escape(task.exported_path)}`  \n"
                "质量 CSV、嵌入坐标和运行清单均位于该结果目录内。"
            )
            self.save_button.disabled = True
            self.confirm_discard.disabled = True
            self.discard_button.disabled = True
            return
        if task.discarded_at:
            self.save_status.object = "临时结果已按要求删除，不能再保存或下载。"
            self.save_button.disabled = True
            self.confirm_discard.disabled = True
            self.discard_button.disabled = True
            for download in self.artifact_downloads.values():
                download.disabled = True
                download.file = None
            return
        source = Path(task.input_path).resolve(strict=True)
        for root in self.storage.roots:
            if source.is_relative_to(root.path):
                if self.output_select.value != root.label:
                    self.output_select.value = root.label
                self._replace_output_selector(source.parent)
                self._set_output_path(source.parent / "results")
                break
        self.result_name.value = source.stem
        self.save_button.disabled = False
        self.confirm_discard.disabled = False
        self.discard_button.disabled = not self.confirm_discard.value
        self.save_status.object = "结果尚未永久保存；当前临时结果仍可在本页面查看和下载。"

    def _save_result(self, _event=None) -> None:
        if self._active_task_id is None or self._output_path is None:
            return
        result_name = self.result_name.value.strip() or Path(self._input_path or "result").stem
        self.save_button.loading = True
        try:
            task = self.tasks.save_result(
                self._active_task_id,
                self.storage,
                self.output_select.value,
                self._output_path,
                result_name,
                overwrite=self.overwrite.value,
            )
        except Exception as exc:
            self.save_status.object = f"❌ **保存失败：** {escape(str(exc))}"
            return
        finally:
            self.save_button.loading = False
        self._quality_task_id = None
        self._active_task_id = task.task_id
        self.poll()

    def _discard_result(self, _event=None) -> None:
        if self._active_task_id is None or not self.confirm_discard.value:
            return
        self.discard_button.loading = True
        try:
            task = self.tasks.discard_result(self._active_task_id)
        except Exception as exc:
            self.save_status.object = f"❌ **删除失败：** {escape(str(exc))}"
            return
        finally:
            self.discard_button.loading = False
        self._configure_save(task)

    def _safe_result_path(self, value: str) -> Path:
        result = Path(value).resolve(strict=True)
        if not result.is_dir() or not (result / ".meta").is_file():
            raise FileNotFoundError(f"不是完整的 scMM 结果目录：{result}")
        in_task_output = any(result.parent == root.path for root in self.outputs.roots)
        in_storage = any(result.parent.is_relative_to(root.path) for root in self.storage.roots)
        in_staging = (
            result.parent.name == "result" and result.parent.parent.parent == self.tasks.state_root
        )
        if not in_task_output and not in_storage and not in_staging:
            raise PermissionError("任务结果不在已配置的服务器目录范围内")
        return result


def _float_input(label: str, value: float, *, step: float):
    return pn.widgets.FloatInput(
        label=label,
        value=value,
        step=step,
        width=150,
        sizing_mode=None,
    )


def _human_size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _empty_figure(title: str) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(title=title)
    return _style_figure(figure)


def _histogram_figure(values, title: str, x_title: str) -> go.Figure:
    figure = go.Figure(go.Histogram(x=values, marker_color="#0F766E"))
    figure.update_layout(title=title, xaxis_title=x_title, yaxis_title="细胞数")
    return _style_figure(figure)


def _detection_figure(features) -> go.Figure:
    figure = go.Figure(
        go.Scattergl(
            x=features.get("mz", []),
            y=features.get("detection_rate", []),
            mode="markers",
            marker={"color": "#C2410C", "size": 6, "opacity": 0.7},
        )
    )
    figure.update_layout(title="特征检出率", xaxis_title="m/z", yaxis_title="检出率")
    figure.update_yaxes(range=[0, 1.02])
    return _style_figure(figure)


def _embedding_figure(report, x_name: str, y_name: str, title: str) -> go.Figure:
    if x_name not in report.embedding or y_name not in report.embedding:
        return _empty_figure(f"{title}（当前数据不可用）")
    totals = report.cells.set_index("cell_index")["total_intensity"]
    colors = report.embedding["cell_index"].map(totals)
    figure = go.Figure(
        go.Scattergl(
            x=report.embedding[x_name],
            y=report.embedding[y_name],
            mode="markers",
            marker={
                "color": colors,
                "colorscale": "Viridis",
                "showscale": True,
                "colorbar": {"title": "总强度"},
                "size": 6,
                "opacity": 0.75,
            },
            text=report.embedding["cell_index"],
            hovertemplate="cell=%{text}<br>x=%{x:.4g}<br>y=%{y:.4g}<extra></extra>",
        )
    )
    figure.update_layout(title=title, xaxis_title=x_name, yaxis_title=y_name)
    return _style_figure(figure)


def _style_figure(figure: go.Figure) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        margin={"l": 55, "r": 25, "t": 55, "b": 48},
        hovermode="closest",
    )
    figure.update_xaxes(showgrid=True, gridcolor="rgba(148,163,184,0.18)")
    figure.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,0.18)")
    return figure


__all__ = ["GuidedProcessingPanel"]
