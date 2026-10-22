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

from .identity import actor
from .projects import ProjectStore
from .storage import StorageCatalog
from .web_ai import AISummaryWorkflow
from .web_analysis import AnalysisWorkflow
from .web_lipids import LipidWorkflow
from .web_projects import ProjectWorkflow
from .web_projects import prepare_mapping as prepare_mapping
from .web_projects import project_candidate as project_candidate
from .web_projects import sync_metadata as sync_metadata
from .web_raw import RawWorkflow
from .web_results import ResultWorkflow
from .workspace_state import BrowserWorkspace as BrowserWorkspace
from .workspace_state import WorkspaceError as WorkspaceError


class WebWorkspaceService(
    ProjectWorkflow, AISummaryWorkflow, RawWorkflow, AnalysisWorkflow, ResultWorkflow, LipidWorkflow
):
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
        self._project_openings = {}
        self._retention_operations = set()

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
