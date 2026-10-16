"""Read-only production readiness probe against an explicitly configured loopback peer."""
# ruff: noqa: RUF001

import json
import math
import time
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def peer_readiness(url, token_file=None):
    if not url:
        return {"configured": False, "state": "unknown", "reason": "尚未配置生产只读检查地址。"}
    try:
        headers = {}
        if token_file:
            path = Path(token_file)
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError("Invalid operations credential")
            headers["Authorization"] = "Bearer " + path.read_text().strip()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(
            urllib.request.Request(url + "/api/v1/health", headers=headers), timeout=2
        ) as r:
            health = json.loads(r.read(65537))
        if not isinstance(health, dict) or health.get("frontend") != "vue":
            raise ValueError("Invalid health")
        with opener.open(
            urllib.request.Request(url + "/api/v1/runtime", headers=headers), timeout=2
        ) as r:
            runtime = json.loads(r.read(65537))
        if not isinstance(runtime, dict):
            raise ValueError("Invalid runtime")
        decision = runtime.get("update_readiness")
        if not isinstance(decision, dict):
            return {
                "configured": True,
                "state": "unknown",
                "reason": "生产仍为旧版，缺少页面登记协议；无法确认页面已关闭。",
                "legacy_unsaved": runtime.get("unsaved_workspaces"),
                "legacy_busy": runtime.get("busy_workspaces"),
            }
        if runtime.get("environment") != "prod":
            raise ValueError("Peer is not production")
        validate_decision(decision, runtime.get("monitor_protocol"))
        return {
            "configured": True,
            **decision,
            "reason": "来自生产实例的独立检查；开发页面状态不代表生产。",
        }
    except (OSError, ValueError, TypeError):
        return {
            "configured": True,
            "state": "unknown",
            "reason": "生产状态无法读取，请核对服务、协议与运维凭据。",
        }


def validate_decision(decision, protocol):
    if protocol != 1 or decision.get("state") not in {"ready", "blocked", "unknown"}:
        raise ValueError("Invalid readiness protocol")
    for key in ("checked_at", "sampled_at"):
        value = decision.get(key)
        if (
            type(value) not in {float, int}
            or not math.isfinite(value)
            or not -5 <= time.time() - value <= 15
        ):
            raise ValueError("Expired readiness")
    fields = (
        "active_pages",
        "unconfirmed_pages",
        "monitor_pages",
        "unsaved_workspaces",
        "busy_workspaces",
        "unconfirmed_workspaces",
        "active_tasks",
        "inflight_requests",
        "open_projects",
    )
    for key in fields:
        if type(decision.get(key)) is not int or decision[key] < 0:
            raise ValueError("Invalid readiness counts")
    if any(
        not isinstance(decision.get(k), list) or any(not isinstance(s, str) for s in decision[k])
        for k in ("blockers", "unknown")
    ):
        raise ValueError("Invalid readiness reasons")
    if decision["state"] == "ready" and (
        any(decision[k] for k in fields if k != "monitor_pages")
        or decision["blockers"]
        or decision["unknown"]
    ):
        raise ValueError("Inconsistent readiness")
