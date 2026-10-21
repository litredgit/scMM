"""Publish immutable AI summaries and read them without the scientific lock."""
# ruff: noqa: RUF001

import time
from copy import deepcopy
from datetime import UTC, datetime


class AISummaryWorkflow:
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
