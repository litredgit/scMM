"""Explicit initialization, resource precedence and optional dependency boundaries."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scMM.api.admin_cli import main
from scMM.application.auth import AuthStore
from scMM.application.server_config import DEFAULTS, load_server_config


@pytest.fixture
def resources(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for name in list(os.environ):
        if name.startswith("SCMM_"):
            monkeypatch.delenv(name)
    folders = {key: tmp_path / key for key in ("raw", "project", "cache", "tmp", "recycle")}
    for folder in folders.values():
        folder.mkdir()
    auth, _ = AuthStore.initialize(tmp_path / "private/auth.sqlite3", "admin")
    from scMM.application.monitor_store import MonitorStore

    monitor = MonitorStore.initialize(tmp_path / "private/monitor.sqlite3")
    config = tmp_path / "private/server.json"
    values = {
        **DEFAULTS,
        "auth_db": str(auth.path),
        "monitor_db": str(monitor.path),
        "project_root": str(folders["project"]),
        "storage": {"Raw": str(folders["raw"])},
        "cache_root": str(folders["cache"]),
        "temp_root": str(folders["tmp"]),
        "recycle_root": str(folders["recycle"]),
        "preferences": str(tmp_path / "private/preferences.json"),
        "cookie_secure": False,
    }
    config.write_text(json.dumps(values))
    return config, values, folders


def test_resource_precedence_and_no_implicit_storage(resources, monkeypatch):
    path, _, folders = resources
    assert load_server_config(path).validate().values["port"] == 5006
    monkeypatch.setenv("SCMM_PORT", "5008")
    monkeypatch.setenv("SCMM_ADDRESS", "127.0.0.2")
    cfg = load_server_config(path, {"port": 5009}).validate()
    assert cfg.values["port"] == 5009 and cfg.values["address"] == "127.0.0.2"
    assert cfg.values["storage"] == {"Raw": str(folders["raw"])}
    assert cfg.values["output"] == {}
    monkeypatch.setenv("SCMM_STORAGE_ROOTS", json.dumps({"Only": str(folders["raw"])}))
    assert list(load_server_config(path).values["storage"]) == ["Only"]


def test_bad_config_or_explicit_path_never_falls_back(resources, monkeypatch):
    path, values, folders = resources
    with pytest.raises(ValueError, match="不存在"):
        load_server_config(path.with_name("absent.json"))
    values["processing"] = {}
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="实验参数"):
        load_server_config(path)
    del values["processing"]
    path.write_text(json.dumps(values))
    monkeypatch.setenv("SCMM_PROJECT_ROOT", str(folders["project"] / "absent"))
    with pytest.raises(FileNotFoundError):
        load_server_config(path).validate()
    assert not (folders["project"] / "absent").exists()


def test_credentials_must_be_outside_browsable_paths_and_git(resources, tmp_path):
    path, values, folders = resources
    values["storage"] = {"TooBroad": str(tmp_path)}
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="可浏览"):
        load_server_config(path).validate()
    repo = folders["raw"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    config = repo / "server.json"
    config.write_text(json.dumps({**values, "storage": {"Raw": str(repo)}}))
    with pytest.raises(ValueError, match="Git 工作区"):
        load_server_config(config).validate()


def test_optional_paths_checked_only_at_use_and_never_switch(resources, monkeypatch):
    from scMM.application.lipid_database import database_root, database_status
    from scMM.file.readers.thermo_raw import ThermoRawError, reader_command

    path, values, _ = resources
    cfg = load_server_config(path).validate()
    cfg.apply()
    with pytest.raises(ValueError, match="未配置"):
        database_root()
    assert database_status()["error"]
    with pytest.raises(ThermoRawError, match="未配置"):
        reader_command()
    values["lipid_database_dir"] = str(path.parent / "missing-db")
    values["thermo_reader"] = str(path.parent / "missing-reader")
    path.write_text(json.dumps(values))
    cfg = load_server_config(path).validate()
    cfg.apply()
    with pytest.raises(FileNotFoundError):
        database_root()
    with pytest.raises(ThermoRawError):
        reader_command()
    assert not Path(values["lipid_database_dir"]).exists()


def test_init_is_explicit_non_overwriting_and_private(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    raw = tmp_path / "raw"
    raw.mkdir()
    config = tmp_path / "private/server.json"
    args = [
        "--server-config",
        str(config),
        "init",
        "--admin",
        "owner",
        "--auth-db",
        str(config.parent / "auth.sqlite3"),
        "--project-root",
        str(tmp_path / "output"),
        "--storage",
        f"Raw={raw}",
        "--insecure-cookie",
        "--cache-root",
        str(tmp_path / "cache"),
        "--temp-root",
        str(tmp_path / "tmp"),
        "--recycle-root",
        str(tmp_path / "recycle"),
        "--preferences",
        str(config.parent / "preferences.json"),
    ]
    assert main(args) == 0
    cfg = load_server_config(config).validate()
    for file in (
        config,
        cfg.auth_db,
        config.with_suffix(".initial.txt"),
        config.with_suffix(".operations-token"),
    ):
        assert file.stat().st_mode & 0o077 == 0
    old = cfg.auth_db.read_bytes()
    with pytest.raises(SystemExit):
        main(args)
    assert cfg.auth_db.read_bytes() == old
    store = AuthStore(cfg.auth_db)
    initial = config.with_suffix(".initial.txt").read_text().strip()
    store.login("owner", initial, "local")
    recovered = config.parent / "recovered.txt"
    assert (
        main(
            [
                "--server-config",
                str(config),
                "reset-password",
                "owner",
                "--credential-file",
                str(recovered),
            ]
        )
        == 0
    )
    store.login("owner", recovered.read_text().strip(), "local")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:5006",
        "http://example.com:5006",
        "http://127.0.0.1:5006/path",
        "http://127.0.0.1:5006?token=value",
        "http://" + "user:pass@" + "127.0.0.1:5006",
        "http://127.0.0.1:5007",
    ],
)
def test_peer_probe_rejects_nonlocal_ambiguous_or_self_targets(resources, url):
    path, values, _ = resources
    values.update(port=5007, monitor_peer_url=url)
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        load_server_config(path)


def test_existing_auth_config_monitor_migration_does_not_change_accounts(resources):
    path, values, _ = resources
    original = Path(values["auth_db"]).read_bytes()
    values.update(monitor_db=None, port=5007)
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="init-monitor"):
        load_server_config(path).validate()
    target = path.parent / "new-monitor.sqlite3"
    args = [
        "--server-config",
        str(path),
        "init-monitor",
        "--monitor-db",
        str(target),
        "--environment",
        "dev",
        "--monitor-peer-url",
        "http://127.0.0.1:5006",
    ]
    assert main(args) == 0
    assert load_server_config(path).validate().values["environment"] == "dev"
    assert target.stat().st_mode & 0o077 == 0
    assert Path(values["auth_db"]).read_bytes() == original
    with pytest.raises(ValueError, match="拒绝覆盖"):
        main(args)
