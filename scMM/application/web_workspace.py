"""Explicit, isolated browser workspaces for HTTP clients.

No frontend objects or HTTP types live here. A revision guards every mutation;
project saves retain the existing cross-process manifest conflict check.
"""
# ruff: noqa: RUF001

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from copy import deepcopy

from scMM.plugins._bundled import BUNDLED
from scMM.plugins._registry import MethodRegistry
from scMM.util.observations import observation_kind

from .annotation_evidence import AnnotationEvidenceWorkflow
from .identity import actor
from .projects import ProjectStore
from .storage import StorageCatalog
from .web_analysis import AnalysisWorkflow
from .web_ions import IonWorkflow
from .web_lipids import LipidWorkflow
from .web_projects import ProjectWorkflow
from .web_projects import prepare_mapping as prepare_mapping
from .web_projects import project_candidate as project_candidate
from .web_projects import sync_metadata as sync_metadata
from .web_raw import RawWorkflow
from .web_results import ResultWorkflow
from .workflows.assistant import AISummaryService
from .workflows.merge import MergeWorkflow
from .workflows.methods import MethodWorkflow
from .workflows.time import TimeWorkflow
from .workspace_state import BrowserWorkspace as BrowserWorkspace
from .workspace_state import WorkspaceError as WorkspaceError


class WebWorkspaceService(
    ProjectWorkflow,
    RawWorkflow,
    AnalysisWorkflow,
    ResultWorkflow,
    LipidWorkflow,
    AnnotationEvidenceWorkflow,
    IonWorkflow,
):
    def __init__(
        self,
        roots,
        result_roots,
        project_root,
        defaults,
        *,
        idle_seconds=3600,
        capacity=128,
        enabled_plugins=(),
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
        self.plugins = MethodRegistry(enabled_plugins)
        self._workspaces = {}
        self._lock = threading.RLock()
        self._project_openings = {}
        self._retention_operations = set()
        self._merge = MergeWorkflow(self)
        self._methods = MethodWorkflow(self)
        self._time = TimeWorkflow(self)

    def publish_ai(self, workspace):
        AISummaryService.publish(workspace)

    def ai_context(self, identity, user_id, page):
        with self._lock:
            workspace = self._workspaces.get(identity)
        return AISummaryService.context(workspace, user_id, page, self.idle_seconds)

    def merge_inspect(self, identity, revision, specification):
        return self._merge.merge_inspect(identity, revision, specification)

    def merge_preview(self, identity, revision, options):
        return self._merge.merge_preview(identity, revision, options)

    def merge_info(self, identity):
        return self._merge.merge_info(identity)

    def merge_preview_download(self, identity, token):
        return self._merge.merge_preview_download(identity, token)

    def merge_apply(self, identity, revision, token):
        return self._merge.merge_apply(identity, revision, token)

    def run_method(self, identity, revision, method_id, version, options, **selection):
        return self._methods.run_method(
            identity, revision, method_id, version, options, **selection
        )

    def method_result(self, identity, key, **options):
        return self._methods.method_result(identity, key, **options)

    def time_info(self, identity, **options):
        return self._time.time_info(identity, **options)

    def time_result(self, identity, key):
        return self._time.time_result(identity, key)

    def run_time(self, identity, revision, operation, options):
        return self._time.run_time(identity, revision, operation, options)

    def time_download(self, identity, key):
        return self._time.time_download(identity, key)

    def require_plugin(self, key):
        if key not in self.plugins.bundled:
            raise WorkspaceError(
                f"插件「{BUNDLED[key].label}」未启用。", code="plugin_disabled", status=409
            )

    def _prune(self):
        now = time.monotonic()
        jobs = []
        with self._lock:
            for identity, workspace in list(self._workspaces.items()):
                if now - workspace.touched <= self.idle_seconds or not workspace.lock.acquire(
                    blocking=False
                ):
                    continue
                try:
                    if now - workspace.touched > self.idle_seconds:
                        workspace.closed = True
                        workspace.project = None
                        jobs.append(workspace.detach_views())
                        self._workspaces.pop(identity, None)
                finally:
                    workspace.lock.release()
        from .cell_preview import stop_preview_job

        for job in jobs:
            if job is not None:
                stop_preview_job(job)

    def create(self):
        self._prune()
        with self._lock:
            if getattr(self, "maintenance_frozen", False):
                raise WorkspaceError(
                    "维护暂存已冻结，请等待服务恢复。", code="maintenance", status=503
                )
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

    @staticmethod
    def view(workspace):
        from .annotation_sources import review_sources

        project = workspace.project
        payload = None
        if project is not None:
            data = project.workspace.data
            payload = {
                "path": str(project.folder),
                "manifest": deepcopy(
                    {key: value for key, value in project.manifest.items() if key != "mz_lists"}
                ),
                "unsaved": project.unsaved,
                "annotation": review_sources(project),
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
                    "quantitation_available": data.n_obs > 0,
                    "observation_kind": observation_kind(data),
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
        if hasattr(self, "ion_jobs"):
            self.ion_jobs.shutdown()
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
