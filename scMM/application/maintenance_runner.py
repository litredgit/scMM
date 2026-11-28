"""Deferred systemd job: apply validated configuration and roll back failed restarts."""

import argparse
import fcntl
import json
import os
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from .projects import write_json
from .server_config import ServerConfig, load_server_config


def healthy(port):
    for _ in range(150):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=2
            ) as response:
                if json.load(response).get("status") == "ok":
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Service did not pass health check")


@contextmanager
def pending_lock(path, *, operation=False):
    suffix = ".operation.lock" if operation else ".pending.lock"
    with path.with_suffix(suffix).open("a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if operation else 0))
        yield


def restore_file(path, content):
    if content is None:
        path.unlink(missing_ok=True)
        return
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read_optional(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


class ResourceChange:
    def __init__(self, config):
        self.path = config.path
        self.pending = self.path.with_suffix(".pending.json")
        self.original = self.path.read_bytes()
        self.updates = None
        with pending_lock(self.path):
            if self.pending.is_file():
                self.identity = self.pending.stat()
                self.updates = json.loads(self.pending.read_bytes())
                ServerConfig({**config.values, **self.updates}, self.path).validate()

    def apply(self):
        if self.updates is not None:
            previous = json.loads(self.original)
            write_json(self.path.with_suffix(".previous.json"), previous, mode=0o600)
            write_json(self.path, {**previous, **self.updates}, mode=0o600)

    def rollback(self):
        if self.updates is not None:
            restore_file(self.path, self.original)

    def finish(self):
        if self.updates is not None:
            with pending_lock(self.path):
                if self.pending.exists():
                    current = self.pending.stat()
                    if (current.st_ino, current.st_mtime_ns, current.st_size) == (
                        self.identity.st_ino,
                        self.identity.st_mtime_ns,
                        self.identity.st_size,
                    ):
                        self.pending.unlink()


def run(config_path, action, version=None, *, deployment_first=False, strict_checkpoint=None):
    config = load_server_config(config_path, environ={}).validate()
    environment = config.values["environment"]
    if environment not in {"dev", "prod"}:
        raise ValueError("Unsupported service environment")
    unit = "scmm-dev.service" if environment == "dev" else "scmm-ui.service"
    root = config.path.parent / (config.path.stem + ".recovery")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = time.time()
    status = "failed"
    try:
        if action == "update":
            repository = Path(__file__).resolve().parents[2]
            command = [
                str(repository / ".venv/bin/python"),
                str(repository / "scripts/scmm_env.py"),
                "update",
                environment,
                "--approved-version",
                version,
                "--maintenance-config",
                str(config.path),
            ]
            if deployment_first:
                command.append("--deployment-first")
            elif strict_checkpoint:
                command.extend(["--strict-checkpoint", strict_checkpoint])
            else:
                raise ValueError("Update requires a maintenance policy")
            subprocess.run(command, check=True)
        else:
            with pending_lock(config.path, operation=True):
                change = ResourceChange(config)
                if deployment_first:
                    from .deployment_client import prepare_service

                    prepare_service(config, config.values["port"])
                elif strict_checkpoint:
                    from .deployment_client import verify_strict_checkpoint

                    verify_strict_checkpoint(config, strict_checkpoint)
                pointer = root / "current.json"
                checkpoint = read_optional(pointer)
                try:
                    change.apply()
                    subprocess.run(["systemctl", "--user", "restart", unit], check=True)
                    healthy(config.values["port"])
                except BaseException:
                    change.rollback()
                    restore_file(pointer, checkpoint)
                    subprocess.run(["systemctl", "--user", "restart", unit], check=True)
                    healthy(config.values["port"])
                    status = "rolled_back"
                    raise
                change.finish()
        status = "succeeded"
    finally:
        write_json(
            root / "last-operation.json",
            {
                "action": action,
                "version": version,
                "started": started,
                "finished": time.time(),
                "status": status,
            },
            mode=0o600,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("action", choices=["restart", "update"])
    parser.add_argument("--version")
    parser.add_argument("--deployment-first", action="store_true")
    parser.add_argument("--strict-checkpoint")
    args = parser.parse_args()
    run(
        args.config,
        args.action,
        args.version,
        deployment_first=args.deployment_first,
        strict_checkpoint=args.strict_checkpoint,
    )


if __name__ == "__main__":
    main()
