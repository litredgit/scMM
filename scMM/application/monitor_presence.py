"""Conservative update decisions from explicitly observed browser and task state."""
# ruff: noqa: RUF001

import time


def update_readiness(*, pages, workspaces, tasks, sampled_at, now=None, incomplete=(), inflight=0):
    now = time.time() if now is None else now
    blockers, unknown = [], list(incomplete)
    ordinary = [p for p in pages if p["state"] == "connected" and not p["monitor_only"]]
    uncertain = [p for p in pages if p["state"] == "unconfirmed"]
    if ordinary:
        blockers.append(f"仍有 {len(ordinary)} 个活动页面（含后台标签页）。")
    if uncertain:
        unknown.append(f"{len(uncertain)} 个页面失联，尚未确认关闭。")
    busy = sum(w["busy"] for w in workspaces)
    unsaved = sum(w["unsaved"] is True for w in workspaces)
    uncertain_ws = sum(w["unsaved"] is None for w in workspaces)
    opened = sum(bool(w["project"]) for w in workspaces)
    if busy:
        blockers.append(f"{busy} 个工作区繁忙。")
    if unsaved:
        blockers.append(f"{unsaved} 个工作区有未保存修改。")
    if opened:
        blockers.append(f"{opened} 个工作区仍打开项目。")
    if uncertain_ws:
        unknown.append(f"{uncertain_ws} 个工作区状态待核实。")
    running = sum(t["status"] in {"queued", "running"} for t in tasks)
    if running:
        blockers.append(f"{running} 个任务待启动或运行中。")
    if inflight:
        blockers.append(f"{inflight} 个业务请求尚未完成。")
    if sampled_at is None or not -5 <= now - sampled_at <= 15:
        unknown.append("任务及工作区采样已过期。")
    return {
        "state": "blocked" if blockers else "unknown" if unknown else "ready",
        "checked_at": now,
        "sampled_at": sampled_at,
        "blockers": blockers,
        "unknown": unknown,
        "active_pages": len(ordinary),
        "monitor_pages": sum(p["monitor_only"] for p in pages),
        "unconfirmed_pages": len(uncertain),
        "unsaved_workspaces": unsaved,
        "busy_workspaces": busy,
        "unconfirmed_workspaces": uncertain_ws,
        "open_projects": opened,
        "active_tasks": running,
        "inflight_requests": inflight,
    }
