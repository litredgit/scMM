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
        self.cipher = Fernet(private_file(key_file).read_bytes().strip())
        with self.connect() as db:
            db.execute("SELECT user_id FROM configurations LIMIT 1")

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
