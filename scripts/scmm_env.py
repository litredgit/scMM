#!/usr/bin/env python3
"""Manage two local worktrees without adding a separate deployment stack."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
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
        "dev_server_config": str(home / ".config/scmm/dev.json"),
        "prod_server_config": str(home / ".config/scmm/prod.json"),
    }
    if config.exists():
        overrides = json.loads(config.read_text(encoding="utf-8"))
        # Accept existing Vue deployment configs without retaining a frontend switch.
        for key in ("dev_frontend", "prod_frontend"):
            if overrides.pop(key, "vue") != "vue":
                raise ValueError("Only Vue is supported; remove obsolete frontend settings")
        overrides.pop("origins", None)  # Retired WebSocket configuration.
        if set(overrides) - set(values):
            raise ValueError("Unknown environment configuration keys")
        values.update(overrides)
    for key in (
        "dev",
        "prod",
        "raw",
        "prod_results",
        "state",
        "dev_server_config",
        "prod_server_config",
    ):
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


def environment(values, name, *, create=True):
    base = values["state"] / name
    cache = base / "cache"
    results = values["prod_results"] if name == "prod" else base / "results"
    preferences = (
        results / ".scmm-preferences.json" if name == "prod" else base / "preferences.json"
    )
    if create:
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
        PYTHONUTF8="1",
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
    frontend = values[name] / "frontend"
    if (frontend / "package-lock.json").is_file():
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError("Node.js/npm is required to build the Vue frontend")
        subprocess.run([npm, "ci"], cwd=frontend, env=env, check=True)
        subprocess.run([npm, "run", "build"], cwd=frontend, env=env, check=True)


def clean(root, branch):
    if git(root, "branch", "--show-current") != branch:
        raise RuntimeError(f"{root} must be on {branch}")
    if git(root, "status", "--porcelain"):
        raise RuntimeError(f"{root} has uncommitted files; commit or stash them first")


def web_idle(port, token_file=None):
    """Vue workspaces have no long-lived socket; ask the API before restarting."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/health", timeout=2
        ) as response:
            if response.headers.get("Content-Type", "").startswith("application/json"):
                health = json.load(response)
            else:
                raise ValueError("Unexpected health response")
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot verify web workspace state") from exc
    if not isinstance(health, dict) or health.get("frontend") != "vue":
        raise RuntimeError("Cannot verify Vue workspace state: invalid health response")
    try:
        headers = {}
        if token_file is not None:
            token_path = Path(token_file)
            if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
                raise RuntimeError("Operations token file must be private and not a symlink")
            headers["Authorization"] = "Bearer " + token_path.read_text().strip()
        url = f"http://127.0.0.1:{port}/api/v1/runtime"
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers) if headers else url, timeout=2
        ) as response:
            status = json.load(response)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot verify Vue workspace state") from exc
    if not isinstance(status, dict) or any(
        type(status.get(key)) is not int or status[key] < 0
        for key in ("unsaved_workspaces", "busy_workspaces")
    ):
        raise RuntimeError("Cannot verify Vue workspace state: invalid runtime response")
    decision = status.get("update_readiness")
    if not isinstance(decision, dict) or status.get("monitor_protocol") != 1:
        raise RuntimeError("Page activity cannot be verified: monitoring protocol is unavailable")
    for key in ("checked_at", "sampled_at"):
        value = decision.get(key)
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not -5 <= time.time() - value <= 15
        ):
            raise RuntimeError("Page activity cannot be verified: monitoring sample expired")
    fields = (
        "active_pages",
        "unconfirmed_pages",
        "monitor_pages",
        "unsaved_workspaces",
        "busy_workspaces",
        "unconfirmed_workspaces",
        "active_tasks",
        "inflight_requests",
        "open_projects",
    )
    if any(type(decision.get(k)) is not int or decision[k] < 0 for k in fields):
        raise RuntimeError("Invalid page activity counters")
    if any(
        not isinstance(decision.get(k), list) or any(not isinstance(s, str) for s in decision[k])
        for k in ("blockers", "unknown")
    ):
        raise RuntimeError("Invalid monitoring reasons")
    if (
        decision.get("state") != "ready"
        or any(decision[k] for k in fields if k != "monitor_pages")
        or decision["blockers"]
        or decision["unknown"]
        or status["unsaved_workspaces"]
        or status["busy_workspaces"]
    ):
        raise RuntimeError(
            f"{port} has active pages, unsaved or busy workspaces, tasks, or unconfirmed state; save and close them first"
        )


def legacy_web_idle():
    """Only for an explicitly coordinated, first authentication migration."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:5006/api/v1/health", timeout=2) as response:
            health = json.load(response)
        with urllib.request.urlopen("http://127.0.0.1:5006/api/v1/runtime", timeout=2) as response:
            state = json.load(response)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot verify legacy service for migration") from exc
    if (
        not isinstance(health, dict)
        or health.get("frontend") != "vue"
        or not isinstance(state, dict)
        or "monitor_protocol" in state
        or "update_readiness" in state
        or any(
            type(state.get(k)) is not int or state[k] != 0
            for k in ("unsaved_workspaces", "busy_workspaces")
        )
    ):
        raise RuntimeError(
            "Migration requires an idle legacy service; cannot override monitoring evidence"
        )


def validate_auth_migration(values, target):
    if (values["prod"] / "scMM/application/auth.py").exists():
        raise RuntimeError("Authentication migration is only allowed from the legacy revision")
    git(values["prod"], "cat-file", "-e", f"{target}:scMM/application/auth.py")
    config = values.get("prod_server_config")
    if not config or not Path(config).is_file():
        raise RuntimeError("Initialize the independent production resource config before migration")
    # Use the target-compatible development interpreter, never the legacy production environment.
    run(
        values["dev"] / ".venv/bin/python",
        "-c",
        """
import sys
from pathlib import Path
from scMM.application.server_config import load_server_config
prod = load_server_config(sys.argv[1]).validate()
dev = load_server_config(sys.argv[2]).validate()
if prod.values['environment'] != 'prod' or prod.values['port'] != 5006:
    raise ValueError('Production environment/port mismatch')
if Path(prod.values['project_root']).resolve() != Path(sys.argv[3]).resolve():
    raise ValueError('Production project root must preserve the configured result directory')
for key in ('auth_db', 'monitor_db', 'preferences', 'cache_root', 'temp_root'):
    if Path(prod.values[key]).resolve() == Path(dev.values[key]).resolve():
        raise ValueError('Production private resources must be independent of development')
if prod.cookie_name == dev.cookie_name:
    raise ValueError('Production and development must use different cookie names')
""",
        config,
        values["dev_server_config"],
        values["prod_results"],
        cwd=values["dev"],
    )


def backup_launchers(values):
    directory = Path(tempfile.mkdtemp(prefix="pre-auth-launchers-", dir=values["state"]))
    home = Path.home()
    paths = [
        home / ".local/share/scmm/scmm_env.py",
        home / ".config/systemd/user/scmm-ui.service",
        home / ".config/systemd/user/scmm-dev.service",
    ]
    records = []
    for i, path in enumerate(paths):
        if path.is_symlink():
            raise RuntimeError("Migration startup files must not be symlinks")
        exists = path.exists()
        record = {
            "path": str(path),
            "exists": exists,
            "mode": path.stat().st_mode & 0o777 if exists else None,
        }
        if exists:
            backup = directory / str(i)
            backup.write_bytes(path.read_bytes())
            backup.chmod(0o600)
        records.append(record)
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(records), encoding="utf-8")
    manifest.chmod(0o600)
    print(f"Legacy launcher backup: {directory}")
    return directory


def restore_launchers(directory):
    records = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for i, item in enumerate(records):
        path = Path(item["path"])
        if item["exists"]:
            path.write_bytes((directory / str(i)).read_bytes())
            path.chmod(item["mode"])
        else:
            path.unlink(missing_ok=True)
    run("systemctl", "--user", "daemon-reload")


def idle(values, *, migrate_auth=False):
    config = values.get("prod_server_config")
    token_file = Path(config).with_suffix(".operations-token") if config else None
    if migrate_auth:
        legacy_web_idle()
    else:
        web_idle(5006, token_file=token_file)
    connections = run("ss", "-Htn", "state", "established", "( sport = :5006 )", capture=True)
    if connections:
        raise RuntimeError("5006 has browser connections; save and close production pages first")
    for path in values["prod_results"].rglob("state.json"):
        state = json.loads(path.read_text(encoding="utf-8"))
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


def deploy(values, target, *, rollback=False, migrate_auth=False, config=CONFIG):
    root = values["prod"]
    clean(root, "main")
    previous = git(root, "rev-parse", "HEAD")
    target = git(root, "rev-parse", "--verify", f"{target}^{{commit}}")
    if not rollback:
        git(root, "merge-base", "--is-ancestor", previous, target)
    launchers = None
    if migrate_auth:
        if rollback:
            raise RuntimeError("Authentication migration cannot be combined with rollback")
        validate_auth_migration(values, target)
        idle(values, migrate_auth=True)
        launchers = backup_launchers(values)
    else:
        idle(values)
    # The old revision remains recoverable even when local main moves backwards.
    git(root, "update-ref", "refs/scmm/recovery", previous)
    run("systemctl", "--user", "stop", SERVICE)
    try:
        if migrate_auth:
            install(values, config)
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
        if launchers:
            restore_launchers(launchers)
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
    config_path = Path(
        values.get(f"{name}_server_config", Path.home() / f".config/scmm/{name}.json")
    )
    if not config_path.is_file():
        raise RuntimeError(
            "Initialize the external server config with scmm-admin init before starting"
        )
    env, _ = environment(values, name, create=False)
    # Resource paths are resolved by scmm-web with its documented precedence.
    # Do not inject the old deployment layout as environment overrides.
    env.pop("SCMM_PREFERENCES", None)
    args = [
        str(root / ".venv/bin/scmm-web"),
        "--server-config",
        str(config_path),
        "--port",
        "5006" if name == "prod" else "5007",
    ]
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
Environment=PYTHONUTF8=1
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
    release = commands.add_parser("release")
    release.add_argument(
        "--migrate-auth",
        action="store_true",
        help="First legacy migration only: operator has coordinated a maintenance window and saved/closed all production pages",
    )
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
            deploy(values, "dev", migrate_auth=args.migrate_auth, config=args.config.resolve())
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
