"""Admin maintenance state, frontend draft handshake and deferred service actions."""

# ruff: noqa: RUF001
import json
import subprocess
import threading
import time
from copy import deepcopy
from functools import wraps
from pathlib import Path
from uuid import uuid4

from .recovery import RecoveryStore

MAX_STANDALONE_DRAFTS_PER_USER = 16


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._control_lock:
            return method(self, *args, **kwargs)

    return call


class Maintenance:
    def __init__(self, manager, monitor, config):
        self._control_lock = threading.RLock()
        self.manager, self.monitor, self.config = manager, monitor, config
        self.recovery = RecoveryStore(config)
        self.request = None
        self.completed = None
        self.acks = {}
        self.closure_review = None
        self.deployment = None
        self._strict_snapshotting = False
        self._deployment_requests = {}
        from .deployment_maintenance import restore

        restore(self)

    def control_state(self):
        with self._control_lock:
            return {
                "request": deepcopy(self.request),
                "completed": deepcopy(self.completed),
                "frozen": getattr(self.manager, "maintenance_frozen", False),
                "acknowledged": list(self.acks),
                "deployment": deepcopy(self.deployment),
                "restoration": deepcopy(self.restoration_report),
            }

    def status(self):
        with self._control_lock:
            completed = self.completed
            value = self.control_state()
        value["verified_checkpoint"] = bool(completed) and self.verified_checkpoint(
            expected=completed
        )
        value.pop("frozen")
        try:
            value["last_operation"] = json.loads(
                (self.recovery.root / "last-operation.json").read_text()
            )
        except FileNotFoundError:
            value["last_operation"] = None
        return value

    @_serialized
    def prepare(self):
        if self.request:
            return self.status()
        self.request = {"id": uuid4().hex, "started": time.time()}
        self.acks = {}
        self.closure_review = None
        return self.status()

    @_serialized
    def review_closed_pages(self):
        from .maintenance_closure import review_closed_pages

        return review_closed_pages(self)

    @_serialized
    def confirm_closed_pages(self, review_id, reason, actor):
        from .maintenance_closure import confirm_closed_pages

        return confirm_closed_pages(self, review_id, reason, actor)

    @_serialized
    def acknowledge(self, page_id, workspace, state, nonce, owner_id=None, tab_id=None):
        if not self.request or nonce != self.request["id"]:
            raise ValueError("维护请求已改变。")
        page = next(
            (p for p in self.monitor.store.pages(include_ids=True) if p["id"] == page_id), None
        )
        if not page or page["user_id"] != owner_id:
            raise ValueError("页面身份已改变，请重新登记后重试。")
        if (
            self.completed
            or self._strict_snapshotting
            or (self.deployment and self.deployment["phase"] != "collecting")
        ):
            raise ValueError("会话已冻结，请取消维护后重新收集。")
        if workspace is not None:
            workspace.client_state = state
        else:
            with self.manager._lock:
                pages = getattr(self.manager, "maintenance_pages", {})
                if (owner_id, tab_id) not in pages and sum(
                    owner == owner_id for owner, _ in pages
                ) >= MAX_STANDALONE_DRAFTS_PER_USER:
                    raise ValueError("独立页面草稿已达 16 页上限，已有标签页仍可更新。")
                pages[(owner_id, tab_id)] = state
                self.manager.maintenance_pages = pages
        self.acks[page_id] = workspace.id if workspace is not None else "standalone"

    def checkpoint(self):
        with self._control_lock:
            if self._strict_snapshotting:
                raise ValueError("正在验证会话暂存。")
            self._strict_snapshotting = True
        try:
            return self._checkpoint()
        finally:
            with self._control_lock:
                self._strict_snapshotting = False

    def _checkpoint(self):
        with self._control_lock:
            if self.request and self.request.get("policy") == "deployment":
                raise ValueError("部署维护请使用限时暂存入口。")
            if not self.request:
                raise ValueError("请先发起维护收集。")
            acknowledged = set(self.acks)
            was_frozen = bool(self.completed)
        # No lost/legacy page is silently considered safe.
        readiness = self.monitor.snapshot()
        pages = self.monitor.store.pages(include_ids=True)
        missing = [p["id"] for p in pages if p["id"] not in acknowledged]
        if missing:
            raise ValueError("仍有页面未完成草稿暂存：" + ", ".join(missing))
        if (
            readiness.get("incomplete")
            or readiness.get("update_readiness", {}).get("unknown")
            or time.time() - (readiness.get("sampled_at") or 0) > 15
        ):
            raise ValueError(
                "维护监控证据不完整或已过期："
                + "；".join(
                    readiness.get("incomplete", [])
                    + readiness.get("update_readiness", {}).get("unknown", [])
                )
            )
        if any(r.get("business") for r in readiness.get("requests", [])):
            raise ValueError("仍有业务请求正在执行。")
        tasks = readiness.get("tasks", [])
        if any(t.get("status") in {"queued", "running"} for t in tasks):
            raise ValueError("仍有任务正在运行。")
        with self.manager._lock:
            self.manager.maintenance_frozen = True
        try:
            completed = self.recovery.snapshot(self.manager)
        except BaseException:
            with self.manager._lock:
                self.manager.maintenance_frozen = was_frozen
            raise
        with self._control_lock:
            self.completed = completed
        return self.status()

    @_serialized
    def cancel(self):
        if self._strict_snapshotting:
            raise ValueError("正在验证会话暂存，请等待完成。")
        if self.deployment and self.deployment["phase"] != "collecting":
            raise ValueError("部署暂存已开始，请由发布流程完成重启。")
        if self.deployment and hasattr(self.manager, "ion_jobs"):
            with self.manager.ion_jobs.lock:
                self.manager.ion_jobs.closed = False
        self.manager.maintenance_frozen = False
        self.request = None
        self.completed = None
        self.acks = {}
        self.closure_review = None
        self.deployment = None
        (self.recovery.root / "current.json").unlink(missing_ok=True)

    def verified_checkpoint(self, *, expected=None):
        with self._control_lock:
            completed = self.completed
            if (
                not completed
                or (expected is not None and completed is not expected)
                or not getattr(self.manager, "maintenance_frozen", False)
            ):
                return False
        pages = self.monitor.store.pages(include_ids=True)
        with self._control_lock:
            return self.completed is completed and all(p["id"] in self.acks for p in pages)

    def execute(self, action, version=None, *, deployment_first=False):
        with self._control_lock:
            completed = self.completed
            if self._strict_snapshotting:
                raise ValueError("正在验证会话暂存，请等待完成。")
        if not deployment_first and (
            completed is None or not self.verified_checkpoint(expected=completed)
        ):
            raise ValueError("请先完成全部会话暂存验证。")
        environment = self.config.values.get("environment")
        if environment not in {"dev", "prod"}:
            raise ValueError("仅支持配置好的开发/生产服务。")
        repository = Path(__file__).resolve().parents[2]
        if action == "update":
            approved = self.recovery.root / "approved.json"
            versions = json.loads(approved.read_text()) if approved.exists() else []
            if not version or version not in versions:
                raise ValueError("请选择已经验收/授权发布的版本。")
            remote_ref = "origin/main" if environment == "prod" else "origin/dev"
            expected = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", remote_ref], text=True
            ).strip()
            if version != expected:
                raise ValueError("只允许更新当前环境远端分支中已经批准的版本。")
        command = [
            str(repository / ".venv/bin/python"),
            "-m",
            "scMM.application.maintenance_runner",
            str(self.config.path),
            action,
        ]
        if version:
            command.extend(["--version", version])
        if deployment_first:
            command.append("--deployment-first")
        else:
            command.extend(["--strict-checkpoint", completed["id"]])
        subprocess.run(
            [
                "systemd-run",
                "--user",
                "--collect",
                "--unit=scmm-maintenance-" + uuid4().hex[:12],
                "--on-active=3s",
                *command,
            ],
            check=True,
            capture_output=True,
        )
        return {
            "scheduled": True,
            "action": action,
            "checkpoint": completed["id"] if completed else None,
        }
