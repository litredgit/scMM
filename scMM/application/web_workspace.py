"""Explicit, isolated browser workspaces for HTTP clients.

No Panel objects or HTTP types live here. A revision guards every mutation;
project saves retain the existing cross-process manifest conflict check.
"""
# ruff: noqa: RUF001

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from copy import copy, deepcopy
from dataclasses import dataclass, field
from io import StringIO
from uuid import uuid4

import pandas as pd

from .projects import Project, ProjectStore
from .storage import StorageCatalog
from .web_analysis import AnalysisWorkflow
from .web_raw import RawWorkflow
from .web_results import ResultWorkflow
from .workbench import read_dataset

RESULT_PLOTS = {
    "differential": ("volcano", "violin"),
    "network": ("network_plot",),
    "supervised": ("roc", "pr", "calibration"),
    "shap": ("shap_plot",),
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
    """Invalidate reports and saved plots using the same dependencies as Panel."""
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


class WebWorkspaceService(RawWorkflow, AnalysisWorkflow, ResultWorkflow):
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
        with self._lock:
            self._prune()
            if len(self._workspaces) >= self.capacity:
                raise WorkspaceError(
                    "打开的工作区过多，请关闭不用的页面后重试。", code="capacity", status=503
                )
            workspace = BrowserWorkspace()
            self._workspaces[workspace.id] = workspace
        return self.view(workspace)

    @contextmanager
    def access(self, identity):
        with self._lock:
            workspace = self._workspaces.get(identity)
        if workspace is None:
            raise WorkspaceError(
                "工作区已关闭或服务已重启，请重新打开项目。", code="workspace_missing", status=404
            )
        with workspace.lock:
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
            try:
                yield workspace
            finally:
                workspace.touched = time.monotonic()

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

    def mutate(self, identity, revision, action, *, require_project=True):
        with self.access(identity) as workspace:
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

        return self.mutate(identity, revision, action, require_project=False)

    def open_project(self, identity, revision, path):
        def action(workspace):
            project = self.store.open(path)
            workspace.discard_views()
            workspace.project = project

        return self.mutate(identity, revision, action, require_project=False)

    def close_project(self, identity, revision):
        def action(workspace):
            workspace.discard_views()
            workspace.project = None

        return self.mutate(identity, revision, action, require_project=False)

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

        return self.mutate(identity, revision, action)

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

        return self.mutate(identity, revision, action)
