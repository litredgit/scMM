#!/usr/bin/env python3
"""Manage two local worktrees without adding a separate deployment stack."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path.home() / ".config/scmm/environments.json"
SERVICE = "scmm-ui.service"


def settings(config=CONFIG):
    home = Path.home()
    values = {
        "dev": str(home / "scMM"),
        "prod": str(home / "scMM-prod"),
        "raw": str(home / "data"),
        "prod_results": str(home / "data/results"),
        "state": str(home / ".local/state/scmm"),
        "address": "0.0.0.0",
        "origins": ["*"],
    }
    if config.exists():
        overrides = json.loads(config.read_text())
        if set(overrides) - set(values):
            raise ValueError("Unknown environment configuration keys")
        values.update(overrides)
    for key in ("dev", "prod", "raw", "prod_results", "state"):
        values[key] = Path(values[key]).expanduser().resolve()
    if values["dev"] == values["prod"]:
        raise ValueError("Development and production worktrees must differ")
    dev_results = values["state"] / "dev/results"
    if dev_results == values["prod_results"] or (
        dev_results in values["prod_results"].parents
        or values["prod_results"] in dev_results.parents
    ):
        raise ValueError("Development and production result roots must not overlap")
    return values


def run(*args, cwd=None, capture=False):
    result = subprocess.run(
        list(map(str, args)), cwd=cwd, check=True, text=True, capture_output=capture
    )
    return result.stdout.strip() if capture else None


def git(root, *args):
    return run("git", "-C", root, *args, capture=True)


def environment(values, name):
    base = values["state"] / name
    cache = base / "cache"
    results = values["prod_results"] if name == "prod" else base / "results"
    preferences = (
        results / ".scmm-preferences.json" if name == "prod" else base / "preferences.json"
    )
    for path in (results, cache / "numba", cache / "matplotlib", base / "tmp"):
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        XDG_CACHE_HOME=str(cache),
        UV_CACHE_DIR=str(cache / "uv"),
        NUMBA_CACHE_DIR=str(cache / "numba"),
        MPLCONFIGDIR=str(cache / "matplotlib"),
        TMPDIR=str(base / "tmp"),
        SCMM_PREFERENCES=str(preferences),
        VIRTUAL_ENV=str(values[name] / ".venv"),
    )
    # Never allow a caller's Python path/environment to cross the worktree boundary.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env["PATH"] = str(values[name] / ".venv/bin") + os.pathsep + env["PATH"]
    return env, results


def sync(values, name):
    env, _ = environment(values, name)
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    subprocess.run(
        [uv, "sync", "--locked", "--all-extras", "--dev" if name == "dev" else "--no-dev"],
        cwd=values[name],
        env=env,
        check=True,
    )


def clean(root, branch):
    if git(root, "branch", "--show-current") != branch:
        raise RuntimeError(f"{root} must be on {branch}")
    if git(root, "status", "--porcelain"):
        raise RuntimeError(f"{root} has uncommitted files; commit or stash them first")


def idle(values):
    connections = run("ss", "-Htn", "state", "established", "( sport = :5006 )", capture=True)
    if connections:
        raise RuntimeError("5006 has browser connections; save and close production pages first")
    for path in values["prod_results"].rglob("state.json"):
        state = json.loads(path.read_text())
        if state.get("status") in {"queued", "running"}:
            raise RuntimeError(f"Unfinished production task: {path}; inspect it before deployment")
    # Detached workers can survive the server and must not read changing editable code.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
            if (
                any(
                    name in command
                    for name in (b"scMM.application.worker", b"scMM.application.project_batch")
                )
                and str(values["prod"]).encode() in command
            ):
                raise RuntimeError(f"Production worker still running: {entry.name}")
        except (OSError, ProcessLookupError):
            continue


def dev_idle():
    if run("ss", "-Hltn", "( sport = :5007 )", capture=True):
        raise RuntimeError(
            "Stop scmm-dev.service or foreground debugging before syncing/updating dev"
        )


def health():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:5006", timeout=2) as response:
                if (
                    response.status == 200
                    and b"scMM" in response.read()
                    and run("systemctl", "--user", "is-active", SERVICE, capture=True) == "active"
                ):
                    return
        except (OSError, urllib.error.URLError, subprocess.CalledProcessError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Production failed its HTTP/systemd health check")


def deploy(values, target, *, rollback=False):
    root = values["prod"]
    clean(root, "main")
    previous = git(root, "rev-parse", "HEAD")
    target = git(root, "rev-parse", "--verify", f"{target}^{{commit}}")
    if not rollback:
        git(root, "merge-base", "--is-ancestor", previous, target)
    idle(values)
    # The old revision remains recoverable even when local main moves backwards.
    git(root, "update-ref", "refs/scmm/recovery", previous)
    run("systemctl", "--user", "stop", SERVICE)
    try:
        if rollback:
            git(root, "reset", "--hard", target)
        else:
            git(root, "merge", "--ff-only", target)
        sync(values, "prod")
        run("systemctl", "--user", "start", SERVICE)
        health()
    except Exception:
        print("Deployment failed; restoring previous code and locked environment", file=sys.stderr)
        run("systemctl", "--user", "stop", SERVICE)
        git(root, "reset", "--hard", previous)
        sync(values, "prod")
        run("systemctl", "--user", "start", SERVICE)
        health()
        raise
    if previous != target:
        git(root, "update-ref", "refs/scmm/previous", previous)
    print(f"Production main: {target[:12]}; previous: {previous[:12]}")


def serve(values, name, *, debug=False):
    if debug and name != "dev":
        raise ValueError("Debugger is only available in the development environment")
    root = values[name]
    env, results = environment(values, name)
    args = [
        str(root / ".venv/bin/scmm-ui"),
        "--storage",
        f"原始数据={values['raw']}",
        "--isolated-storage",
        "--project-root",
        str(results),
        "--output",
        f"处理结果={results}",
        "--address",
        values["address"],
        "--port",
        "5006" if name == "prod" else "5007",
    ]
    for origin in values["origins"]:
        args.extend(["--allow-websocket-origin", origin])
    if debug:
        python = str(root / ".venv/bin/python")
        args = [python, "-m", "debugpy", "--listen", "127.0.0.1:5678", "--wait-for-client", *args]
    os.chdir(root)
    os.execve(args[0], args, env)


def unit_path(path):
    try:
        relative = Path(path).relative_to(Path.home())
    except ValueError:
        return str(path)
    return f"%h/{relative}"


def install(values, config):
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    script = Path.home() / ".local/share/scmm/scmm_env.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != script:
        shutil.copy2(__file__, script)
    for name, unit in (("prod", SERVICE), ("dev", "scmm-dev.service")):
        unit_text = f'''[Unit]
Description=scMM {name} web environment
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={unit_path(values[name])}
ExecStart=/usr/bin/python3 "{unit_path(script)}" --config "{unit_path(config)}" serve {name}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
'''
        path = unit_dir / unit
        if path.exists() and not path.with_suffix(".service.before-worktrees").exists():
            shutil.copy2(path, path.with_suffix(".service.before-worktrees"))
        path.write_text(unit_text)
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", SERVICE)
    print("Units installed; production restart and development start are explicit commands")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("serve", "sync", "update"):
        sub = commands.add_parser(command)
        sub.add_argument("name", choices=("dev", "prod"))
        if command == "serve":
            sub.add_argument(
                "--debug",
                action="store_true",
                help="Wait for a debugger on 127.0.0.1:5678 (dev only)",
            )
    commands.add_parser("install")
    commands.add_parser("status")
    commands.add_parser("release")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("revision", nargs="?", default="refs/scmm/previous")
    args = parser.parse_args()
    values = settings(args.config)
    if args.command == "serve":
        serve(values, args.name, debug=args.debug)
        return
    # Serialize deployment operations across both worktrees.
    values["state"].mkdir(parents=True, exist_ok=True)
    with (values["state"] / "environment.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "sync":
            if args.name == "prod":
                raise RuntimeError(
                    "Use update prod to sync a running production environment safely"
                )
            dev_idle()
            sync(values, args.name)
        elif args.command == "install":
            install(values, args.config.resolve())
        elif args.command == "status":
            print(git(values["dev"], "worktree", "list"))
            for unit in (SERVICE, "scmm-dev.service"):
                subprocess.run(["systemctl", "--user", "status", unit, "--no-pager"], check=False)
        elif args.command == "release":
            clean(values["dev"], "dev")
            deploy(values, "dev")
            # Only publish main after the local service has passed its health check.
            run("git", "-C", values["prod"], "push", "-u", "origin", "main")
        elif args.command == "rollback":
            deploy(values, args.revision, rollback=True)
            print("Local rollback only; remote main unchanged. update prod reapplies remote main.")
        elif args.command == "update":
            name = args.name
            clean(values[name], "dev" if name == "dev" else "main")
            if name == "dev":
                dev_idle()
            run("git", "-C", values[name], "fetch", "origin")
            if name == "prod":
                deploy(values, "origin/main")
            else:
                git(values[name], "merge", "--ff-only", "origin/dev")
                sync(values, name)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
