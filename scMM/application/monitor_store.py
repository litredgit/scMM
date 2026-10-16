"""Bounded monitoring history and durable browser-page evidence, without credentials."""
# ruff: noqa: RUF001

import json
import math
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .auth import AuthError, digest


class MonitorStore:
    def __init__(self, path=None, *, clock=time.time):
        self.clock = clock
        self.path = Path(path).expanduser().absolute() if path else None
        if self.path and (self.path.is_symlink() or not self.path.is_file()):
            raise ValueError("监控数据库未初始化，请执行 scmm-admin init-monitor。")
        if self.path and self.path.stat().st_mode & 0o077:
            raise ValueError("监控数据库权限必须为 600。")
        self._lock = threading.RLock()
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if not path else None
        with self.connect() as db:
            if self._memory:
                self.schema(db)
            elif db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("监控数据库版本不受支持。")

    @staticmethod
    def schema(db):
        db.executescript("""
            CREATE TABLE pages (
                id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, instance TEXT NOT NULL,
                user_id TEXT, seen REAL NOT NULL, route TEXT NOT NULL, visibility TEXT NOT NULL,
                workspace_id TEXT, closed REAL
            );
            CREATE TABLE accounts (id TEXT PRIMARY KEY, seen REAL NOT NULL, activity REAL);
            CREATE TABLE history (minute INTEGER PRIMARY KEY, instance TEXT NOT NULL, data TEXT NOT NULL);
            PRAGMA user_version=1;
        """)

    @classmethod
    def initialize(cls, path):
        path = Path(path).expanduser().absolute()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with sqlite3.connect(path) as db:
                cls.schema(db)
            return cls(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @contextmanager
    def connect(self):
        with self._lock:
            db = self._memory or sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True, timeout=2
            )
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                if db is not self._memory:
                    db.close()

    def register(self, identity, instance, user_id, route, visibility, workspace_id):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) FROM pages WHERE closed IS NULL").fetchone()[0] >= 2048:
                raise AuthError(
                    "页面登记容量已满，请联系服务器管理员核对。", 503, "presence_capacity"
                )
            if db.execute("SELECT 1 FROM pages WHERE id=?", (identity,)).fetchone():
                raise AuthError("页面已登记，请使用原登记凭据。", 409, "page_exists")
            db.execute(
                "INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,NULL)",
                (
                    identity,
                    digest(token),
                    instance,
                    user_id,
                    self.clock(),
                    route,
                    visibility,
                    workspace_id,
                ),
            )
        return {"id": identity, "token": token, "instance": instance}

    def heartbeat(
        self, identity, token, instance, user_id, route, visibility, workspace_id, closed=False
    ):
        with self.connect() as db:
            row = db.execute("SELECT * FROM pages WHERE id=?", (identity,)).fetchone()
            if not row or not secrets.compare_digest(row["secret_hash"], digest(token)):
                raise AuthError("页面登记无效，请刷新页面。", 403, "presence_rejected")
            # A late heartbeat must never reopen a document which already sent pagehide.
            if row["closed"] is not None:
                raise AuthError("页面登记已关闭。", 409, "page_closed")
            db.execute(
                """UPDATE pages SET instance=?,user_id=?,seen=?,route=?,visibility=?,
                workspace_id=?,closed=? WHERE id=?""",
                (
                    instance,
                    user_id,
                    self.clock(),
                    route,
                    visibility,
                    workspace_id,
                    self.clock() if closed else None,
                    identity,
                ),
            )
        return {"instance": instance}

    def pages(self):
        with self.connect() as db:
            # Page IDs and lease hashes are deliberately excluded from administration responses.
            return [
                dict(row)
                for row in db.execute("""SELECT instance,user_id,seen,route,visibility,workspace_id
                FROM pages WHERE closed IS NULL ORDER BY seen DESC""")
            ]

    def observed(self, identity, *, closing=False):
        with self.connect() as db:
            return bool(
                db.execute(
                    """SELECT 1 FROM pages WHERE id=? AND
                (closed IS NULL OR (?=1 AND closed>=?))""",
                    (identity, int(closing), self.clock() - 30),
                ).fetchone()
            )

    def seen(self, principal, activity):
        with self.connect() as db:
            db.execute(
                """INSERT INTO accounts VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET
                seen=excluded.seen,activity=COALESCE(excluded.activity,accounts.activity)""",
                (principal["id"], self.clock(), self.clock() if activity else None),
            )

    def accounts(self):
        with self.connect() as db:
            return {row["id"]: dict(row) for row in db.execute("SELECT * FROM accounts")}

    def write_history(self, instance, sample):
        now = self.clock()
        minute = int(now // 60) * 60
        values = {
            k: v
            for k, v in sample.items()
            if isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
        }
        with self.connect() as db:
            row = db.execute("SELECT * FROM history WHERE minute=?", (minute,)).fetchone()
            data = json.loads(row["data"]) if row and row["instance"] == instance else {}
            for key, value in values.items():
                item = data.setdefault(key, {"sum": 0, "count": 0, "max": value})
                item["sum"] += value
                item["count"] += 1
                item["max"] = max(item["max"], value)
            db.execute(
                "INSERT OR REPLACE INTO history VALUES(?,?,?)", (minute, instance, json.dumps(data))
            )
            db.execute("DELETE FROM history WHERE minute<?", (now - 86400,))
            db.execute("DELETE FROM pages WHERE closed IS NOT NULL AND closed<?", (now - 86400,))

    def history(self):
        with self.connect() as db:
            result = []
            for row in db.execute(
                "SELECT * FROM history WHERE minute>=? ORDER BY minute", (self.clock() - 86400,)
            ):
                data = json.loads(row["data"])
                result.append(
                    {
                        "at": row["minute"],
                        "instance": row["instance"],
                        "metrics": {
                            key: {"mean": item["sum"] / item["count"], "peak": item["max"]}
                            for key, item in data.items()
                        },
                    }
                )
            return result
