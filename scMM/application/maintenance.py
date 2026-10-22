"""Admin maintenance state, frontend draft handshake and deferred service actions."""

# ruff: noqa: RUF001
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from .recovery import RecoveryStore


class Maintenance:
    def __init__(self, manager, monitor, config):
        self.manager, self.monitor, self.config = manager, monitor, config
        self.recovery = RecoveryStore(config)
        self.request = None
        self.completed = None
        self.acks = {}
        self.recovery.restore(manager)

    def status(self):
        return {
            "request": self.request,
            "completed": self.completed,
            "acknowledged": list(self.acks),
            "last_operation": json.loads((self.recovery.root / "last-operation.json").read_text())
            if (self.recovery.root / "last-operation.json").exists()
            else None,
        }

    def prepare(self):
        if self.request:
            return self.status()
        self.request = {"id": uuid4().hex, "started": time.time()}
        self.acks = {}
        return self.status()

    def acknowledge(self, page_id, workspace, state, nonce, owner_id=None, tab_id=None):
        if not self.request or nonce != self.request["id"]:
            raise ValueError("维护请求已改变。")
        page = next(
            (p for p in self.monitor.store.pages(include_ids=True) if p["id"] == page_id), None
        )
        if not page or page["user_id"] != owner_id:
            raise ValueError("页面身份已改变，请重新登记后重试。")
        if self.completed:
            raise ValueError("会话已冻结，请取消维护后重新收集。")
        if workspace is not None:
            workspace.client_state = state
        else:
            pages = getattr(self.manager, "maintenance_pages", {})
            pages[(owner_id, tab_id)] = state
            self.manager.maintenance_pages = pages
        self.acks[page_id] = workspace.id if workspace is not None else "standalone"

    def checkpoint(self):
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

    def cancel(self):
        self.manager.maintenance_frozen = False
        self.request = None
        self.completed = None
        self.acks = {}
        (self.recovery.root / "current.json").unlink(missing_ok=True)

    def verified_checkpoint(self):
        if not self.completed or not getattr(self.manager, "maintenance_frozen", False):
            return False
        return all(p["id"] in self.acks for p in self.monitor.store.pages(include_ids=True))

    def execute(self, action, version=None):
        if not self.verified_checkpoint():
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
        return {"scheduled": True, "action": action, "checkpoint": self.completed["id"]}
