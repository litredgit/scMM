"""Browser workspace state and errors; storage/ownership stay in the service."""

# ruff: noqa: RUF001
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

from .projects import Project


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
