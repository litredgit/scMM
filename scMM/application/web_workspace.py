"""Explicit, isolated browser workspaces for HTTP clients.

No frontend objects or HTTP types live here. A revision guards every mutation;
project saves retain the existing cross-process manifest conflict check.
"""
# ruff: noqa: RUF001

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from copy import copy, deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
from uuid import uuid4

import pandas as pd

from .identity import actor
from .projects import Project, ProjectStore
from .storage import StorageCatalog
from .web_analysis import AnalysisWorkflow
from .web_lipids import LipidWorkflow
from .web_raw import RawWorkflow
from .web_results import ResultWorkflow
from .workbench import read_dataset

RESULT_PLOTS = {
    "differential": ("volcano", "violin"),
    "network": ("network_plot",),
    "supervised": ("roc", "pr", "calibration", "confusion"),
    "shap": ("shap_plot", "shap_beeswarm", "shap_waterfall", "shap_dependence"),
}


class WorkspaceError(RuntimeError):
    def __init__(self, message, *, code="conflict", status=409):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class BrowserWorkspace:
    id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    project: Project | None = None
    touched: float = field(default_factory=time.monotonic)
    closed: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)

    raw: dict | None = None
    preview_job: dict | None = None
    trash_plan: tuple | None = None
    owner_id: str | None = None
    # Published AI state has its own short lock; readers never take the data lock.
    ai_lock: threading.RLock = field(default_factory=threading.RLock)
    ai_snapshot: dict = field(default_factory=dict)
    ai_signature: tuple | None = None
    ai_running: str | None = None
    ai_completed: str | None = None
    ai_parameters: dict = field(default_factory=dict)
    ai_before_filter: dict = field(default_factory=dict)
    ai_generation: int = 0
    ai_project: object = None
    ai_dataset: str = ""
    ai_preview: object = None
    ai_batches: tuple = ()
    ai_tasks_unknown: bool = False
    ai_reviewed: set = field(default_factory=set)

    def discard_views(self):
        self.raw = None
        if self.preview_job:
            self.preview_job["future"].cancel()
            self.preview_job = None

    def check(self, revision):
        if revision != self.revision:
            raise WorkspaceError("页面状态已改变，请刷新当前状态后重试。", code="stale_revision")

    def require_project(self):
        if self.project is None:
            raise WorkspaceError("请先打开或新建项目。", code="project_required", status=400)
        return self.project


def project_candidate(project):
    """Copy mutable data/annotations before importing or synchronizing metadata."""
    candidate = copy(project)
    candidate.manifest = deepcopy(project.manifest)
    candidate.saved_reports = deepcopy(project.saved_reports)
    candidate.views = deepcopy(project.views)
    candidate.workspace = copy(project.workspace)
    candidate.workspace.results = dict(project.workspace.results)
    if project.workspace.data is not None:
        candidate.workspace.data = project.workspace.data.copy()
        candidate.workspace._original = project.workspace._original.copy()
    return candidate


def sync_metadata(project):
    """Invalidate reports and saved plots using their recorded data dependencies."""
    before = set(project.workspace.results)
    changed = project.workspace.sync_sample_metadata(
        project.samples,
        project.manifest.get("sample_mapping"),
        project.manifest.get("sample_column", "sample"),
    )
    if not changed:
        return
    stale = before - set(project.workspace.results)
    for name, report in list(project.saved_reports.items()):
        dependencies = {report.get("group_key"), report.get("label_key")}
        if dependencies & changed or (name in {"supervised", "shap"} and not dependencies - {None}):
            stale.add(name)
            project.saved_reports.pop(name, None)
    if "supervised" in stale:
        stale.add("shap")
        project.saved_reports.pop("shap", None)
    for name in stale:
        for figure in RESULT_PLOTS.get(name, ()):
            project.views.get("figures", {}).pop(figure, None)
    project.report_token = project.workspace.token


def prepare_mapping(project, storage_label):
    data = project.workspace.require_data()
    source = project.manifest.get("sample_column")
    if source not in data.obs:
        source = next(
            (key for key in ("sample", "sample_id", "source_file") if key in data.obs), None
        )
    if source is None:
        project.manifest.pop("sample_column", None)
        project.manifest.pop("sample_mapping", None)
        return
    project.manifest["sample_column"] = source
    names = data.obs[source].dropna().astype(str).unique().tolist()
    if not project.samples:
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
            project.samples.append(
                {
                    "id": uuid4().hex,
                    "name": name,
                    "path": "",
                    "storage": storage_label,
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
    matches = {sample["name"]: sample["id"] for sample in project.samples}
    # A newly imported dataset must not inherit a mapping from an unrelated import.
    project.manifest["sample_mapping"] = {name: matches[name] for name in names if name in matches}


class WebWorkspaceService(RawWorkflow, AnalysisWorkflow, ResultWorkflow, LipidWorkflow):
    def __init__(
        self, roots, result_roots, project_root, defaults, *, idle_seconds=3600, capacity=128
    ):
        self.store = ProjectStore(project_root)
        self.storage = StorageCatalog(roots)
        self.results = StorageCatalog(result_roots)
        from dataclasses import replace

        self.defaults = replace(
            defaults, processing=replace(defaults.processing, extraction_method="snr_v1")
        )
        self.idle_seconds = idle_seconds
        self.capacity = capacity
        self._workspaces = {}
        self._lock = threading.RLock()

    def _prune(self):
        now = time.monotonic()
        for identity, workspace in list(self._workspaces.items()):
            if now - workspace.touched <= self.idle_seconds or not workspace.lock.acquire(
                blocking=False
            ):
                continue
            try:
                # Recheck after taking the lock: another request may just have finished.
                if now - workspace.touched > self.idle_seconds:
                    workspace.closed = True
                    workspace.project = None
                    workspace.discard_views()
                    self._workspaces.pop(identity, None)
            finally:
                workspace.lock.release()

    def create(self):
        if getattr(self, "maintenance_frozen", False):
            raise WorkspaceError("维护暂存已冻结，请等待服务恢复。", code="maintenance", status=503)
        with self._lock:
            self._prune()
            if len(self._workspaces) >= self.capacity:
                raise WorkspaceError(
                    "打开的工作区过多，请关闭不用的页面后重试。", code="capacity", status=503
                )
            principal = actor.get()
            workspace = BrowserWorkspace(owner_id=principal["id"] if principal else None)
            self._workspaces[workspace.id] = workspace
        self.publish_ai(workspace)
        return self.view(workspace)

    @contextmanager
    def access(self, identity, *, operation=None):
        with self._lock:
            workspace = self._workspaces.get(identity)
        if workspace is None:
            raise WorkspaceError(
                "工作区已关闭或服务已重启，请重新打开项目。", code="workspace_missing", status=404
            )
        with workspace.lock:
            principal = actor.get()
            if principal is not None and workspace.owner_id != principal["id"]:
                raise WorkspaceError(
                    "工作区不存在或不属于当前账号。", code="workspace_missing", status=404
                )
            if workspace.closed or time.monotonic() - workspace.touched > self.idle_seconds:
                with self._lock:
                    self._workspaces.pop(identity, None)
                workspace.closed = True
                workspace.project = None
                workspace.discard_views()
                raise WorkspaceError(
                    "工作区已过期，请重新打开项目。", code="workspace_missing", status=404
                )
            workspace.touched = time.monotonic()
            with workspace.ai_lock:
                workspace.ai_running = operation
            try:
                yield workspace
            finally:
                self.publish_ai(workspace)
                with workspace.ai_lock:
                    workspace.ai_running = None
                workspace.touched = time.monotonic()

    def publish_ai(self, workspace):
        from .ai_summary import build_summary

        project = workspace.project
        state = project.workspace if project else None
        signature = (workspace.revision, state.token if state else None, workspace.closed)
        if signature == workspace.ai_signature:
            return
        # dataset_id distinguishes reopened/replaced data; never goes to the provider.
        project_identity = str(project.folder) if project else None
        dataset_identity = state.dataset_id if state else ""
        if workspace.ai_project != project_identity:
            workspace.ai_reviewed = set()
        if workspace.ai_project != project_identity or workspace.ai_dataset != dataset_identity:
            workspace.ai_parameters = {}
            workspace.ai_completed = None
            workspace.ai_before_filter = {}
        from .project_batch import batches

        tasks_unknown = False
        try:
            batch_paths = tuple(batches(project)) if project else ()
        except (OSError, ValueError, TypeError, AttributeError):
            batch_paths = ()
            tasks_unknown = True
        try:
            summary = build_summary(workspace)
            summary["summary_available"] = True
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            # Imported legacy metadata must never break a scientific transaction.
            # Fail closed: no raw exception, metadata or partial result is published.
            summary = {
                "published_at": datetime.now(UTC).isoformat(),
                "workspace_version": workspace.revision,
                "summary_available": False,
                "results": {},
                "counts": {},
            }
        if state and state.data is not None:
            frozen = state.data.uns.get("project_batch", {})
            if isinstance(frozen, dict) and isinstance(frozen.get("source"), str):
                workspace.ai_reviewed.add(frozen["source"])
        with workspace.ai_lock:
            workspace.ai_generation += 1
            workspace.ai_snapshot = summary
            workspace.ai_signature = signature
            workspace.ai_project = project_identity
            workspace.ai_dataset = dataset_identity
            workspace.ai_batches = batch_paths
            workspace.ai_tasks_unknown = tasks_unknown
            workspace.ai_preview = (
                workspace.preview_job["future"] if workspace.preview_job else None
            )

    def ai_context(self, identity, user_id, page):
        from .ai_config import AIError

        with self._lock:
            workspace = self._workspaces.get(identity)
        if workspace is None:
            raise AIError("工作区已关闭或过期，请重新打开项目。", 404, "workspace_missing")
        with workspace.ai_lock:
            if (
                workspace.owner_id != user_id
                or workspace.closed
                or time.monotonic() - workspace.touched > self.idle_seconds
            ):
                raise AIError("工作区不存在、已过期或不属于当前账号。", 404, "workspace_missing")
            summary = deepcopy(workspace.ai_snapshot)
            generation = workspace.ai_generation
            running = workspace.ai_running
            batch_paths, reviewed = workspace.ai_batches, set(workspace.ai_reviewed)
            preview = workspace.ai_preview
            task_unknown = workspace.ai_tasks_unknown
        # Only registered batch state files, outside the scientific lock. No raw
        # reading or analysis is performed to answer a question.
        awaiting_review = False
        if preview and not preview.done():
            running = running or "preview"
        for path in batch_paths:
            try:
                from .project_batch import read_batch

                status = read_batch(path)["status"]
                if status in {"queued", "running"}:
                    running = running or "extract"
                elif (
                    status in {"completed", "stopped", "failed", "interrupted"}
                    and str(path) not in reviewed
                ):
                    awaiting_review = True
                elif status not in {
                    "queued",
                    "running",
                    "completed",
                    "stopped",
                    "failed",
                    "interrupted",
                }:
                    task_unknown = True
            except (OSError, ValueError, KeyError):
                task_unknown = True
        return {
            "page": page,
            "running_operation": running,
            "awaiting_review": awaiting_review,
            "task_status_unknown": task_unknown,
            "summary": summary,
            "snapshot_version": generation,
            "read_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def view(workspace):
        project = workspace.project
        payload = None
        if project is not None:
            data = project.workspace.data
            payload = {
                "path": str(project.folder),
                "manifest": deepcopy(project.manifest),
                "unsaved": project.unsaved,
                "presentation": deepcopy(project.views.get("legend_positions", {})),
                "legend_orders": deepcopy(project.views.get("legend_orders", {})),
                "dataset": None
                if data is None
                else {
                    "id": project.workspace.dataset_id,
                    "revision": project.workspace.revision,
                    "cells": data.n_obs,
                    "features": data.n_vars,
                    "observation_columns": list(map(str, data.obs.columns)),
                    "source": project.workspace.source,
                },
            }
        return {"workspace_id": workspace.id, "revision": workspace.revision, "project": payload}

    def current(self, identity):
        with self.access(identity) as workspace:
            return self.view(workspace)

    def close(self, identity):
        with self.access(identity) as workspace:
            workspace.closed = True
            workspace.project = None
            workspace.discard_views()
            with self._lock:
                self._workspaces.pop(identity, None)

    def shutdown(self):
        with self._lock:
            workspaces = list(self._workspaces.values())
        for workspace in workspaces:
            with workspace.lock:
                workspace.closed = True
                workspace.project = None
                workspace.discard_views()
        with self._lock:
            self._workspaces.clear()

    def mutate(self, identity, revision, action, *, require_project=True, operation="update"):
        with self.access(identity, operation=operation) as workspace:
            workspace.check(revision)
            if require_project:
                workspace.require_project()
            action(workspace)
            workspace.revision += 1
            return self.view(workspace)

    def create_project(self, identity, revision, name):
        def action(workspace):
            project = self.store.create(name, self.defaults)
            workspace.discard_views()
            workspace.project = project

        return self.mutate(
            identity, revision, action, require_project=False, operation="create_project"
        )

    def open_project(self, identity, revision, path):
        def action(workspace):
            project = self.store.open(path)
            workspace.discard_views()
            workspace.project = project

        return self.mutate(
            identity, revision, action, require_project=False, operation="open_project"
        )

    def close_project(self, identity, revision):
        def action(workspace):
            workspace.discard_views()
            workspace.project = None

        return self.mutate(
            identity, revision, action, require_project=False, operation="close_project"
        )

    def edit_project(self, identity, revision, name, description):
        def action(workspace):
            if not name.strip():
                raise ValueError("项目名称不能为空。")
            workspace.project.manifest.update(name=name.strip(), description=description)
            workspace.project.dirty = True

        return self.mutate(identity, revision, action)

    def add_samples(self, identity, revision, root, paths):
        def action(workspace):
            candidate = project_candidate(workspace.project)
            candidate.add_files(self.storage, root, paths)
            candidate.validate_samples()
            workspace.project = candidate

        return self.mutate(identity, revision, action)

    def _update_samples(self, identity, revision, update):
        def action(workspace):
            candidate = project_candidate(workspace.project)
            update(candidate)
            candidate.validate_samples()
            sync_metadata(candidate)
            candidate.dirty = True
            workspace.project = candidate

        return self.mutate(identity, revision, action)

    def edit_samples(self, identity, revision, edits):
        def update(candidate):
            lookup = {sample["id"]: sample for sample in candidate.samples}
            ids = [edit["id"] for edit in edits]
            if len(ids) != len(set(ids)) or set(ids) - lookup.keys():
                raise ValueError("样本 ID 重复或不属于当前项目。")
            for edit in edits:
                sample = lookup[edit["id"]]
                sample.update(
                    {key: str(value).strip() for key, value in edit.items() if key != "id"}
                )
                sample["metadata_unresolved"] = []

        return self._update_samples(identity, revision, update)

    def remove_samples(self, identity, revision, ids):
        def update(candidate):
            if set(ids) - {sample["id"] for sample in candidate.samples}:
                raise ValueError("请选择当前项目中的样本。")
            candidate.manifest["samples"] = [
                sample for sample in candidate.samples if sample["id"] not in ids
            ]

        return self._update_samples(identity, revision, update)

    def import_csv(self, identity, revision, text):
        def update(candidate):
            frame = pd.read_csv(StringIO(text.lstrip("\ufeff")), dtype=str, keep_default_na=False)
            if (
                "name" not in frame
                or set(frame.columns) - {"name", "group", "subject", "batch"}
                or frame.name.duplicated().any()
            ):
                raise ValueError("CSV 必须含唯一 name 列，仅支持 name/group/subject/batch。")
            samples = {sample["name"]: sample for sample in candidate.samples}
            if set(frame.name) - samples.keys():
                raise ValueError("CSV 中存在项目未添加的样本名称。")
            for _, row in frame.iterrows():
                sample = samples[row["name"]]
                sample.update(row.to_dict())
                sample["metadata_unresolved"] = [
                    key for key in sample.get("metadata_unresolved", []) if key not in frame.columns
                ]

        return self._update_samples(identity, revision, update)

    def relocate(self, identity, revision, sample_id, root, path):
        def update(candidate):
            resolved = self.storage.resolve_raw_file(root, path)
            sample = next((s for s in candidate.samples if s["id"] == sample_id), None)
            if sample is None:
                raise ValueError("请选择当前项目中的样本。")
            if any(s["id"] != sample_id and s["path"] == str(resolved) for s in candidate.samples):
                raise ValueError("该文件已关联其他样本。")
            sample.update(path=str(resolved), storage=root, result_only=False)
            for key in ("preview", "auto_mz_range", "range_initialized"):
                sample.pop(key, None)

        return self._update_samples(identity, revision, update)

    def import_dataset(self, identity, revision, root, path, trust_pickle):
        if trust_pickle and actor.get() is not None:
            raise WorkspaceError(
                "网页不支持导入可执行 pickle，请离线转换为 H5AD。", code="unsafe_import", status=403
            )

        def action(workspace):
            data = read_dataset(self.results, root, path, trust_pickle=trust_pickle)
            candidate = project_candidate(workspace.project)
            candidate.workspace.replace(data, source=str(self.results.resolve(root, path)))
            prepare_mapping(candidate, self.storage.roots[0].label)
            candidate.validate_samples()
            sync_metadata(candidate)
            candidate.saved_reports = {}
            candidate.views.pop("figures", None)
            candidate.dirty = True
            workspace.project = candidate

        return self.mutate(identity, revision, action, operation="import_dataset")

    def mapping(self, identity, source_key=None):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            data = project.workspace.require_data()
            source_key = source_key or project.manifest.get("sample_column", "")
            if source_key and source_key not in data.obs:
                raise ValueError("样本来源字段不存在。")
            names = (
                []
                if not source_key
                else data.obs[source_key].dropna().astype(str).unique().tolist()
            )
            mapping = project.manifest.get("sample_mapping", {})
            valid_ids = {sample["id"] for sample in project.samples}
            rows = []
            for name in names:
                selected = mapping.get(name, "")
                if "sample_id" in data.obs:
                    linked = (
                        data.obs.loc[data.obs[source_key].astype(str).eq(name), "sample_id"]
                        .astype(str)
                        .unique()
                        .tolist()
                    )
                    if len(linked) == 1 and linked[0] in valid_ids:
                        selected = linked[0]
                rows.append({"value": name, "sample_id": selected if selected in valid_ids else ""})
            return {
                "source_key": source_key,
                "columns": list(map(str, data.obs.columns)),
                "rows": rows,
            }

    def map_samples(self, identity, revision, source_key, mapping):
        def update(candidate):
            data = candidate.workspace.require_data()
            if source_key not in data.obs:
                raise ValueError("样本来源字段不存在。")
            names = set(data.obs[source_key].dropna().astype(str))
            if set(mapping) - names or set(mapping.values()) - {s["id"] for s in candidate.samples}:
                raise ValueError("映射包含未知的结果样本或项目样本。")
            candidate.manifest.update(sample_column=source_key, sample_mapping=mapping)
            # Explicit remapping must take precedence over previous sample IDs.
            for dataset in (candidate.workspace.data, candidate.workspace._original):
                if "sample_id" not in dataset.obs:
                    dataset.obs["sample_id"] = ""
                values = dataset.obs[source_key].astype(str)
                selected = values.isin(mapping)
                dataset.obs.loc[selected, "sample_id"] = values.loc[selected].map(mapping)

        return self._update_samples(identity, revision, update)

    def save(self, identity, revision):
        def action(workspace):
            try:
                self.store.save(workspace.project)
            except RuntimeError as exc:
                if "another session" in str(exc):
                    raise WorkspaceError(
                        "项目已被其他会话保存，请重新打开后操作。", code="save_conflict"
                    ) from exc
                raise

        return self.mutate(identity, revision, action, operation="save")
