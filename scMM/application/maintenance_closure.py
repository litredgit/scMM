"""Explicit, scoped administrator attestations; never discard workspace state."""
# ruff: noqa: RUF001

import time
from uuid import uuid4

LIFETIME = 300


def _evidence(service):
    monitor = service.monitor
    pages = monitor.store.pages(include_ids=True)
    now = monitor.clock()
    unknown = [
        page
        for page in pages
        if page["instance"] != monitor.instance
        or now - page["seen"] > 90
        or page["visibility"] == "suspended"
    ]
    return {
        "instance": monitor.instance,
        "legacy_generation": monitor._legacy_generation,
        "legacy": monitor._legacy_pages,
        "known_ids": sorted(page["id"] for page in pages),
        "unknown": sorted(unknown, key=lambda page: page["id"]),
    }


def _ready(service):
    if not service.request or service.completed:
        raise ValueError("请先收集维护会话；冻结后的状态不能另行确认关闭。")


def review_closed_pages(service):
    _ready(service)
    with service.monitor._lock, service.monitor.store._lock:
        evidence = _evidence(service)
        review = {
            "id": uuid4().hex,
            "created": time.monotonic(),
            "nonce": service.request["id"],
            "evidence": evidence,
        }
        service.closure_review = review
    return {
        "review_id": review["id"],
        "expires_in_seconds": LIFETIME,
        "unconfirmed_pages": len(evidence["unknown"]),
        "legacy_requests": evidence["legacy"],
        "active_pages": len(evidence["known_ids"]) - len(evidence["unknown"]),
        "scope": "仅确认本轮失联页面和既有未登记请求已关闭；保留全部服务端工作区，仍须验证维护恢复包。",
    }


def confirm_closed_pages(service, review_id, reason, actor):
    _ready(service)
    review = service.closure_review
    # One attempt consumes the review; an expired/new heartbeat needs a new review.
    service.closure_review = None
    if (
        not review
        or review["id"] != review_id
        or review["nonce"] != service.request["id"]
        or not 0 <= time.monotonic() - review["created"] <= LIFETIME
    ):
        raise ValueError("关闭审阅已失效，请重新读取失联记录。")
    if not reason.strip() or len(reason) > 200:
        raise ValueError("须记录明确的页面关闭依据（最多 200 字）。")
    monitor = service.monitor
    with monitor._lock, monitor.store._lock:
        current = _evidence(service)
        if current != review["evidence"]:
            raise ValueError("页面或未登记请求已改变，请重新核对；不会沿用旧关闭确认。")
        if any(item["business"] for item in monitor._active.values()):
            raise ValueError("仍有业务请求执行，请等待结束后重新审阅。")
        # Record the explicit assertion before changing evidence. If audit storage
        # fails, no lease or unknown state is cleared.
        monitor.auth.audit(
            actor,
            "maintenance_closed_pages",
            f"{monitor.environment}; pages={len(current['unknown'])}; "
            f"legacy={current['legacy']}; reason={reason.strip()}",
        )
        with monitor.store.connect() as db:
            for page in current["unknown"]:
                changed = db.execute(
                    "UPDATE pages SET closed=? WHERE id=? AND closed IS NULL AND seen=?",
                    (monitor.clock(), page["id"], page["seen"]),
                ).rowcount
                if changed != 1:
                    raise ValueError("页面证据已改变，关闭确认未应用。")
        monitor._legacy_pages = False
        for page in current["unknown"]:
            service.acks.pop(page["id"], None)
    return {
        "confirmed_pages": len(current["unknown"]),
        "legacy_cleared": current["legacy"],
        "requires_checkpoint": True,
    }
