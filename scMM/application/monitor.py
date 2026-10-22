"""Independent, read-only sampling. Never touches matrices or workspace idle timers."""
# ruff: noqa: RUF001

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psutil

from .monitor_peer import peer_readiness
from .monitor_presence import update_readiness
from .monitor_store import MonitorStore


class MonitorService:
    def __init__(self, manager, auth, config, *, clock=time.time):
        self.manager, self.auth, self.clock = manager, auth, clock
        values = getattr(config, "values", {})
        if hasattr(config, "values") and not values.get("monitor_db"):
            raise RuntimeError("监控数据库未配置，请执行 scmm-admin init-monitor。")
        self.store = MonitorStore(values.get("monitor_db"))
        self.instance = uuid4().hex
        self.started = clock()
        self.environment = values.get("environment", "standalone")
        self.peer_url = values.get("monitor_peer_url")
        self.peer_token = values.get("monitor_peer_token_file")
        self.roots = list(
            dict.fromkeys([str(manager.store.root), *[str(r.path) for r in manager.results.roots]])
        )
        self.disk_roots = {"项目结果": str(manager.store.root)}
        self.disk_roots.update({r.label: str(r.path) for r in manager.storage.roots})
        for key in ("cache_root", "temp_root", "recycle_root"):
            if values.get(key):
                self.disk_roots[key] = values[key]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._active = {}
        self._requests = deque(maxlen=4096)
        self._legacy_pages = False
        self.registration_budget = {}
        self._snapshot = {
            "sampled_at": None,
            "resources": {},
            "disks": [],
            "tasks": [],
            "incomplete": ["等待首次采样。"],
            "production": {"state": "unknown", "reason": "等待生产检查。"},
        }
        self._cpu = None
        self._process_cpu = {}
        self._disk_at = self._peer_at = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, name="scmm-monitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=12)

    def _run(self):
        while not self._stop.is_set():
            start = time.monotonic()
            try:
                self.sample()
            except Exception:
                # Keep last values, but never present a failed sample as fresh evidence.
                with self._lock:
                    self._snapshot["incomplete"] = ["监控采样失败；保留上次数据，需核对服务。"]
            self._stop.wait(max(0.1, 5 - (time.monotonic() - start)))

    @staticmethod
    def probe(mode, payload):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("monitor_probe.py")), mode],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            check=True,
        )
        return json.loads(result.stdout)

    def workspaces(self):
        if not self.manager._lock.acquire(blocking=False):
            return [], ["工作区清单正在改变，尚未确认。"]
        try:
            items = list(self.manager._workspaces.values())
        finally:
            self.manager._lock.release()
        result = []
        for w in items:
            row = {
                "id": w.id,
                "user_id": w.owner_id,
                "busy": True,
                "unsaved": None,
                "project": None,
                "idle_seconds": max(0, time.monotonic() - w.touched),
            }
            if w.lock.acquire(blocking=False):
                try:
                    if w.closed:
                        continue
                    row.update(
                        busy=bool(w.preview_job and not w.preview_job["future"].done()),
                        unsaved=bool(w.project and w.project.unsaved),
                        project=w.project.manifest["name"] if w.project else None,
                    )
                finally:
                    w.lock.release()
            result.append(row)
        return result, []

    def note(self, principal, activity=False):
        try:
            self.store.seen(principal, activity)
        except Exception:
            with self._lock:
                self._snapshot["incomplete"] = ["监控数据库不可写。"]

    def begin(self, principal, path, page_id, *, closing=False):
        identity = uuid4().hex
        # Unsupported browser clients cannot silently become evidence of no open pages.
        if not self.store.observed(page_id, closing=closing):
            self._legacy_pages = True
        with self._lock:
            self._active[identity] = {
                "user_id": principal["id"],
                "kind": self.operation(path),
                "business": path.startswith("/api/v1/workspace/")
                and path != "/api/v1/workspace/maintenance/draft",
                "started_at": self.clock(),
            }
        return identity

    @staticmethod
    def operation(path):
        for fragment, label in (
            ("analysis", "分析"),
            ("preprocess", "预处理"),
            ("raw", "原始谱预览"),
            ("save", "保存"),
            ("extraction", "提取与审核"),
            ("download", "下载"),
        ):
            if fragment in path:
                return label
        return "工作区操作"

    def end(self, identity, status):
        with self._lock:
            item = self._active.pop(identity, None)
            if item:
                self._requests.append(
                    (self.clock(), max(0, self.clock() - item["started_at"]), status)
                )

    def sample(self):
        incomplete = []
        try:
            scan = self.probe("tasks", self.roots)
            if "error" in scan:
                raise ValueError()
            tasks = scan["tasks"]
            incomplete.extend(scan["incomplete"])
        except (OSError, ValueError, subprocess.SubprocessError):
            scan = {"pids": []}
            with self._lock:
                tasks = deepcopy(self._snapshot["tasks"])
            incomplete.append("任务扫描失败或超时；任务状态待确认。")
        now = self.clock()
        resource = {}
        try:
            cpu = psutil.cpu_times()
            total = sum(cpu) - getattr(cpu, "guest", 0) - getattr(cpu, "guest_nice", 0)
            idle = cpu.idle + getattr(cpu, "iowait", 0)
            if self._cpu:
                dt = total - self._cpu[0]
                resource["host_cpu"] = (
                    max(0, min(100, 100 * (1 - (idle - self._cpu[1]) / dt))) if dt > 0 else None
                )
            self._cpu = total, idle
            memory = psutil.virtual_memory()
            resource.update(
                host_memory=memory.percent,
                memory_available=memory.available,
                swap=psutil.swap_memory().percent,
            )
            if hasattr(os, "getloadavg"):
                resource["load1"] = os.getloadavg()[0]
            api = psutil.Process()
            processes = {p.pid: p for p in [api, *api.children(recursive=True)]}
            for pid in scan["pids"]:
                try:
                    processes[pid] = psutil.Process(pid)
                except psutil.Error:
                    incomplete.append("任务进程在采样时发生变化。")
            rss = cpu_percent = 0
            valid_cpu = False
            current_cpu = {}
            for process in processes.values():
                try:
                    # PID plus creation time prevents CPU deltas across PID reuse.
                    key = (process.pid, process.create_time())
                    times = process.cpu_times()
                    used = times.user + times.system
                    current_cpu[key] = used, now
                    old = self._process_cpu.get(key)
                    if old and now > old[1]:
                        cpu_percent += max(0, 100 * (used - old[0]) / (now - old[1]))
                        valid_cpu = True
                    rss += process.memory_info().rss
                except psutil.Error:
                    incomplete.append("部分服务进程资源不可读。")
            self._process_cpu = current_cpu
            resource.update(
                process_rss=rss,
                process_cpu=cpu_percent if valid_cpu else None,
                processes=len(processes),
            )
        except (psutil.Error, OSError):
            incomplete.append("系统资源暂时不可读。")
        with self._lock:
            disks, peer = deepcopy(self._snapshot["disks"]), deepcopy(self._snapshot["production"])
            requests = [r for r in self._requests if now - r[0] <= 300]
        resource.update(
            requests_5m=len(requests),
            errors_5m=sum(r[2] >= 500 for r in requests),
            latency_ms=sum(r[1] for r in requests) / len(requests) * 1000 if requests else None,
        )
        if now - self._disk_at >= 60:
            try:
                disks = self.probe("disks", self.disk_roots)
                self._disk_at = now
            except (OSError, ValueError, subprocess.SubprocessError):
                incomplete.append("存储容量检查失败或超时。")
        if (
            not isinstance(disks, list)
            or not disks
            or any(d.get("error") for d in disks)
            or now - self._disk_at > 90
        ):
            incomplete.append("存储状态不可用或检查已过期。")
        if now - self._peer_at >= 10:
            peer = peer_readiness(self.peer_url, self.peer_token)
            peer["observed_at"] = self.clock()
            self._peer_at = now
        if isinstance(disks, list):
            for disk in disks:
                if disk.get("free") is not None:
                    resource["disk_free:" + disk["label"]] = disk["free"]
        try:
            self.store.write_history(self.instance, resource)
        except Exception:
            incomplete.append("监控历史写入失败。")
        with self._lock:
            self._snapshot = {
                "sampled_at": self.clock(),
                "resources": resource,
                "disks": disks,
                "disks_at": self._disk_at,
                "tasks": tasks,
                "incomplete": incomplete,
                "production": peer,
            }

    def snapshot(self):
        with self._lock:
            result = deepcopy(self._snapshot)
            active = list(self._active.values())
        workspaces, incomplete = self.workspaces()
        if getattr(self.manager, "retention", None) is not None:
            retention_tasks, retention_error = self.manager.retention.runtime()
            result["tasks"].extend(retention_tasks)
            if retention_error:
                incomplete.append(retention_error)
        now = self.clock()
        users = self.auth.users()
        names = {u["id"]: u["username"] for u in users}
        admins = {u["id"] for u in users if u["role"] == "admin" and u["active"]}
        observations = self.store.accounts()
        pages = self.store.pages()
        for page in pages:
            state = (
                "connected"
                if page["instance"] == self.instance
                and now - page["seen"] <= 90
                and page["visibility"] != "suspended"
                else "unconfirmed"
            )
            # Any associated open/busy project remains a blocker even on the monitoring route.
            associated = next((w for w in workspaces if w["id"] == page["workspace_id"]), None)
            page.update(
                state=state,
                monitor_only=state == "connected"
                and page["route"] == "/admin/monitor"
                and page["user_id"] in admins
                and not (
                    associated
                    and (associated["project"] or associated["busy"] or associated["unsaved"])
                ),
                username=names.get(page["user_id"], "未登录"),
            )
            page.pop("workspace_id")
            page.pop("instance")
            page.pop("user_id")
        for collection in (workspaces, result["tasks"], active):
            for row in collection:
                row["username"] = names.get(row.pop("user_id", None), "未记录")
                # Task messages may contain paths, input filenames or reader diagnostics.
                row.pop("message", None)
        issues = result["incomplete"] + incomplete
        if self._legacy_pages:
            issues.append("观察到未登记页面的业务请求；无法确认旧页面均已关闭。")
        decision = update_readiness(
            pages=pages,
            workspaces=workspaces,
            tasks=result["tasks"],
            sampled_at=result["sampled_at"],
            now=now,
            incomplete=issues,
            inflight=len(active),
        )
        result.update(
            instance=self.instance,
            environment=self.environment,
            uptime=max(0, now - self.started),
            pages=pages,
            workspaces=workspaces,
            requests=active,
            update_readiness=decision,
            users=[
                {
                    **u,
                    "last_seen": observations.get(u["id"], {}).get("seen"),
                    "last_activity": observations.get(u["id"], {}).get("activity"),
                    "pages": sum(
                        p["username"] == u["username"] and p["state"] == "connected" for p in pages
                    ),
                }
                for u in users
            ],
        )
        # A cached green peer decision must expire when its probe stops succeeding.
        if now - result["production"].get("observed_at", 0) > 15 or (
            result["production"].get("state") == "ready"
            and any(now - result["production"].get(k, 0) > 15 for k in ("sampled_at", "checked_at"))
        ):
            result["production"].update(state="unknown", reason="生产检查已过期。")
        return result
