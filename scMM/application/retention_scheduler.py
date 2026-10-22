"""Opt-in, serial retention cycles with persistent policies and interruption records."""
# ruff: noqa: RUF001

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .retention import _safe, retention_plan
from .retention_cleanup import cleanup_plan, execute_cleanup


class RetentionCancelled(RuntimeError):
    pass


class RetentionScheduler:
    def __init__(self, manager, auth, *, clock=time.time, path=None):
        self.manager, self.auth, self.clock = manager, auth, clock
        self.path = (
            Path(path) if path is not None else manager.store.root / ".scmm-retention.sqlite3"
        )
        _safe(self.path)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._active = None
        self.error = None
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS policies (
                    project TEXT PRIMARY KEY, revision TEXT NOT NULL,
                    enabled INTEGER NOT NULL, owner TEXT NOT NULL,
                    options TEXT NOT NULL, interval_minutes INTEGER NOT NULL,
                    next_at REAL NOT NULL, updated_at REAL NOT NULL, project_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, revision TEXT NOT NULL,
                    user_id TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
                    status TEXT NOT NULL, message TEXT NOT NULL, entry TEXT);
            """)
            expected = {
                "policies": {
                    "project",
                    "revision",
                    "enabled",
                    "owner",
                    "options",
                    "interval_minutes",
                    "next_at",
                    "updated_at",
                    "project_id",
                },
                "runs": {
                    "id",
                    "project",
                    "revision",
                    "user_id",
                    "started_at",
                    "finished_at",
                    "status",
                    "message",
                    "entry",
                },
            }
            for table, columns in expected.items():
                if {row["name"] for row in db.execute(f"PRAGMA table_info({table})")} != columns:
                    raise ValueError("自动保留数据库结构无法核实，拒绝覆盖")
            db.execute("PRAGMA user_version=1")
            # A prior process's uncertain write is not automatically replayed.
            db.execute("""UPDATE policies SET enabled=0 WHERE project IN
                (SELECT project FROM runs WHERE status='running')""")
            db.execute(
                """UPDATE runs SET status='interrupted',finished_at=?,
                message='服务中断；请检查回收区、恢复未完成条目并重新审阅启用'
                WHERE status='running'""",
                (clock(),),
            )
        self.path.chmod(0o600)

    @contextmanager
    def _db(self):
        _safe(self.path)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                if db.execute("PRAGMA user_version").fetchone()[0] not in {0, 1}:
                    raise ValueError("自动保留数据库版本不受支持，拒绝降级或覆盖")
                yield db
        finally:
            db.close()

    def review(self, path, options, interval_minutes):
        if type(interval_minutes) is not int or not 1 <= interval_minutes <= 525600:
            raise ValueError("检查间隔必须是 1–525600 的整数分钟")
        if options.get("min_age_days") is None and options.get("keep_latest") is None:
            raise ValueError("自动保留必须显式指定年龄或数量规则")
        advice = retention_plan(self.manager.saved_items(), path, **options)
        if advice["warnings"]:
            raise ValueError("引用或任务无法核实，请处理后重新审阅")
        self._check_archive(advice["project"])
        with self._db() as db:
            prior = db.execute(
                "SELECT revision FROM policies WHERE project=?", (advice["project"],)
            ).fetchone()
        return {
            "project": advice["project"],
            "project_id": self.manager.store._manifest(Path(advice["project"]))["id"],
            "previous_revision": prior["revision"] if prior else None,
            "options": options,
            "interval_minutes": interval_minutes,
            "advice": advice,
            "authorization": "启用后持续按本项目规则重新选择产物，包括未来符合条件的产物；只移入回收区，不永久清空。",
        }

    def enable(self, review, owner):
        # Repeat validation; a review is not an exemption from current safety checks.
        current = self.review(review["project"], review["options"], review["interval_minutes"])
        if current["project_id"] != review["project_id"]:
            raise RuntimeError("项目身份已改变，请重新审阅")
        principal = next((u for u in self.auth.users() if u["id"] == owner), None)
        if not principal or not principal["active"] or principal["role"] != "admin":
            raise PermissionError("启用自动保留需要有效管理员授权")
        now = self.clock()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT revision FROM policies WHERE project=?", (current["project"],)
            ).fetchone()
            if (prior["revision"] if prior else None) != review["previous_revision"]:
                raise RuntimeError("自动保留规则已被其他操作改变，请重新审阅")
            active = self.runtime()[0]
            db.execute(
                "UPDATE runs SET status='interrupted',finished_at=?,message='已重新审阅；旧运行结果须结合回收区核实' WHERE project=? AND status='running' AND id!=?",
                (now, current["project"], active[0]["id"] if active else ""),
            )
            db.execute(
                """INSERT OR REPLACE INTO policies VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    current["project"],
                    uuid4().hex,
                    1,
                    owner,
                    json.dumps(current["options"]),
                    current["interval_minutes"],
                    now + 60 * current["interval_minutes"],
                    now,
                    current["project_id"],
                ),
            )
        return self.status(current["project"])

    def disable(self, path):
        folder = str(self.manager.store._folder(_safe(Path(path).absolute())))
        with self._db() as db:
            db.execute(
                "UPDATE policies SET enabled=0,revision=?,updated_at=? WHERE project=?",
                (uuid4().hex, self.clock(), folder),
            )
        return self.status(folder)

    def status(self, path):
        folder = str(self.manager.store._folder(_safe(Path(path).absolute())))
        with self._db() as db:
            row = db.execute("SELECT * FROM policies WHERE project=?", (folder,)).fetchone()
            runs = db.execute(
                "SELECT * FROM runs WHERE project=? ORDER BY started_at DESC,id DESC LIMIT 50",
                (folder,),
            ).fetchall()
        policy = dict(row) if row else None
        if policy:
            policy["enabled"] = bool(policy["enabled"])
            policy["options"] = json.loads(policy["options"])
            policy["authorized_by"] = next(
                (u["username"] for u in self.auth.users() if u["id"] == policy["owner"]),
                "账号已移除",
            )
        return {"policy": policy, "runs": [dict(r) for r in runs], "error": self.runtime()[1]}

    def runtime(self):
        with self._lock:
            active = [dict(self._active)] if self._active else []
        error = self.error
        if self._thread is not None and not self._thread.is_alive() and not self._stop.is_set():
            error = "自动保留线程已停止，运行状态待核实"
        if not active:
            try:
                with self._db() as db:
                    if db.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
                        error = "存在未完成自动保留运行记录，请检查回收区并重新审阅"
            except (OSError, sqlite3.Error, ValueError):
                error = "自动保留状态无法核实，请检查服务存储"
        return active, error

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="scmm-retention", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
                self.error = None
            except Exception:
                self.error = "自动保留状态不可读或不可写，已停止本轮执行，请检查服务存储"
            self._stop.wait(5)

    def _allowed(self, policy):
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM policies WHERE project=?", (policy["project"],)
            ).fetchone()
        owner = next((u for u in self.auth.users() if u["id"] == policy["owner"]), None)
        if not owner or not owner["active"] or owner["role"] != "admin":
            with self._db() as db:
                db.execute(
                    "UPDATE policies SET enabled=0 WHERE project=? AND revision=?",
                    (policy["project"], policy["revision"]),
                )
        manifest = self.manager.store._manifest(_safe(Path(policy["project"])))
        if manifest["id"] != policy["project_id"]:
            raise RuntimeError("原路径的项目身份已改变，已停用自动保留")
        if (
            self._stop.is_set()
            or not row
            or not row["enabled"]
            or row["revision"] != policy["revision"]
            or not owner
            or not owner["active"]
            or owner["role"] != "admin"
            or getattr(self.manager, "maintenance_frozen", False)
        ):
            raise RetentionCancelled(
                "策略已停用/改变、管理员授权已失效或服务正在停止，停止本轮清理"
            )

    def _check_archive(self, project):
        if any(
            r.get("retention_version") == 1
            and r["path"] == project
            and r.get("status") not in {"moved", "restored"}
            for r in self.manager.saved_items().list_trash()
        ):
            raise RuntimeError("本项目存在未完成清理，请先恢复回收条目")

    def tick(self):
        """At most one cycle runs in this single-process service; missed intervals coalesce."""
        if self._stop.is_set():
            return
        with self._db() as db:
            # An in-process persistence failure stays unknown until reviewed.
            if (
                db.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone()
                and not self.runtime()[0]
            ):
                raise RuntimeError("存在未完成自动保留运行记录，请检查回收区并重新审阅")
            policies = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM policies WHERE enabled=1 AND next_at<=? ORDER BY next_at,project",
                    (self.clock(),),
                )
            ]
        for policy in policies:
            with self.manager._lock, self._lock:
                if (
                    self._active
                    or self._stop.is_set()
                    or getattr(self.manager, "maintenance_frozen", False)
                ):
                    return
                identity = uuid4().hex
                self._active = {
                    "id": identity,
                    "kind": "自动保留",
                    "status": "running",
                    "user_id": policy["owner"],
                    "started_at": self.clock(),
                    "project": Path(policy["project"]).name,
                    "process_alive": True,
                    "total": 0,
                    "completed": 0,
                }
            try:
                self._cycle(policy, identity)
            finally:
                with self._lock:
                    self._active = None

    def _cycle(self, policy, identity):
        started = self.clock()
        with self._db() as db:
            claimed = db.execute(
                "UPDATE policies SET next_at=? WHERE project=? AND revision=? AND enabled=1 AND next_at<=?",
                (
                    started + policy["interval_minutes"] * 60,
                    policy["project"],
                    policy["revision"],
                    started,
                ),
            )
            if not claimed.rowcount:
                return
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?, ?,?)",
                (
                    identity,
                    policy["project"],
                    policy["revision"],
                    policy["owner"],
                    started,
                    None,
                    "running",
                    "开始检查引用与规则",
                    None,
                ),
            )
        status, message, entry = "retained", "没有可清理产物；保护项和未知项继续保留", None
        try:
            self._allowed(policy)
            # Busy/open projects remain scheduled, and are rechecked next interval.
            with self.manager.retention_operation(policy["project"]):
                self._check_archive(policy["project"])
                advice = retention_plan(
                    self.manager.saved_items(), policy["project"], **json.loads(policy["options"])
                )
                if advice["warnings"]:
                    raise RuntimeError("引用或任务无法完整核实；已停用策略，请处理后重新审阅")
                if any(r["selected_for_cleanup"] for r in advice["items"]):
                    plan = cleanup_plan(
                        self.manager.saved_items(),
                        policy["project"],
                        **json.loads(policy["options"]),
                    )
                    entry = str(
                        execute_cleanup(
                            self.manager.saved_items(),
                            plan,
                            check_allowed=lambda: self._allowed(policy),
                        )
                    )
                    status, message = "completed", "本轮已归档到回收区，尚未释放磁盘空间"
        except RetentionCancelled as exc:
            status, message = "cancelled", str(exc)
        except Exception as exc:
            from .workspace_state import WorkspaceError

            if isinstance(exc, WorkspaceError) and exc.code == "retention_busy":
                status, message = "skipped", str(exc)
            else:
                status, message = "failed", str(exc)
                with self._db() as db:
                    db.execute(
                        "UPDATE policies SET enabled=0 WHERE project=? AND revision=?",
                        (policy["project"], policy["revision"]),
                    )
        with self._db() as db:
            db.execute(
                "UPDATE runs SET status=?,message=?,entry=?,finished_at=? WHERE id=?",
                (status, message, entry, self.clock(), identity),
            )
            db.execute(
                "DELETE FROM runs WHERE project=? AND id NOT IN (SELECT id FROM runs WHERE project=? ORDER BY started_at DESC,id DESC LIMIT 50)",
                (policy["project"], policy["project"]),
            )
