"""Process-isolated cell previews; workers never mutate the live UI project."""
# ruff: noqa: RUF001

from __future__ import annotations

import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .preview_cache import (
    file_identity,
    load_detection,
    prepare_shared_targets,
    reusable_preview,
    save_preview,
    signature,
)
from .processing import ProcessingParameters
from .project_batch import SHARED_FIELDS, preflight
from .projects import Project, child_path, write_json
from .raw_preview import RawPreviewService
from .storage import StorageCatalog, StorageRoot
from .tasks import utc_now


def initialize_ranges(project, service):
    """Derive automatic ranges on a candidate project before resolving shared features."""
    if not project.manifest.get("auto_ranges") or project.manifest.get("manual_parameters"):
        return
    for sample in project.samples:
        if (
            sample["parameters"] is not None
            or sample.get("auto_mz_range")
            or sample.get("result_only")
        ):
            continue
        summary = service.open(sample["storage"], sample["path"]).summary
        if summary.mz_min is not None and summary.mz_max is not None:
            sample["auto_mz_range"] = [
                math.floor(summary.mz_min / 10) * 10,
                math.ceil(summary.mz_max / 10) * 10,
            ]
            sample["range_initialized"] = True
            project.dirty = True


def run_preview(request, state_path):
    """Read, extract and persist a frozen request in a fresh interpreter."""
    state = {"created_at": request["created_at"], "pid": os.getpid()}

    def report(message, status="running"):
        write_json(state_path, {**state, "status": status, "message": message})

    def check_inputs():
        if any(file_identity(path) != identity for path, identity in request["inputs"].items()):
            raise ValueError("Input changed during preview; reopen the file")

    try:
        report("读取原始数据与检查参数")
        check_inputs()
        project = Project(Path(request["project_folder"]), deepcopy(request["manifest"]))
        catalog = StorageCatalog(StorageRoot(label, Path(path)) for label, path in request["roots"])
        service = RawPreviewService(catalog)
        sample = next(s for s in project.samples if s["id"] == request["sample_id"])
        catalog.resolve_raw_file(sample["storage"], sample["path"])
        parameters = dict(request["parameters"])
        targets = None
        if project.manifest["feature_strategy"] == "shared":
            initialize_ranges(project, service)
            batch = preflight(project, catalog)
            if (
                project.manifest.get("auto_ranges")
                and not project.manifest.get("manual_parameters")
                and sample["parameters"] is None
            ):
                parameters.update({key: batch["parameters"][key] for key in ("mz_min", "mz_max")})
            if any(parameters[key] != batch["parameters"][key] for key in SHARED_FIELDS):
                raise ValueError("共同特征参数已编辑，请先应用为项目默认再预览")
            report("建立或复用全项目共同特征")
            targets = prepare_shared_targets(project, batch)
        params = ProcessingParameters(**parameters)
        before = signature(sample["path"], params)
        cached = reusable_preview(project.folder, {**sample, "parameters": parameters}, targets)
        if cached:
            report("读取已验证的预览缓存")
            detection = load_detection(cached)
            artifact = sample["preview"]["artifact"]
        else:
            report("读取当前样本并完整提取细胞")
            preview = service.open(sample["storage"], sample["path"])
            detection = preview.cell_detection(params, targets=targets)
            report("写入预览缓存")
            artifact = save_preview(project, sample, preview, params, before)
        check_inputs()
        result = {
            "detection": detection,
            "artifact": artifact,
            "parameters": asdict(params),
            "reused": cached is not None,
            "ranges": {
                s["id"]: {key: s[key] for key in ("auto_mz_range", "range_initialized") if key in s}
                for s in project.samples
            },
        }
        report("预览计算完成，等待页面接收", "succeeded")
        return result
    except Exception as exc:
        report(str(exc), "failed")
        raise


def submit_preview(request):
    """Return a future immediately, with status visible to deployment idle checks.

    Each session allows one job. A fresh process releases raw spectra and native
    library memory on completion; no frontend objects cross the process boundary.
    """
    request = deepcopy(request)
    request["created_at"] = utc_now()
    folder = child_path(request["project_folder"], f"processing/preview-jobs/{uuid4().hex}")
    folder.mkdir(parents=True)
    state_path = folder / "state.json"
    write_json(folder / "request.json", request)
    state = {"created_at": request["created_at"], "status": "queued", "message": "等待启动"}
    write_json(state_path, state)
    pool = None

    def finished(future):
        try:
            if future.cancelled():
                write_json(state_path, {**state, "status": "stopped", "message": "会话已关闭"})
            elif (error := future.exception()) is not None:
                write_json(state_path, {**state, "status": "failed", "message": str(error)})
        finally:
            if pool is not None:
                pool.shutdown(wait=False)

    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        future = pool.submit(run_preview, request, state_path)
    except Exception as exc:
        if pool is not None:
            pool.shutdown(wait=False)
        write_json(state_path, {**state, "status": "failed", "message": str(exc)})
        raise
    future.add_done_callback(finished)
    return future, state_path
