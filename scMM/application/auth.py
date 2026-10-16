"""Local accounts and revocable, opaque browser sessions. No HTTP dependencies."""
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_HASHER = PasswordHasher()
_DUMMY = _HASHER.hash(secrets.token_urlsafe(32))


class AuthError(ValueError):
    def __init__(self, message, status=401, code="authentication_required"):
        super().__init__(message)
        self.status, self.code = status, code


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", value):
        raise AuthError("账号须为 3–64 位字母、数字、点、下划线或短横线。", 422, "invalid_account")
    return value


class AuthStore:
    def __init__(self, path, *, idle_seconds=3600, absolute_seconds=43200, clock=time.time):
        self.path = Path(path).expanduser().absolute()
        self.idle_seconds, self.absolute_seconds, self.clock = idle_seconds, absolute_seconds, clock
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimeError("认证数据库缺失或路径无效，请先执行 scmm-admin init。")
        if self.path.stat().st_mode & 0o077:
            raise RuntimeError("认证数据库权限过宽，请将权限设为 600。")
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise RuntimeError("认证数据库版本不受支持。")
            if not db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():
                raise RuntimeError("认证数据库没有可用管理员。")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @classmethod
    def initialize(cls, path, admin):
        path = Path(path).expanduser().absolute()
        admin = username(admin)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        credential = secrets.token_urlsafe(32)
        try:
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE users (
                        id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                        password_hash TEXT, role TEXT NOT NULL, active INTEGER NOT NULL,
                        must_change INTEGER NOT NULL, credential_expires REAL
                    );
                    CREATE TABLE sessions (
                        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL,
                        created REAL NOT NULL, touched REAL NOT NULL
                    );
                    CREATE TABLE attempts (key TEXT PRIMARY KEY, count INTEGER, started REAL);
                    CREATE TABLE audit (
                        id INTEGER PRIMARY KEY, at REAL NOT NULL, user_id TEXT,
                        action TEXT NOT NULL, resource TEXT, status INTEGER
                    );
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    PRAGMA user_version=1;
                """)
                db.execute(
                    "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                    (
                        secrets.token_hex(16),
                        admin,
                        _HASHER.hash(credential),
                        "admin",
                        1,
                        1,
                        time.time() + 86400,
                    ),
                )
                db.execute(
                    "INSERT INTO settings VALUES ('operations_token', ?)",
                    (digest(secrets.token_urlsafe(32)),),
                )
            return cls(path), credential
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def audit(self, user_id, action, resource="", status=200):
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit(at,user_id,action,resource,status) VALUES(?,?,?,?,?)",
                (self.clock(), user_id, action, resource, status),
            )

    def login(self, name, password, source):
        now = self.clock()
        # Account and address budgets are persistent; callers cannot supply forwarding headers.
        keys = ["account:" + digest(name.strip().lower()), "address:" + digest(source)]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for key, limit in zip(keys, (10, 50), strict=True):
                row = db.execute("SELECT * FROM attempts WHERE key=?", (key,)).fetchone()
                if row and now - row["started"] < 900 and row["count"] >= limit:
                    raise AuthError("登录尝试过多，请稍后再试。", 429, "login_throttled")
            for key in keys:
                db.execute(
                    """INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET
                    count=CASE WHEN ?-started>=900 THEN 1 ELSE count+1 END,
                    started=CASE WHEN ?-started>=900 THEN ? ELSE started END""",
                    (key, now, now, now, now),
                )
            row = db.execute(
                "SELECT * FROM users WHERE username=?", (name.strip().lower(),)
            ).fetchone()
        try:
            _HASHER.verify(
                row["password_hash"] if row and row["password_hash"] else _DUMMY, password
            )
            valid = bool(
                row
                and row["active"]
                and (not row["must_change"] or (row["credential_expires"] or 0) > now)
            )
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            self.audit(None, "login_failed", status=401)
            raise AuthError("账号或密码不正确。", code="invalid_credentials")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            if not current["active"] or current["password_hash"] != row["password_hash"]:
                raise AuthError("账号或密码不正确。", code="invalid_credentials")
            if row["must_change"]:
                # Initialization credentials are consumed by the first successful login.
                db.execute("UPDATE users SET password_hash=NULL WHERE id=?", (row["id"],))
            elif _HASHER.check_needs_rehash(row["password_hash"]):
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (_HASHER.hash(password), row["id"]),
                )
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?)", (digest(token), row["id"], csrf, now, now)
            )
            db.execute("DELETE FROM attempts WHERE key=?", (keys[0],))
        self.audit(row["id"], "login")
        return token, self.authenticate(token)

    def authenticate(self, token, *, activity=False):
        now = self.clock()
        with self.connect() as db:
            row = db.execute(
                """SELECT users.*, sessions.id AS session_id, csrf, created, touched
                FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.id=?""",
                (digest(token),),
            ).fetchone()
            if (
                not row
                or not row["active"]
                or now - row["created"] >= self.absolute_seconds
                or (now - row["touched"] >= self.idle_seconds)
            ):
                raise AuthError("登录已失效，请重新登录。")
            if activity:
                db.execute("UPDATE sessions SET touched=? WHERE id=?", (now, row["session_id"]))
            return {
                key: row[key]
                for key in ("id", "username", "role", "must_change", "session_id", "csrf")
            }

    def logout(self, principal):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (principal["session_id"],))
        self.audit(principal["id"], "logout")

    def change_password(self, principal, current, new):
        if not 15 <= len(new) <= 128:
            raise AuthError("新密码须为 15–128 个字符。", 422, "invalid_password")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM sessions WHERE id=? AND user_id=?",
                (principal["session_id"], principal["id"]),
            ).fetchone():
                raise AuthError("登录已失效，请重新登录。")
            row = db.execute("SELECT * FROM users WHERE id=?", (principal["id"],)).fetchone()
            if not row["must_change"]:
                try:
                    _HASHER.verify(row["password_hash"], current)
                except (VerificationError, InvalidHashError):
                    raise AuthError("当前密码不正确。", 400, "invalid_password") from None
            db.execute(
                "UPDATE users SET password_hash=?, must_change=0, credential_expires=NULL WHERE id=?",
                (_HASHER.hash(new), principal["id"]),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (principal["id"],))
        self.audit(principal["id"], "password_changed")

    def users(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,username,role,active,must_change FROM users ORDER BY username"
                )
            ]

    def create_user(self, name, role="member", *, by=None):
        name = username(name)
        if role not in {"member", "admin"}:
            raise AuthError("账号角色无效。", 422, "invalid_account")
        credential, identity = secrets.token_urlsafe(32), secrets.token_hex(16)
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                    (identity, name, _HASHER.hash(credential), role, 1, 1, self.clock() + 86400),
                )
        except sqlite3.IntegrityError:
            raise AuthError("账号已存在。", 409, "account_exists") from None
        self.audit(by, "account_created", identity)
        return {"id": identity, "username": name, "initial_credential": credential}

    def update_user(self, identity, *, active=None, reset=False, by=None):
        if reset and by == identity:
            raise AuthError(
                "请使用修改密码功能；无法登录时由服务器管理员离线重置。", 409, "self_reset"
            )
        credential = secrets.token_urlsafe(32) if reset else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE id=?", (identity,)).fetchone()
            if not row:
                raise AuthError("账号不存在。", 404, "account_missing")
            if (
                active is False
                and row["role"] == "admin"
                and row["active"]
                and (
                    db.execute(
                        "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1"
                    ).fetchone()[0]
                    <= 1
                )
            ):
                raise AuthError("不能停用最后一个管理员。", 409, "last_admin")
            if active is not None:
                db.execute("UPDATE users SET active=? WHERE id=?", (int(active), identity))
            if reset:
                db.execute(
                    "UPDATE users SET password_hash=?,must_change=1,credential_expires=? WHERE id=?",
                    (_HASHER.hash(credential), self.clock() + 86400, identity),
                )
            db.execute("DELETE FROM sessions WHERE user_id=?", (identity,))
        self.audit(by, "account_reset" if reset else "account_updated", identity)
        return {"id": identity, "initial_credential": credential}

    def rotate_operations_token(self):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='operations_token'", (digest(token),))
        return token

    def check_operations_token(self, token):
        with self.connect() as db:
            expected = db.execute(
                "SELECT value FROM settings WHERE key='operations_token'"
            ).fetchone()[0]
        return bool(token and secrets.compare_digest(digest(token), expected))

    def audit_log(self, limit=200):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """SELECT audit.at, users.username, action, resource, status
                FROM audit LEFT JOIN users ON users.id=audit.user_id ORDER BY audit.id DESC LIMIT ?""",
                    (limit,),
                )
            ]
