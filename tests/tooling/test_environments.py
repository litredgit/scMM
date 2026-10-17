"""Exercise deployment recovery with real temporary Git worktrees, without services."""

import json
from pathlib import Path
from typing import ClassVar

import pytest

from scripts import scmm_env as manager


@pytest.fixture
def worktrees(tmp_path, monkeypatch):
    dev = tmp_path / "dev"
    prod = tmp_path / "prod"
    dev.mkdir()
    manager.run("git", "init", "-b", "dev", dev, capture=True)
    manager.git(dev, "config", "user.name", "Test")
    manager.git(dev, "config", "user.email", "test@example.invalid")
    (dev / "code.txt").write_text("old")
    manager.git(dev, "add", ".")
    manager.git(dev, "commit", "-m", "old")
    old = manager.git(dev, "rev-parse", "HEAD")
    manager.git(dev, "worktree", "add", "-b", "main", prod)
    (dev / "code.txt").write_text("new")
    manager.git(dev, "commit", "-am", "new")
    new = manager.git(dev, "rev-parse", "HEAD")
    values = {
        "dev": dev,
        "prod": prod,
        "prod_results": tmp_path / "results",
        "state": tmp_path / "state",
    }
    values["prod_results"].mkdir()
    service_calls = []
    real_run = manager.run

    def run(*args, **kwargs):
        if args[0] == "systemctl":
            service_calls.append(args[2:])
            return "active"
        if args[0] == "ss":
            return ""
        return real_run(*args, **kwargs)

    monkeypatch.setattr(manager, "run", run)
    monkeypatch.setattr(manager, "health", lambda: None)
    monkeypatch.setattr(manager, "web_idle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "sync", lambda *_: None)
    return values, old, new, service_calls


def test_release_rollback_and_reapply_keep_results(worktrees):
    values, old, new, calls = worktrees
    saved = values["prod_results"] / "saved.json"
    saved.write_text("keep")
    manager.deploy(values, "dev")
    assert manager.git(values["prod"], "rev-parse", "HEAD") == new
    assert manager.git(values["prod"], "rev-parse", "refs/scmm/previous") == old
    manager.deploy(values, "refs/scmm/previous", rollback=True)
    assert (values["prod"] / "code.txt").read_text() == "old"
    assert manager.git(values["prod"], "branch", "--show-current") == "main"
    manager.deploy(values, "dev")
    assert (values["prod"] / "code.txt").read_text() == "new"
    assert saved.read_text() == "keep"
    assert calls == [(action, manager.SERVICE) for action in ("stop", "start") * 3]


@pytest.mark.parametrize("failure", ["sync", "health"])
def test_failed_deployment_restores_code_and_restarts(worktrees, monkeypatch, failure):
    values, old, _, calls = worktrees
    attempts = []

    def fail_once(*_):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(manager, failure, fail_once)
    with pytest.raises(RuntimeError, match="simulated failure"):
        manager.deploy(values, "dev")
    assert manager.git(values["prod"], "rev-parse", "HEAD") == old
    assert manager.git(values["prod"], "rev-parse", "refs/scmm/recovery") == old
    assert (values["prod"] / "code.txt").read_text() == "old"
    assert calls[-1] == ("start", manager.SERVICE)
    assert len(attempts) == 2


def test_dirty_production_is_rejected_before_stopping(worktrees):
    values, _, _, calls = worktrees
    (values["prod"] / "code.txt").write_text("unsaved code")
    with pytest.raises(RuntimeError, match="uncommitted"):
        manager.deploy(values, "dev")
    assert calls == []
    assert (values["prod"] / "code.txt").read_text() == "unsaved code"


def test_active_task_or_browser_prevents_deployment(worktrees, monkeypatch):
    values, _, _, calls = worktrees
    state = values["prod_results"] / "state.json"
    state.write_text(json.dumps({"status": "running"}))
    with pytest.raises(RuntimeError, match="Unfinished production task"):
        manager.deploy(values, "dev")
    state.unlink()
    monkeypatch.setattr(manager, "run", lambda *_args, **_kwargs: "connected")
    with pytest.raises(RuntimeError, match="browser connections"):
        manager.idle(values)
    assert calls == []


def test_runtime_paths_and_preferences_are_isolated(worktrees, monkeypatch):
    values, *_ = worktrees
    monkeypatch.setenv("PYTHONPATH", "wrong/worktree")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "wrong/venv")
    prod_env, prod_results = manager.environment(values, "prod")
    dev_env, dev_results = manager.environment(values, "dev")
    assert prod_results != dev_results
    for key in (
        "VIRTUAL_ENV",
        "XDG_CACHE_HOME",
        "NUMBA_CACHE_DIR",
        "MPLCONFIGDIR",
        "TMPDIR",
        "SCMM_PREFERENCES",
    ):
        assert prod_env[key] != dev_env[key]
        assert Path(prod_env[key]).parent.exists()
        assert Path(dev_env[key]).parent.exists()
    assert "PYTHONPATH" not in dev_env
    assert "UV_PROJECT_ENVIRONMENT" not in prod_env
    assert prod_env["PYTHONUTF8"] == dev_env["PYTHONUTF8"] == "1"


def test_overlapping_results_are_rejected(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"state": str(tmp_path), "prod_results": str(tmp_path / "dev")}))
    with pytest.raises(ValueError, match="must not overlap"):
        manager.settings(config)


def test_development_update_guard_without_systemd(monkeypatch):
    monkeypatch.setattr(manager, "run", lambda *_args, **_kwargs: "LISTEN")
    with pytest.raises(RuntimeError, match="Stop scmm-dev"):
        manager.dev_idle()


def test_debug_launch_uses_development_interpreter_and_paths(worktrees, monkeypatch):
    values, *_ = worktrees
    values.update(raw=Path("/raw"), address="127.0.0.1")
    config = values["state"] / "dev.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{}")
    values["dev_server_config"] = config
    calls = []
    monkeypatch.setattr(manager.os, "chdir", lambda *_: None)
    monkeypatch.setattr(manager.os, "execve", lambda *args: calls.append(args))
    manager.serve(values, "dev", debug=True)
    executable, args, env = calls[0]
    assert executable == str(values["dev"] / ".venv/bin/python")
    assert args[1:6] == ["-m", "debugpy", "--listen", "127.0.0.1:5678", "--wait-for-client"]
    assert args[6] == str(values["dev"] / ".venv/bin/scmm-web")
    assert args[args.index("--port") + 1] == "5007"
    assert args[args.index("--server-config") + 1] == str(config)
    assert "SCMM_PREFERENCES" not in env
    with pytest.raises(ValueError, match="only available"):
        manager.serve(values, "prod", debug=True)


def test_home_paths_expand_for_preferences_and_systemd(tmp_path, monkeypatch):
    from scMM.application.preferences import preferences_path

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SCMM_PREFERENCES", raising=False)
    assert preferences_path() == tmp_path / "data/results/.scmm-preferences.json"
    monkeypatch.setenv("SCMM_PREFERENCES", "~/dev/preferences.json")
    assert preferences_path() == tmp_path / "dev/preferences.json"
    assert manager.unit_path(tmp_path / "scMM-prod") == "%h/scMM-prod"
    assert manager.unit_path(Path("/opt/scmm")) == "/opt/scmm"


def test_existing_vue_config_migrates_without_retaining_frontend_switches(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"prod_frontend": "vue", "dev_frontend": "vue", "origins": ["*"]}))
    values = manager.settings(config)
    assert not {"prod_frontend", "dev_frontend", "origins"} & values.keys()
    config.write_text(json.dumps({"prod_frontend": "panel"}))
    with pytest.raises(ValueError, match="Only Vue"):
        manager.settings(config)


@pytest.mark.parametrize("health", [[], {}, {"frontend": "unknown"}])
def test_invalid_health_never_assumes_idle(monkeypatch, health):
    from io import BytesIO

    class Response(BytesIO):
        headers: ClassVar[dict] = {"Content-Type": "application/json"}

    monkeypatch.setattr(
        manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps(health).encode()),
    )
    with pytest.raises(RuntimeError, match="invalid health response"):
        manager.web_idle(5006)


def test_vue_unsaved_workspaces_block_restart_without_sockets(monkeypatch):
    from io import BytesIO

    class Response(BytesIO):
        headers: ClassVar[dict] = {"Content-Type": "application/json"}

    replies = [{"frontend": "vue"}, {"unsaved_workspaces": 1, "busy_workspaces": 0}]
    monkeypatch.setattr(
        manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps(replies.pop(0)).encode()),
    )
    with pytest.raises(RuntimeError, match="monitoring protocol is unavailable"):
        manager.web_idle(5006)


def test_vue_missing_runtime_never_assumes_idle(monkeypatch):
    from io import BytesIO

    class Response(BytesIO):
        headers: ClassVar[dict] = {"Content-Type": "application/json"}

    def open_url(url, **_kwargs):
        if url.endswith("health"):
            return Response(b'{"frontend":"vue"}')
        raise OSError("connection lost")

    monkeypatch.setattr(manager.urllib.request, "urlopen", open_url)
    with pytest.raises(RuntimeError, match="Cannot verify Vue"):
        manager.web_idle(5006)


@pytest.mark.parametrize("status", [{}, [], {"unsaved_workspaces": 0, "busy_workspaces": False}])
def test_vue_invalid_runtime_never_assumes_idle(monkeypatch, status):
    from io import BytesIO

    class Response(BytesIO):
        headers: ClassVar[dict] = {"Content-Type": "application/json"}

    replies = [{"frontend": "vue"}, status]
    monkeypatch.setattr(
        manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps(replies.pop(0)).encode()),
    )
    with pytest.raises(RuntimeError, match="invalid runtime response"):
        manager.web_idle(5006)


@pytest.mark.parametrize(
    "change,allowed",
    [
        ({}, True),
        ({"active_pages": 1}, False),
        ({"unconfirmed_pages": 1}, False),
        ({"monitor_pages": 1}, True),
        ({"active_tasks": 1}, False),
        ({"open_projects": 1}, False),
        ({"sampled_at": 1}, False),
        ({"state": "unknown"}, False),
        ({"busy_workspaces": True}, False),
    ],
)
def test_update_gate_requires_fresh_explicit_page_evidence(monkeypatch, change, allowed):
    from io import BytesIO

    from scMM.application.monitor_presence import update_readiness

    class Response(BytesIO):
        headers: ClassVar[dict] = {"Content-Type": "application/json"}

    decision = update_readiness(pages=[], workspaces=[], tasks=[], sampled_at=manager.time.time())
    decision.update(change)
    replies = [
        {"frontend": "vue"},
        {
            "monitor_protocol": 1,
            "unsaved_workspaces": 0,
            "busy_workspaces": 0,
            "update_readiness": decision,
        },
    ]
    monkeypatch.setattr(
        manager.urllib.request,
        "urlopen",
        lambda *_a, **_k: Response(json.dumps(replies.pop(0)).encode()),
    )
    if allowed:
        manager.web_idle(5006)
    else:
        with pytest.raises(RuntimeError):
            manager.web_idle(5006)


@pytest.mark.parametrize(
    "state,allowed",
    [
        ({"unsaved_workspaces": 0, "busy_workspaces": 0}, True),
        ({"unsaved_workspaces": 1, "busy_workspaces": 0}, False),
        ({"unsaved_workspaces": 0, "busy_workspaces": False}, False),
        ({"unsaved_workspaces": 0, "busy_workspaces": 0, "monitor_protocol": 1}, False),
        (
            {
                "unsaved_workspaces": 0,
                "busy_workspaces": 0,
                "update_readiness": {"state": "unknown"},
            },
            False,
        ),
        ({}, False),
    ],
)
def test_first_migration_never_overrides_new_protocol_or_busy_state(monkeypatch, state, allowed):
    from io import BytesIO

    replies = [{"frontend": "vue"}, state]
    monkeypatch.setattr(
        manager.urllib.request,
        "urlopen",
        lambda *_a, **_k: BytesIO(json.dumps(replies.pop(0)).encode()),
    )
    if allowed:
        manager.legacy_web_idle()
    else:
        with pytest.raises(RuntimeError):
            manager.legacy_web_idle()


def test_migration_is_rejected_on_authenticated_revision(worktrees):
    values, *_ = worktrees
    module = values["prod"] / "scMM/application/auth.py"
    module.parent.mkdir(parents=True)
    module.write_text("existing authentication")
    with pytest.raises(RuntimeError, match="only allowed from the legacy"):
        manager.validate_auth_migration(values, "dev")


@pytest.mark.parametrize("failure", ["install", "sync", "health"])
def test_first_migration_failure_restores_legacy_launcher_and_code(worktrees, monkeypatch, failure):
    values, old, _, calls = worktrees
    home = values["state"] / "home"
    home.mkdir(parents=True)
    monkeypatch.setattr(manager.Path, "home", classmethod(lambda _cls: home))
    launcher = home / ".local/share/scmm/scmm_env.py"
    unit = home / ".config/systemd/user/scmm-ui.service"
    for path in (launcher, unit):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy")
        path.chmod(0o640)
    monkeypatch.setattr(manager, "validate_auth_migration", lambda *_: None)
    monkeypatch.setattr(manager, "legacy_web_idle", lambda: None)
    attempts = []

    def install(*_):
        launcher.write_text("new")
        unit.write_text("new")
        if failure == "install":
            raise RuntimeError("simulated migration failure")

    def fail_once(*_):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(manager, "install", install)
    if failure != "install":
        monkeypatch.setattr(manager, failure, fail_once)
    with pytest.raises(RuntimeError, match="simulated migration failure"):
        manager.deploy(values, "dev", migrate_auth=True)
    assert manager.git(values["prod"], "rev-parse", "HEAD") == old
    assert launcher.read_text() == unit.read_text() == "legacy"
    assert launcher.stat().st_mode & 0o777 == 0o640
    assert calls[-1] == ("start", manager.SERVICE)
    assert list(values["state"].glob("pre-auth-launchers-*/manifest.json"))
