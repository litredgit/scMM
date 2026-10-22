"""Bounded, deployment-first preservation of independent browser workspaces."""
# ruff: noqa: RUF001

import json
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from .projects import write_json as _write_json
from .workspace_state import WorkspaceError

GRACE_SECONDS = 60
SNAPSHOT_SECONDS = 120
MAX_SNAPSHOT_BYTES = 512 * 1024**2
MAX_TOTAL_BYTES = 1024**3


def write_json(path, value):
    _write_json(path, value)
    path.chmod(0o600)


def control_path(path):
    return any(part in path for part in ("/maintenance/", "/presence/", "/auth/")) or path in {
        "/api/v1/health",
        "/api/v1/runtime",
    }


def persistent_request(path, method):
    """Unknown mutations remain protected; only known in-memory computations may end."""
    return (
        method not in {"GET", "HEAD", "OPTIONS"}
        and not control_path(path)
        and not any(
            part in path
            for part in ("/workspace/analysis/", "/workspace/preprocess", "/workspace/raw/")
        )
    )


def prepare(service):
    with service._control_lock:
        if service.request and service.request.get("policy") != "deployment":
            raise ValueError("请先取消已有的严格维护，再启动部署维护。")
        if not service.request:
            service.request = {
                "id": uuid4().hex,
                "started": time.time(),
                "policy": "deployment",
                "deadline": time.time() + GRACE_SECONDS,
            }
            service.deployment = {"phase": "collecting", "preserved": [], "failed": []}
            # Prevent retention admission and workspace creation; existing saves may finish.
            service.manager.maintenance_frozen = True
            service.recovery.discard_pointer()
            service.monitor.auth.audit(None, "deployment_prepare", service.monitor.environment)
        return service.status()


def checkpoint(service):
    with service._control_lock:
        if not service.request or service.request.get("policy") != "deployment":
            raise ValueError("请先启动部署维护。")
        if time.time() < service.request["deadline"]:
            raise ValueError("维护通知宽限期尚未结束。")
        if service.deployment["phase"] != "collecting":
            return service.status()
        if any(service._deployment_requests.values()):
            raise ValueError("正式写入或其他受保护请求仍在执行，请等待安全结束。")
        retention = getattr(service.manager, "retention", None)
        if retention is not None and any(retention.runtime()):
            raise ValueError("自动保留任务尚未到达安全停止点。")
        service.deployment["phase"] = "snapshotting"
        service.deployment["snapshot_deadline"] = time.time() + SNAPSHOT_SECONDS
        service._deployment_stop = threading.Event()
        threading.Thread(
            target=_snapshot, args=(service,), daemon=True, name="scmm-deployment-snapshot"
        ).start()
        return service.status()


def _snapshot(service):
    manager = service.manager
    # A busy inventory must not consume an unbounded maintenance deadline.
    if not manager._lock.acquire(timeout=1):
        with service._control_lock:
            service.deployment["failed"].append({"reason": "workspace_inventory_busy"})
        return
    try:
        items = list(manager._workspaces.values())
        pages = dict(getattr(manager, "maintenance_pages", {}))
    finally:
        manager._lock.release()
    with service._control_lock:
        service.deployment["expected"] = [{"id": w.id, "owner_id": w.owner_id} for w in items]
    used_bytes = 0
    # Preserve standalone page state even when there are no scientific workspaces.
    for workspace in items or [None]:
        with service._control_lock:
            if service._deployment_stop.is_set():
                return
        identity = workspace.id if workspace else None
        owner = workspace.owner_id if workspace else None
        candidate = SimpleNamespace(
            _lock=threading.RLock(),
            _workspaces={identity: workspace} if workspace else {},
            maintenance_pages={
                k: v for k, v in pages.items() if workspace is None or k[0] == owner
            },
            snapshot_byte_limit=min(MAX_SNAPSHOT_BYTES, MAX_TOTAL_BYTES - used_bytes),
        )
        try:
            manifest = service.recovery.snapshot(candidate, publish=False)
            used_bytes += sum(
                p.stat().st_size for p in (service.recovery.root / manifest["id"]).iterdir()
            )
            result = {"id": identity, "owner_id": owner, "checkpoint": manifest["id"]}
            failed = False
        except Exception:
            # Avoid paths/scientific contents in operational reports.
            result = {"id": identity, "owner_id": owner, "reason": "snapshot_failed"}
            failed = True
        with service._control_lock:
            if service._deployment_stop.is_set():
                return  # A timed-out encoder can never publish a late recovery pointer.
            service.deployment["failed" if failed else "preserved"].append(result)
    with service._control_lock:
        service.deployment["encoding_finished"] = True


def finish(service):
    """Called during status polling; never waits for a scientific codec or data lock."""
    report = service.deployment
    if not report or report["phase"] != "snapshotting":
        return
    if not report.get("encoding_finished") and time.time() < report["snapshot_deadline"]:
        return
    service._deployment_stop.set()
    timed_out = not report.get("encoding_finished", False)
    report.update(timed_out=timed_out, finished=time.time())
    if timed_out:
        handled = {r.get("id") for r in report["preserved"] + report["failed"]}
        report["failed"].extend(
            {**r, "reason": "snapshot_deadline_exceeded"}
            for r in report.get("expected", [])
            if r["id"] not in handled
        )
        if not report.get("expected") and not report["failed"]:
            report["failed"].append({"reason": "snapshot_deadline_exceeded"})
    payload = {"checkpoints": report["preserved"], "report": {**report, "phase": "ready"}}
    sealed = service.recovery.cipher.encrypt(json.dumps(payload).encode()).decode()
    write_json(service.recovery.root / "current.json", {"deployment": sealed})
    write_json(service.recovery.root / "deployment-report.json", {**report, "phase": "ready"})
    service.monitor.auth.audit(
        None,
        "deployment_checkpoint",
        f"preserved={len(report['preserved'])}; failed={len(report['failed'])}",
    )
    report["phase"] = "ready"


def restore(service):
    service.restoration_report = {}
    pointer = service.recovery.root / "current.json"
    if not pointer.exists():
        return
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
        if "deployment" not in value:
            payload = {"checkpoints": [{"checkpoint": value["id"], "legacy": True}]}
        else:
            payload = json.loads(service.recovery.cipher.decrypt(value["deployment"].encode()))
        results, lock = [], threading.Lock()
        stopped = threading.Event()

        def work():
            for record in payload["checkpoints"]:
                if stopped.is_set():
                    return
                candidate = SimpleNamespace(
                    _lock=threading.RLock(),
                    _workspaces={},
                    storage=service.manager.storage,
                    store=SimpleNamespace(recovered_folders=set()),
                    publish_ai=service.manager.publish_ai,
                )
                temporary = service.recovery.root / ("restore-" + uuid4().hex + ".json")
                try:
                    write_json(temporary, {"id": record["checkpoint"]})
                    service.recovery.restore(candidate, pointer=temporary, consume=False)
                    result = (record, candidate, None)
                except Exception:
                    result = (record, None, "restore_failed")
                finally:
                    temporary.unlink(missing_ok=True)
                with lock:
                    if not stopped.is_set():
                        results.append(result)

        thread = threading.Thread(target=work, daemon=True, name="scmm-deployment-restore")
        thread.start()
        thread.join(SNAPSHOT_SECONDS)
        stopped.set()
        report = {
            "restored": [],
            "failed": list(payload.get("report", {}).get("failed", [])),
            "timed_out": thread.is_alive(),
        }
        with lock:
            completed = list(results)
        for record, candidate, error in completed:
            if error:
                report["failed"].append({**record, "reason": error})
                continue
            service.manager._workspaces.update(candidate._workspaces)
            if hasattr(service.manager, "store"):
                service.manager.store.recovered_folders.update(candidate.store.recovered_folders)
            pages = getattr(service.manager, "maintenance_pages", {})
            pages.update(getattr(candidate, "maintenance_pages", {}))
            service.manager.maintenance_pages = pages
            report["restored"].extend(
                {**record, "id": w.id, "owner_id": w.owner_id}
                for w in candidate._workspaces.values()
            )
        finished = {r["checkpoint"] for r, _, _ in completed}
        report["failed"].extend(
            {**r, "reason": "restore_deadline_exceeded"}
            for r in payload["checkpoints"]
            if r["checkpoint"] not in finished
        )
        write_json(service.recovery.root / "deployment-restore.json", report)
        service.restoration_report = report
        pointer.replace(service.recovery.root / "restored.json")
    except Exception:
        # A corrupt/incompatible temporary session must never prevent service startup.
        service.manager._workspaces.clear()
        pointer.replace(service.recovery.root / ("rejected-" + uuid4().hex + ".json"))
        write_json(
            service.recovery.root / "deployment-restore.json", {"failed": ["invalid_recovery"]}
        )
        service.restoration_report = {"invalid_recovery": True}


def admit(service, path, method):
    if control_path(path) or not path.startswith("/api/"):
        return None
    with service._control_lock:
        if service.request and service.request.get("policy") == "deployment":
            phase = service.deployment["phase"]
            saving = path == "/api/v1/workspace/project/save" and method == "POST"
            saving = saving or (path == "/api/v1/workspace/analysis/settings" and method == "PUT")
            if phase != "collecting" or (method not in {"GET", "HEAD", "OPTIONS"} and not saving):
                raise WorkspaceError(
                    "服务正在部署维护，请稍后重新连接。", code="maintenance", status=503
                )
        identity = uuid4().hex
        service._deployment_requests[identity] = persistent_request(path, method)
        return identity
