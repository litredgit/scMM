"""Deferred systemd job: apply validated configuration and roll back failed restarts."""

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

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


def run(config_path, action, version=None, *, deployment_first=False):
    config = load_server_config(config_path, environ={}).validate()
    environment = config.values["environment"]
    if environment not in {"dev", "prod"}:
        raise ValueError("Unsupported service environment")
    unit = "scmm-dev.service" if environment == "dev" else "scmm-ui.service"
    if deployment_first:
        from .deployment_client import prepare_service

        prepare_service(config, config.values["port"])
    root = config.path.parent / (config.path.stem + ".recovery")
    pointer = root / "current.json"
    checkpoint = pointer.read_bytes()
    original = config.path.read_bytes()
    pending = config.path.with_suffix(".pending.json")
    started = time.time()
    try:
        if pending.exists():
            updates = json.loads(pending.read_text())
            ServerConfig({**config.values, **updates}, config.path).validate()
            previous = json.loads(original)
            write_json(config.path.with_suffix(".previous.json"), previous)
            write_json(config.path, {**previous, **updates})
        if action == "restart":
            subprocess.run(["systemctl", "--user", "restart", unit], check=True)
        else:
            repository = Path(__file__).resolve().parents[2]
            subprocess.run(
                [
                    str(repository / ".venv/bin/python"),
                    str(repository / "scripts/scmm_env.py"),
                    "update",
                    environment,
                    "--approved-version",
                    version,
                ],
                check=True,
            )
        healthy(config.values["port"])
        pending.unlink(missing_ok=True)
        write_json(
            root / "last-operation.json",
            {
                "action": action,
                "version": version,
                "started": started,
                "finished": time.time(),
                "status": "succeeded",
            },
        )
    except BaseException:
        temporary = config.path.with_suffix(".rollback.tmp")
        temporary.write_bytes(original)
        temporary.chmod(0o600)
        temporary.replace(config.path)
        pointer.write_bytes(checkpoint)
        subprocess.run(["systemctl", "--user", "restart", unit], check=True)
        healthy(config.values["port"])
        write_json(
            root / "last-operation.json",
            {
                "action": action,
                "version": version,
                "started": started,
                "finished": time.time(),
                "status": "rolled_back",
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("action", choices=["restart", "update"])
    parser.add_argument("--version")
    parser.add_argument("--deployment-first", action="store_true")
    args = parser.parse_args()
    run(args.config, args.action, args.version, deployment_first=args.deployment_first)


if __name__ == "__main__":
    main()
