"""Explicit server initialization and offline account recovery; never runs on startup."""
# ruff: noqa: RUF001

import argparse
import json
import os
from pathlib import Path

from scMM.application.auth import AuthStore
from scMM.application.monitor_store import MonitorStore
from scMM.application.server_config import DEFAULTS, load_server_config, outside_repository
from scMM.application.storage import StorageRoot

from .cli import parse_storage_root


def write_private(path, content):
    path = outside_repository(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="scmm-admin", description="初始化服务器配置、账号和运维凭据"
    )
    parser.add_argument("--server-config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="首次初始化；只在管理员终端执行")
    init.add_argument("--admin", required=True)
    init.add_argument("--auth-db", type=Path, required=True)
    init.add_argument("--project-root", type=Path, required=True)
    init.add_argument("--storage", action="append", type=parse_storage_root, required=True)
    init.add_argument("--output", action="append", type=parse_storage_root)
    for name in (
        "monitor-db",
        "preferences",
        "recycle-root",
        "cache-root",
        "temp-root",
        "lipid-database-dir",
        "thermo-reader",
        "dotnet",
    ):
        init.add_argument("--" + name, type=Path)
    init.add_argument("--cookie-name", default="scmm_session")
    init.add_argument("--insecure-cookie", action="store_true", help="仅受信任的内部 HTTP 环境使用")
    init.add_argument("--origin", action="append", default=[])
    init.add_argument("--port", type=int, default=5006)
    init.add_argument("--environment", choices=("dev", "prod", "standalone"), default="standalone")
    init.add_argument("--monitor-peer-url")
    init.add_argument("--monitor-peer-token-file", type=Path)
    init.add_argument("--session-idle-seconds", type=int, default=3600)
    init.add_argument("--session-absolute-seconds", type=int, default=43200)
    for name in ("create-user", "reset-password"):
        command = commands.add_parser(name)
        command.add_argument("username")
        command.add_argument("--credential-file", type=Path, required=True)
        if name == "create-user":
            command.add_argument("--role", choices=("member", "admin"), default="member")
    monitor = commands.add_parser("init-monitor", help="为已有认证配置初始化独立监控数据库")
    monitor.add_argument("--monitor-db", type=Path, required=True)
    monitor.add_argument(
        "--environment", choices=("dev", "prod", "standalone"), default="standalone"
    )
    monitor.add_argument("--monitor-peer-url")
    monitor.add_argument("--monitor-peer-token-file", type=Path)
    ai = commands.add_parser("init-ai", help="初始化独立的个人 AI 数据库与加密主密钥")
    ai.add_argument("--ai-db", type=Path, required=True)
    ai.add_argument("--ai-key-file", type=Path, required=True)
    commands.add_parser("rotate-operations-token")
    args = parser.parse_args(argv)
    if args.command == "init":
        if args.server_config is None:
            parser.error("init 必须指定仓库外的 --server-config")
        config_path = outside_repository(args.server_config)
        if config_path.exists() or args.auth_db.expanduser().exists():
            parser.error("配置或认证数据库已存在，初始化不会覆盖；恢复账号请用 reset-password")
        for target in (
            config_path.with_suffix(".initial.txt"),
            config_path.with_suffix(".operations-token"),
        ):
            if target.exists() or target.is_symlink():
                parser.error("初始化凭据输出文件已存在，拒绝覆盖")
        values = dict(DEFAULTS)
        for key in values:
            value = getattr(args, key, None)
            if value is not None and key not in {"storage", "output"}:
                values[key] = (
                    str(value.expanduser().absolute()) if isinstance(value, Path) else value
                )
        values["storage"] = {k: str(v.absolute()) for k, v in args.storage}
        values["output"] = {k: str(v.absolute()) for k, v in (args.output or [])}
        values.update(origins=args.origin, cookie_secure=not args.insecure_cookie)
        for key in ("preferences", "recycle_root", "cache_root", "temp_root"):
            values[key] = str(Path(values[key]).expanduser().absolute())
        for key, directory in values["storage"].items():
            StorageRoot(key, Path(directory))
        for directory in [
            values["project_root"],
            *values["output"].values(),
            values["recycle_root"],
            values["cache_root"],
            values["temp_root"],
            str(Path(values["preferences"]).parent),
        ]:
            Path(directory).mkdir(parents=True, exist_ok=True)
        values["monitor_db"] = values["monitor_db"] or str(
            Path(values["auth_db"]).with_name("monitor.sqlite3")
        )
        monitor_path = outside_repository(values["monitor_db"])
        auth_path = outside_repository(values["auth_db"])
        if monitor_path in {auth_path, config_path} or monitor_path.exists():
            parser.error("监控数据库必须独立且尚不存在")
        for directory in [
            *values["storage"].values(),
            *values["output"].values(),
            values["project_root"],
        ]:
            if any(
                p.is_relative_to(Path(directory).resolve())
                for p in (auth_path, config_path, monitor_path)
            ):
                parser.error("认证数据库和配置不能放在网页可浏览目录中")
        MonitorStore.initialize(monitor_path)
        store, credential = AuthStore.initialize(auth_path, args.admin)
        write_private(config_path, json.dumps(values, ensure_ascii=False, indent=2) + "\n")
        credential_path = write_private(config_path.with_suffix(".initial.txt"), credential + "\n")
        token_path = write_private(
            config_path.with_suffix(".operations-token"), store.rotate_operations_token() + "\n"
        )
        print(
            f"初始化完成。首次登录凭据（24 小时内有效）：{credential_path}\n运维凭据：{token_path}"
        )
        load_server_config(config_path).validate()
        return 0
    config = load_server_config(args.server_config)
    outside_repository(config.path)
    if args.command == "init-ai":
        from scMM.application.ai_config import AIConfigStore

        if config.values.get("ai_db") or config.values.get("ai_key_file"):
            raise ValueError("AI 配置已存在，拒绝覆盖。")
        database, key_file = (outside_repository(p) for p in (args.ai_db, args.ai_key_file))
        private = {
            config.auth_db.resolve(),
            config.path.resolve(),
            Path(config.values["monitor_db"]).resolve(),
        }
        if database == key_file or database in private or key_file in private:
            raise ValueError("AI 数据库、主密钥及其他私有配置必须分别保存。")
        for directory in [
            *config.values["storage"].values(),
            *config.values["output"].values(),
            config.values["project_root"],
        ]:
            if any(p.is_relative_to(Path(directory).resolve()) for p in (database, key_file)):
                raise ValueError("AI 配置不能位于网页可浏览目录中。")
        values = json.loads(config.path.read_text(encoding="utf-8"))
        values.update(ai_db=str(database), ai_key_file=str(key_file))
        staging = config.path.with_name(config.path.name + ".ai-init")
        write_private(staging, json.dumps(values, ensure_ascii=False, indent=2) + "\n")
        created = False
        try:
            AIConfigStore.initialize(database, key_file)
            created = True
            load_server_config(staging).validate()
            staging.replace(config.path)
        except Exception:
            if created:
                database.unlink(missing_ok=True)
                key_file.unlink(missing_ok=True)
            raise
        finally:
            staging.unlink(missing_ok=True)
        print("个人 AI 配置初始化完成；重启对应服务后启用。")
        return 0
    if args.command == "init-monitor":
        if config.values.get("monitor_db"):
            raise ValueError("监控数据库已配置，拒绝覆盖。")
        target = outside_repository(args.monitor_db)
        if target in {config.auth_db, config.path.resolve()}:
            raise ValueError("监控数据库必须独立保存。")
        for directory in [
            *config.values["storage"].values(),
            *config.values["output"].values(),
            config.values["project_root"],
        ]:
            if target.is_relative_to(Path(directory).resolve()):
                raise ValueError("监控数据库不能位于网页可浏览目录中。")
        values = json.loads(config.path.read_text(encoding="utf-8"))
        values.update(
            monitor_db=str(target),
            environment=args.environment,
            monitor_peer_url=args.monitor_peer_url,
            monitor_peer_token_file=str(args.monitor_peer_token_file.expanduser().absolute())
            if args.monitor_peer_token_file
            else None,
        )
        staging = config.path.with_name(config.path.name + ".monitor-init")
        write_private(staging, json.dumps(values, ensure_ascii=False, indent=2) + "\n")
        created = False
        try:
            prospective = load_server_config(staging)
            MonitorStore.initialize(target)
            created = True
            prospective.validate()
            staging.replace(config.path)
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
        finally:
            staging.unlink(missing_ok=True)
        print("监控配置初始化完成；重启对应服务后启用。")
        return 0
    store = AuthStore(config.auth_db)
    if args.command == "rotate-operations-token":
        target = config.path.with_suffix(".operations-token")
        # Explicit rotation replaces only this known private credential file.
        if target.is_symlink():
            raise ValueError("运维凭据文件不能是符号链接。")
        target.unlink(missing_ok=True)
        write_private(target, store.rotate_operations_token() + "\n")
        print(f"运维凭据已轮换：{target}")
        return 0
    target = outside_repository(args.credential_file)
    if target.exists():
        raise ValueError("凭据输出文件已存在，不会覆盖。")
    if args.command == "create-user":
        result = store.create_user(args.username, args.role)
    else:
        account = next((u for u in store.users() if u["username"] == args.username.lower()), None)
        if account is None:
            raise ValueError("账号不存在。")
        result = store.update_user(account["id"], reset=True)
    write_private(target, result["initial_credential"] + "\n")
    print(f"一次性登录凭据已写入：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
