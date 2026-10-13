"""Raw spectra, frozen cell previews and persistent extraction/review for HTTP."""
# ruff: noqa: RUF001

import json
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

import plotly.express as px
import plotly.graph_objects as go

from scMM.plot.presentation import style_figure
from scMM.plot.raw import _peak_preserving_downsample, cell_detection_figure

from .cell_preview import initialize_ranges, submit_preview
from .preview_cache import file_identity
from .processing import ProcessingParameters
from .project_batch import (
    batches,
    preflight,
    read_batch,
    reviewed_dataset,
    stop_after_current,
    submit,
)
from .projects import sample_parameters
from .raw_preview import RawPreviewService
from .web_support import figure_view, table_view


def validated_parameters(values):
    try:
        result = asdict(ProcessingParameters(**values))
        if result["extraction_method"] != "snr_v1":
            raise ValueError("网页新提取仅支持 snr，请在第二步检查并应用 SNR 参数。")
        return result
    except TypeError as exc:
        raise ValueError(f"提取参数不合法：{exc}") from exc


class RawWorkflow:
    def edit_parameters(
        self,
        identity,
        revision,
        parameters,
        sample_id=None,
        *,
        strategy=None,
        merge_ppm=None,
        auto_ranges=None,
        cell_type=None,
    ):
        def action(workspace):
            project = workspace.require_project()
            values = validated_parameters(parameters)
            if sample_id:
                sample = self.sample(project, sample_id)
                sample.update(parameters=values, manual_parameters=True)
            else:
                project.manifest.update(parameters=values, manual_parameters=True)
            if strategy is not None:
                project.manifest["feature_strategy"] = strategy
            if merge_ppm is not None:
                project.manifest["feature_merge_ppm"] = merge_ppm
            if auto_ranges is not None:
                project.manifest["auto_ranges"] = auto_ranges
            if cell_type is not None:
                project.manifest["cell_type"] = cell_type
            project.dirty = True

        return self.mutate(identity, revision, action)

    @staticmethod
    def sample(project, sample_id):
        sample = next((s for s in project.samples if s["id"] == sample_id), None)
        if sample is None:
            raise ValueError("请选择当前项目中的样本。")
        return sample

    def parameters(self, identity, sample_id=None):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            return sample_parameters(
                project, self.sample(project, sample_id) if sample_id else None
            )

    def clear_parameters(self, identity, revision, sample_id):
        def action(workspace):
            self.sample(workspace.project, sample_id)["parameters"] = None
            workspace.project.dirty = True

        return self.mutate(identity, revision, action)

    def raw_open(self, identity, revision, sample_id):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            sample = self.sample(project, sample_id)
            if sample.get("result_only"):
                raise ValueError("请先重新定位此样本的原始文件。")
            preview = RawPreviewService(self.storage).open(sample["storage"], sample["path"])
            # Keep only one raw source per workspace; native resources are bounded.
            workspace.raw = {"sample_id": sample_id, "preview": preview, "frames": {}}
            if (
                not sample.get("range_initialized")
                and sample["parameters"] is None
                and not project.manifest.get("manual_parameters")
            ):
                import math

                summary = preview.summary
                if summary.mz_min is not None and summary.mz_max is not None:
                    sample.update(
                        auto_mz_range=[
                            math.floor(summary.mz_min / 10) * 10,
                            math.ceil(summary.mz_max / 10) * 10,
                        ],
                        range_initialized=True,
                    )
                    project.dirty = True
            workspace.revision += 1
            return {
                "workspace": self.view(workspace),
                "value": {
                    "summary": asdict(preview.summary),
                    "parameters": sample_parameters(project, sample),
                },
            }

    def scan_catalog(self, identity, sample_id, ms_level):
        with self.access(identity) as workspace:
            sample = self.sample(workspace.require_project(), sample_id)
            if not workspace.raw or workspace.raw["sample_id"] != sample_id:
                raise ValueError("请先打开当前样本。")
            preview = workspace.raw["preview"]
            if preview.open_identity != file_identity(sample["path"]):
                raise ValueError("原始文件已改变，请重新打开。")
            frame = preview.total_ion_chromatogram(ms_level=ms_level)
            return {"indices": frame.scan_index.tolist(), "times": frame.rt_seconds.tolist()}

    def raw_frame(self, workspace, sample_id, kind, options):
        project = workspace.require_project()
        sample = self.sample(project, sample_id)
        if not workspace.raw or workspace.raw["sample_id"] != sample_id:
            raise ValueError("请先打开当前样本。")
        preview = workspace.raw["preview"]
        if (
            preview.open_identity != file_identity(sample["path"])
            or str(preview.path) != sample["path"]
        ):
            raise ValueError("原始文件已改变，请重新打开。")
        if kind == "single":
            frame, detail = preview.single_spectrum(options["scan_index"])
        else:
            detail = {}
            common = {"ms_level": options["ms_level"], "rt_range": options.get("rt_range")}
            if kind == "tic":
                frame = preview.total_ion_chromatogram(**common)
            elif kind == "eic":
                frame = preview.extracted_ion_chromatograms(
                    options["references"], ppm_tolerance=options["ppm"], **common
                )
            else:
                spectrum = {
                    "mz_range": options["mz_range"],
                    "normalize": options["normalize"],
                    **common,
                }
                frame = (
                    preview.binned_spectrum(bins=options["bins"], **spectrum)
                    if options["fast"]
                    else preview.summed_spectrum(
                        resolution_200=options["resolution"],
                        points_per_fwhm=options["points_per_fwhm"],
                        **spectrum,
                    )
                )
        workspace.raw["frames"][kind] = frame
        return frame, detail

    def raw_plot(self, identity, sample_id, kind, options):
        with self.access(identity) as workspace:
            frame, detail = self.raw_frame(workspace, sample_id, kind, options)
            x = "mz" if "mz" in frame else "rt_seconds"
            figure = go.Figure()
            groups = (
                frame.groupby("reference_mz", sort=False)
                if "reference_mz" in frame
                else [("", frame)]
            )
            for name, group in groups:
                group = group.reset_index(drop=True)
                shown = _peak_preserving_downsample(group, 30000, "intensity")
                figure.add_scattergl(
                    x=shown[x], y=shown.intensity, name=str(name) or kind.upper(), mode="lines"
                )
            figure.update_layout(
                title={
                    "tic": "总离子流 TIC",
                    "eic": "提取离子流 EIC",
                    "sum": "合并谱",
                    "single": "单扫描谱",
                }[kind],
                xaxis_title="m/z" if x == "mz" else "RT（秒）",
                yaxis_title="强度",
            )
            return {
                "figure": figure_view(style_figure(figure)),
                "table": table_view(frame),
                "detail": detail,
            }

    def start_preview(self, identity, revision, sample_id, parameters):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            if workspace.preview_job and not workspace.preview_job["future"].done():
                raise ValueError("已有细胞预览正在运行。")
            sample = self.sample(project, sample_id)
            if not workspace.raw or workspace.raw["sample_id"] != sample_id:
                raise ValueError("请先打开当前样本。")
            values = validated_parameters(parameters)
            selected = (
                project.samples if project.manifest["feature_strategy"] == "shared" else [sample]
            )
            inputs = {
                s["path"]: file_identity(self.storage.resolve_raw_file(s["storage"], s["path"]))
                for s in selected
                if not s.get("result_only")
            }
            if inputs.get(sample["path"]) != workspace.raw["preview"].open_identity:
                raise ValueError("原始文件已改变，请重新打开。")
            request = {
                "project_folder": str(project.folder),
                "manifest": deepcopy(project.manifest),
                "sample_id": sample_id,
                "parameters": values,
                "roots": [(r.label, str(r.path)) for r in self.storage.roots],
                "inputs": inputs,
            }
            future, state_path = submit_preview(request)
            workspace.revision += 1
            workspace.preview_job = {
                "id": uuid4().hex,
                "future": future,
                "state_path": state_path,
                "revision": workspace.revision,
                "project_folder": project.folder,
                "sample_id": sample_id,
                "inputs": inputs,
            }
            return {
                "workspace": self.view(workspace),
                "value": self.preview_status_unlocked(workspace),
            }

    @staticmethod
    def preview_status_unlocked(workspace):
        job = workspace.preview_job
        if job is None:
            return None
        state = json.loads(job["state_path"].read_text(encoding="utf-8"))
        if job["future"].done():
            state["status"] = "failed" if job["future"].exception() else "ready"
        return {**state, "id": job["id"], "revision": job["revision"]}

    def preview_status(self, identity):
        with self.access(identity) as workspace:
            return self.preview_status_unlocked(workspace)

    def collect_preview(self, identity, revision, job_id):
        with self.access(identity) as workspace:
            workspace.check(revision)
            job = workspace.preview_job
            project = workspace.require_project()
            if (
                not job
                or job["id"] != job_id
                or job["revision"] != revision
                or project.folder != job["project_folder"]
            ):
                raise ValueError("样本或参数已改变，旧预览不再适用，请重新预览。")
            if not job["future"].done():
                raise ValueError("预览尚未完成。")
            result = job["future"].result()
            if any(file_identity(p) != expected for p, expected in job["inputs"].items()):
                raise ValueError("原始文件已改变，请重新预览。")
            detection = result["detection"]
            figure = figure_view(cell_detection_figure(detection))
            for sample in project.samples:
                sample.update(result["ranges"].get(sample["id"], {}))
            self.sample(project, job["sample_id"])["preview"] = {
                "parameters": result["parameters"],
                "artifact": result["artifact"],
                "confirmed": False,
            }
            project.dirty = True
            workspace.revision += 1
            workspace.raw["frames"]["cells"] = detection.traces
            workspace.preview_job = None
            return {
                "workspace": self.view(workspace),
                "value": {
                    "figure": figure,
                    "table": table_view(detection.traces),
                    "parameters": result["parameters"],
                    "reused": result["reused"],
                    "cell_count": detection.cell_count,
                },
            }

    @staticmethod
    def require_snr(project):
        for sample in project.samples:
            if sample_parameters(project, sample)["extraction_method"] != "snr_v1":
                raise ValueError(
                    f"样本 {sample['name']} 仍使用 legacy 参数；请在第二步应用 snr 参数后再启动新批次。"
                )

    def extraction_preflight(self, identity, revision):
        from .web_workspace import project_candidate

        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            self.require_snr(candidate)
            initialize_ranges(candidate, RawPreviewService(self.storage))
            return preflight(candidate, self.storage)

    def extraction_batches(self, identity):
        with self.access(identity) as workspace:
            return [{"path": str(p), **read_batch(p)} for p in batches(workspace.require_project())]

    @staticmethod
    def batch_path(project, path):
        match = next((p for p in batches(project) if str(p) == path), None)
        if match is None:
            raise ValueError("批次不属于当前项目。")
        return match

    def start_extraction(self, identity, revision, retry_path=None):
        from .web_workspace import project_candidate

        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            self.require_snr(candidate)
            initialize_ranges(candidate, RawPreviewService(self.storage))
            preflight(candidate, self.storage)
            if retry_path:
                self.batch_path(candidate, retry_path)
            if any(read_batch(p)["status"] in {"queued", "running"} for p in batches(candidate)):
                raise ValueError("当前项目已有运行中的提取批次。")
            # Save is an explicit part of starting extraction. If process creation fails,
            # keep the now-saved project and revision in sync with disk.
            self.store.save(candidate)
            workspace.project = candidate
            workspace.revision += 1
            try:
                path = submit(candidate, self.storage, retry_path=retry_path)
            except Exception as exc:
                from .web_workspace import WorkspaceError

                raise WorkspaceError(
                    f"输入配置已保存，但批次未启动：{exc}", code="extraction_not_started"
                ) from exc
            return {"workspace": self.view(workspace), "value": {"path": str(path)}}

    def stop_extraction(self, identity, revision, path):
        def action(workspace):
            stop_after_current(self.batch_path(workspace.project, path))

        return self.mutate(identity, revision, action)

    def review_extraction(self, identity, revision, path, ids, *, compare=False):
        from .web_workspace import project_candidate, sync_metadata

        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            path = self.batch_path(project, path)
            data = reviewed_dataset(path, ids)
            if compare:
                from scMM.analysis.quality import quality_metrics

                qc = quality_metrics(data)["cell"]
                figures = [
                    figure_view(style_figure(px.box(qc, x="sample", y=key, points=False)))
                    for key in ("total_intensity", "detected_features")
                ]
                return {
                    "workspace": self.view(workspace),
                    "value": {"figures": figures, "cells": data.n_obs, "features": data.n_vars},
                }
            candidate = project_candidate(project)
            candidate.workspace.replace(data, source=str(path))
            sync_metadata(candidate)
            candidate.saved_reports = {}
            candidate.views.pop("figures", None)
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": None}
