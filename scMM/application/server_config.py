"""Server resources, separate from scientific parameters and browser input."""
# ruff: noqa: RUF001

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .processing import OutputRoot
from .storage import StorageRoot

CONFIG_PATH = Path("~/.config/scmm/server.json")
_PATHS = {
    "auth_db": "SCMM_AUTH_DB",
    "monitor_db": "SCMM_MONITOR_DB",
    "monitor_peer_token_file": "SCMM_MONITOR_PEER_TOKEN_FILE",
    "project_root": "SCMM_PROJECT_ROOT",
    "preferences": "SCMM_PREFERENCES",
    "recycle_root": "SCMM_RECYCLE_ROOT",
    "cache_root": "SCMM_CACHE_DIR",
    "temp_root": "SCMM_TMP_DIR",
    "lipid_database_dir": "SCMM_LIPID_DATABASE_DIR",
    "thermo_reader": "SCMM_THERMO_READER",
    "dotnet": "SCMM_DOTNET",
}
_ENV = {
    **_PATHS,
    "storage": "SCMM_STORAGE_ROOTS",
    "output": "SCMM_OUTPUT_ROOTS",
    "environment": "SCMM_ENVIRONMENT",
    "monitor_peer_url": "SCMM_MONITOR_PEER_URL",
    "address": "SCMM_ADDRESS",
    "port": "SCMM_PORT",
    "cookie_name": "SCMM_SESSION_COOKIE",
    "cookie_secure": "SCMM_COOKIE_SECURE",
    "origins": "SCMM_ALLOWED_ORIGINS",
    "session_idle_seconds": "SCMM_SESSION_IDLE_SECONDS",
    "session_absolute_seconds": "SCMM_SESSION_ABSOLUTE_SECONDS",
}
_STATE = Path("~/.local/state/scmm")
DEFAULTS = {
    "address": "127.0.0.1",
    "port": 5006,
    "cookie_name": "scmm_session",
    "cookie_secure": True,
    "origins": [],
    "storage": {},
    "output": {},
    "preferences": str(_STATE / "preferences.json"),
    "recycle_root": str(_STATE / "recycle"),
    "cache_root": str(_STATE / "cache"),
    "temp_root": str(_STATE / "tmp"),
    "lipid_database_dir": None,
    "thermo_reader": None,
    "dotnet": None,
    "auth_db": None,
    "monitor_db": None,
    "monitor_peer_url": None,
    "monitor_peer_token_file": None,
    "environment": "standalone",
    "project_root": None,
    "session_idle_seconds": 3600,
    "session_absolute_seconds": 43200,
}


def outside_repository(path):
    path = Path(path).expanduser().resolve()
    for parent in (path.parent, *path.parents):
        marker = parent / ".git"
        if marker.is_file() or (marker / "HEAD").is_file():
            raise ValueError("真实服务器配置和凭据必须保存在 Git 工作区之外。")
    return path


@dataclass(frozen=True)
class ServerConfig:
    values: dict
    path: Path

    @property
    def auth_db(self):
        return Path(self.values["auth_db"])

    @property
    def cookie_name(self):
        return self.values["cookie_name"]

    @property
    def cookie_secure(self):
        return self.values["cookie_secure"]

    @property
    def origins(self):
        return tuple(self.values["origins"])

    def validate(self):
        from .auth import AuthStore

        outside_repository(self.path)
        if (
            not self.values["auth_db"]
            or not self.values["project_root"]
            or not self.values["storage"]
        ):
            raise ValueError("缺少认证数据库、原始数据目录或项目输出目录，请执行 scmm-admin init。")
        if not self.values["monitor_db"]:
            raise ValueError("监控数据库未配置，请执行 scmm-admin init-monitor。")
        from .monitor_store import MonitorStore

        monitor_path = outside_repository(self.values["monitor_db"])
        auth_path = outside_repository(self.auth_db)
        private_paths = [auth_path, monitor_path, self.path.resolve()]
        if len(set(private_paths)) != len(private_paths):
            raise ValueError("认证、监控数据库与配置必须分别保存。")
        if self.values.get("monitor_peer_token_file"):
            private_paths.append(outside_repository(self.values["monitor_peer_token_file"]))
        roots = [StorageRoot(k, v) for k, v in self.values["storage"].items()]
        outputs = [OutputRoot(k, v) for k, v in self.values["output"].items()]
        project = OutputRoot("项目结果", Path(self.values["project_root"]))
        for root in [*outputs, project]:
            if not os.access(root.path, os.W_OK | os.X_OK):
                raise PermissionError(f"输出目录不可写：{root.path}")
        # Credentials must never be inside a directory exposed to browser clients.
        for root in [*roots, *outputs, project]:
            if any(p.is_relative_to(root.path) for p in private_paths):
                raise ValueError("认证数据库和服务器配置不能位于网页可浏览目录中。")
        for key in ("cache_root", "temp_root", "recycle_root"):
            root = OutputRoot(key, Path(self.values[key]))
            if not os.access(root.path, os.W_OK | os.X_OK):
                raise PermissionError(f"{key} 目录不可写：{root.path}")
        OutputRoot("preferences", Path(self.values["preferences"]).parent)
        MonitorStore(monitor_path)
        AuthStore(
            auth_path,
            idle_seconds=self.values["session_idle_seconds"],
            absolute_seconds=self.values["session_absolute_seconds"],
        )
        return self

    def apply(self):
        os.environ["SCMM_SERVER_CONFIG_ACTIVE"] = "1"
        for key, name in _PATHS.items():
            if self.values.get(key) is not None:
                os.environ[name] = str(self.values[key])
            elif key in {"lipid_database_dir", "thermo_reader", "dotnet"}:
                os.environ.pop(name, None)
        os.environ["MPLCONFIGDIR"] = str(Path(self.values["cache_root"]) / "matplotlib")
        os.environ["NUMBA_CACHE_DIR"] = str(Path(self.values["cache_root"]) / "numba")
        os.environ["TMPDIR"] = str(self.values["temp_root"])


def load_server_config(path=None, overrides=None, *, environ=None):
    environ = os.environ if environ is None else environ
    path = Path(path or environ.get("SCMM_SERVER_CONFIG") or CONFIG_PATH).expanduser().absolute()
    # Explicitly selected files must exist, even when environment variables supply all fields.
    if not path.is_file():
        raise ValueError("服务器配置不存在，请先执行 scmm-admin init，或指定 --server-config。")
    local = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(local, dict) or set(local) - set(DEFAULTS):
        raise ValueError("服务器资源配置包含未知字段；实验参数请使用 --config。")
    values = {**DEFAULTS, **local}
    for key, name in _ENV.items():
        if name in environ:
            value = environ[name]
            if key in {"storage", "output", "origins", "cookie_secure"}:
                value = json.loads(value)
            values[key] = value
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    for key in _PATHS:
        if values.get(key) is not None:
            values[key] = str(Path(values[key]).expanduser().absolute())
    for key in ("storage", "output"):
        if not isinstance(values[key], dict):
            raise ValueError(f"{key} 必须是名称到目录的映射。")
        values[key] = {k: str(Path(v).expanduser().absolute()) for k, v in values[key].items()}
    if not isinstance(values["cookie_secure"], bool):
        raise ValueError("cookie_secure 必须为布尔值。")
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", values["cookie_name"]):
        raise ValueError("Cookie 名称不合法。")
    values["port"] = int(values["port"])
    if not 1 <= values["port"] <= 65535:
        raise ValueError("端口必须在 1–65535 之间。")
    for key in ("session_idle_seconds", "session_absolute_seconds"):
        if isinstance(values[key], str) and values[key].isdigit():
            values[key] = int(values[key])
        if type(values[key]) is not int or values[key] <= 0:
            raise ValueError(f"{key} 必须是正整数秒数。")
    if values["session_idle_seconds"] > values["session_absolute_seconds"]:
        raise ValueError("会话空闲时限不能超过最长有效期。")
    if not isinstance(values["origins"], list):
        raise ValueError("origins 必须是完整来源地址列表。")
    for origin in values["origins"]:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.path
            or (parsed.query or parsed.fragment or parsed.username or parsed.password)
        ):
            raise ValueError("来源地址必须包含协议和主机，不能包含路径或凭据。")
    if values["environment"] not in {"dev", "prod", "standalone"}:
        raise ValueError("environment 必须为 dev、prod 或 standalone。")
    if values["monitor_peer_url"]:
        peer = urlsplit(values["monitor_peer_url"])
        if (
            peer.scheme != "http"
            or peer.hostname not in {"127.0.0.1", "localhost", "::1"}
            or peer.path
            or peer.query
            or peer.fragment
            or peer.username
            or peer.password
            or peer.port == values["port"]
        ):
            raise ValueError("生产检查仅接受其他端口的本机 HTTP 地址，不能含路径、查询或凭据。")
    return ServerConfig(values, path)
