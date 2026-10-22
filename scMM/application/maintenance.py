"""Admin maintenance state, frontend draft handshake and deferred service actions."""

# ruff: noqa: RUF001
import json
import subprocess
import threading
import time
from functools import wraps
from pathlib import Path
from uuid import uuid4

from .recovery import RecoveryStore


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
        self._deployment_requests = {}
        from .deployment_maintenance import restore

        restore(self)

    @_serialized
    def status(self):
        from .deployment_maintenance import finish

        finish(self)
        return {
            "request": self.request,
            "completed": self.completed,
            "acknowledged": list(self.acks),
            "deployment": self.deployment,
            "restoration": self.restoration_report,
            "last_operation": json.loads((self.recovery.root / "last-operation.json").read_text())
            if (self.recovery.root / "last-operation.json").exists()
            else None,
        }

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
        if self.completed or (self.deployment and self.deployment["phase"] != "collecting"):
            raise ValueError("会话已冻结，请取消维护后重新收集。")
        if workspace is not None:
            workspace.client_state = state
        else:
            pages = getattr(self.manager, "maintenance_pages", {})
            pages[(owner_id, tab_id)] = state
            self.manager.maintenance_pages = pages
        self.acks[page_id] = workspace.id if workspace is not None else "standalone"

    @_serialized
    def checkpoint(self):
        if self.request and self.request.get("policy") == "deployment":
            raise ValueError("部署维护请使用限时暂存入口。")
        if not self.request:
            raise ValueError("请先发起维护收集。")
        # No lost/legacy page is silently considered safe.
        readiness = self.monitor.snapshot()
        pages = self.monitor.store.pages(include_ids=True)
        missing = [p["id"] for p in pages if p["id"] not in self.acks]
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
            self.completed = self.recovery.snapshot(self.manager)
            self.manager.maintenance_frozen = True
        return self.status()

    @_serialized
    def cancel(self):
        if self.deployment and self.deployment["phase"] != "collecting":
            raise ValueError("部署暂存已开始，请由发布流程完成重启。")
        self.manager.maintenance_frozen = False
        self.request = None
        self.completed = None
        self.acks = {}
        self.closure_review = None
        self.deployment = None
        (self.recovery.root / "current.json").unlink(missing_ok=True)

    @_serialized
    def verified_checkpoint(self):
        if not self.completed or not getattr(self.manager, "maintenance_frozen", False):
            return False
        return all(p["id"] in self.acks for p in self.monitor.store.pages(include_ids=True))

    @_serialized
    def execute(self, action, version=None, *, deployment_first=False):
        if not deployment_first and not self.verified_checkpoint():
            raise ValueError("请先完成全部会话暂存验证。")
        environment = self.config.values.get("environment")
        if environment not in {"dev", "prod"}:
            raise ValueError("仅支持配置好的开发/生产服务。")
        unit = "scmm-dev.service" if environment == "dev" else "scmm-ui.service"
        if action == "restart":
            command = ["systemctl", "--user", "restart", unit]
        else:
            approved = self.recovery.root / "approved.json"
            versions = json.loads(approved.read_text()) if approved.exists() else []
            if not version or version not in versions:
                raise ValueError("请选择已经验收/授权发布的版本。")
            repository = Path(__file__).resolve().parents[2]
            expected = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "origin/main"], text=True
            ).strip()
            if version != expected:
                raise ValueError("只允许更新远端 main 中已经批准的版本。")
            command = [
                str(repository / ".venv/bin/python"),
                str(repository / "scripts/scmm_env.py"),
                "update",
                environment,
            ]
        repository = Path(__file__).resolve().parents[2]
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
            "checkpoint": self.completed["id"] if self.completed else None,
        }
