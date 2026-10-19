"""Personal encrypted AI credentials, deliberately outside project persistence."""

# ruff: noqa: RUF001
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class AIError(Exception):
    def __init__(self, message, status=400, code="ai_error"):
        super().__init__(message)
        self.status, self.code = status, code


def private_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("AI 数据库和主密钥必须是独立的私有普通文件（0600）。")
    return path


class AIConfigStore:
    @staticmethod
    def initialize(database, key_file):
        database, key_file = Path(database), Path(key_file)
        if database.resolve() == key_file.resolve():
            raise ValueError("AI 数据库与主密钥必须分开保存。")
        if any(p.exists() or p.is_symlink() for p in (database, key_file)):
            raise ValueError("AI 配置已存在，拒绝覆盖。")
        created = []
        try:
            for path, content in ((key_file, Fernet.generate_key()), (database, b"")):
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                created.append(path)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
            db = sqlite3.connect(database)
            try:
                with db:
                    db.execute(
                        "CREATE TABLE configurations (user_id TEXT PRIMARY KEY, secret BLOB NOT NULL)"
                    )
            finally:
                db.close()
            return AIConfigStore(database, key_file)
        except Exception:
            for path in reversed(created):
                path.unlink(missing_ok=True)
            raise

    def __init__(self, database, key_file):
        self.database = private_file(database)
        if self.database.resolve() == Path(key_file).resolve():
            raise ValueError("AI 数据库与主密钥必须分开保存。")
        self.key_file = private_file(key_file)
        self.cipher = Fernet(self.key_file.read_bytes().strip())
        with self.connect() as db:
            db.execute("SELECT user_id FROM configurations LIMIT 1")
            db.execute(
                "CREATE TABLE IF NOT EXISTS conversations (user_id TEXT NOT NULL, context_key TEXT NOT NULL, revision INTEGER NOT NULL, secret BLOB NOT NULL, PRIMARY KEY(user_id,context_key))"
            )

    @contextmanager
    def connect(self):
        # mode=rw never recreates a deleted database at request time.
        db = sqlite3.connect(self.database.resolve().as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, user_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT secret FROM configurations WHERE user_id=?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(self.cipher.decrypt(row[0]))
            if value.pop("user_id") != user_id:
                raise ValueError
            return value
        except (InvalidToken, ValueError, KeyError):
            raise AIError("个人 AI 配置无法解密，请重新保存或删除。", 409) from None

    def public(self, user_id):
        value = self.load(user_id)
        return {
            "available": True,
            "configured": value is not None,
            "base_url": value["base_url"] if value else "",
            "model": value["model"] if value else "",
        }

    def save(self, user_id, base_url, model, key):
        # Never reuse a key across a changed destination or model. A save is one tuple.
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise AIError("保存配置时请同时输入有效的 API Key。")
        secret = self.cipher.encrypt(
            json.dumps(
                {"user_id": user_id, "base_url": base_url, "model": model, "key": key}
            ).encode()
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO configurations VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET secret=excluded.secret",
                (user_id, secret),
            )
        return self.public(user_id)

    def delete(self, user_id):
        with self.connect() as db:
            db.execute("DELETE FROM configurations WHERE user_id=?", (user_id,))

    def history(self, user_id, context):
        import hashlib

        key = hashlib.sha256(context.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute(
                "SELECT revision,secret FROM conversations WHERE user_id=? AND context_key=?",
                (user_id, key),
            ).fetchone()
        if row is None:
            return {"revision": 0, "messages": [], "draft": "", "streaming": False, "summary": None}
        try:
            payload = json.loads(self.cipher.decrypt(row[1]))
            if payload.pop("owner") != user_id or payload.pop("context_key") != key:
                raise ValueError("Conversation identity mismatch")
        except Exception as exc:
            raise AIError("聊天恢复记录无法验证，请联系管理员。", 409, "history_invalid") from exc
        return {**payload, "revision": row[0]}

    def save_history(self, user_id, context, revision, payload):
        import hashlib

        key = hashlib.sha256(context.encode()).hexdigest()
        plaintext = json.dumps(
            {**payload, "owner": user_id, "context_key": key}, ensure_ascii=False, allow_nan=False
        ).encode()
        if len(plaintext) > 10 * 1024**2:
            raise AIError("单个会话的聊天记录超过 10 MiB，请先导出或清空。", 413)
        secret = self.cipher.encrypt(plaintext)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM conversations WHERE user_id=? AND context_key=?",
                (user_id, key),
            ).fetchone()
            if (row[0] if row else 0) != revision:
                raise AIError("聊天已被其他页面更新，请重新读取后继续。", 409, "history_conflict")
            next_revision = revision + 1
            db.execute(
                "INSERT INTO conversations VALUES(?,?,?,?) ON CONFLICT(user_id,context_key) DO UPDATE SET revision=excluded.revision, secret=excluded.secret",
                (user_id, key, next_revision, secret),
            )
        return {"revision": next_revision}
