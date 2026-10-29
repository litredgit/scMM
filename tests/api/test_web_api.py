"""Exercise the HTTP boundary against real isolated project files and AnnData."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from fastapi.testclient import TestClient

from scMM.api.app import create_app
from scMM.application.storage import StorageRoot
from tests.support.auth import auth_options, login_client


@pytest.fixture
def api(tmp_path, monkeypatch):
    raw, projects, results = (tmp_path / name for name in ("raw", "projects", "results"))
    for folder in (raw, projects, results):
        folder.mkdir()
    for name in ("alpha.mzML", "beta.mzXML"):
        (raw / name).write_text("synthetic input; no extraction in this milestone")
    monkeypatch.setenv("SCMM_PREFERENCES", str(tmp_path / "preferences.json"))
    options, credential = auth_options(tmp_path)
    app = create_app(
        [StorageRoot("Raw", raw)],
        [StorageRoot("Results", results)],
        project_root=projects,
        static_root=None,
        **options,
    )
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        yield client, app.state.workspaces, raw, projects, results


def session(client):
    response = client.post("/api/v1/workspaces")
    assert response.status_code == 201, response.text
    return {"X-SCMM-Workspace": response.json()["workspace_id"]}


def create(client, headers, name="实验 A"):
    response = client.post(
        "/api/v1/workspace/project", headers=headers, json={"revision": 0, "name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add(client, headers, revision=1, paths=None):
    response = client.post(
        "/api/v1/workspace/samples",
        headers=headers,
        json={"revision": revision, "root": "Raw", "paths": paths or ["alpha.mzML", "beta.mzXML"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_workspace_isolation_revision_and_close(api):
    client, *_ = api
    a, b = session(client), session(client)
    state = create(client, a)
    assert client.get("/api/v1/workspace", headers=b).json()["project"] is None
    response = client.patch(
        "/api/v1/workspace/project",
        headers=a,
        json={"revision": 0, "name": "stale", "description": ""},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_revision"
    assert client.get("/api/v1/workspace", headers=a).json() == state
    assert client.delete("/api/v1/workspace", headers=a).status_code == 204
    assert client.get("/api/v1/workspace", headers=a).status_code == 404
    assert client.get("/api/v1/workspace", headers=b).status_code == 200


def test_add_and_edit_samples_are_transactional(api):
    client, *_ = api
    headers = session(client)
    create(client, headers)
    state = add(client, headers)
    failed = client.post(
        "/api/v1/workspace/samples",
        headers=headers,
        json={"revision": 2, "root": "Raw", "paths": ["alpha.mzML"]},
    )
    assert failed.status_code == 400
    samples = deepcopy(state["project"]["manifest"]["samples"])
    edits = [
        {key: sample[key] for key in ("id", "name", "group", "subject", "batch")}
        for sample in samples
    ]
    edits[1]["name"] = edits[0]["name"]
    failed = client.patch(
        "/api/v1/workspace/samples", headers=headers, json={"revision": 2, "samples": edits}
    )
    assert failed.status_code == 400
    assert client.get("/api/v1/workspace", headers=headers).json() == state
    edits[1].update(name="beta", group="treatment", subject="mouse-2")
    edited = client.patch(
        "/api/v1/workspace/samples", headers=headers, json={"revision": 2, "samples": edits}
    )
    assert edited.status_code == 200
    assert edited.json()["project"]["manifest"]["samples"][1]["subject"] == "mouse-2"


def test_batched_add_failure_does_not_add_first_file(api):
    client, *_ = api
    headers = session(client)
    state = create(client, headers)
    failed = client.post(
        "/api/v1/workspace/samples",
        headers=headers,
        json={"revision": 1, "root": "Raw", "paths": ["alpha.mzML", "missing.mzML"]},
    )
    assert failed.status_code == 404
    assert client.get("/api/v1/workspace", headers=headers).json() == state


def test_storage_boundaries_pagination_and_result_filters(api, tmp_path):
    client, _, raw, _, results = api
    (raw / "escape").symlink_to(tmp_path)
    (results / "data.h5ad").write_text("placeholder")
    (results / "not-result.txt").write_text("hidden")
    listed = client.get("/api/v1/storage/entries", params={"root": "Raw", "limit": 1}).json()
    assert listed["total"] == 2 and len(listed["entries"]) == 1
    assert (
        client.get("/api/v1/storage/entries", params={"root": "Raw", "path": ".."}).status_code
        == 403
    )
    assert (
        client.get("/api/v1/storage/entries", params={"root": "Raw", "path": "escape"}).status_code
        == 403
    )
    assert (
        client.get("/api/v1/storage/entries", params={"root": "Raw", "limit": 0}).status_code == 422
    )
    listed = client.get(
        "/api/v1/storage/entries", params={"root": "Results", "kind": "results"}
    ).json()
    assert [entry["name"] for entry in listed["entries"]] == ["data.h5ad"]


def test_save_roundtrip_and_other_session_conflict(api):
    client, *_ = api
    a, b = session(client), session(client)
    state = create(client, a)
    path = state["project"]["path"]
    response = client.post(
        "/api/v1/workspace/project/open", headers=b, json={"revision": 0, "path": path}
    )
    assert response.status_code == 200
    state = add(client, a)
    saved = client.post(
        "/api/v1/workspace/project/save", headers=a, json={"revision": state["revision"]}
    )
    assert saved.status_code == 200 and not saved.json()["project"]["unsaved"]
    stale = client.post("/api/v1/workspace/project/save", headers=b, json={"revision": 1})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "save_conflict"
    reopened = client.post(
        "/api/v1/workspace/project/open", headers=b, json={"revision": 1, "path": path}
    )
    assert len(reopened.json()["project"]["manifest"]["samples"]) == 2


def write_dataset(results, samples=("alpha", "beta")):
    data = AnnData(
        np.arange(1.0, 25.0).reshape(6, 4),
        obs=pd.DataFrame(
            {"sample": np.repeat(samples, 3), "group": ["control"] * 3 + ["case"] * 3},
            index=[f"c{i}" for i in range(6)],
        ),
    )
    data.write_h5ad(results / "input.h5ad")
    return data


def test_import_sync_baseline_and_preserve_unrelated_results(api):
    client, manager, _, _, results = api
    data = write_dataset(results)
    headers = session(client)
    create(client, headers)
    imported = client.post(
        "/api/v1/workspace/dataset/import",
        headers=headers,
        json={"revision": 1, "root": "Results", "path": "input.h5ad"},
    )
    assert imported.status_code == 200, imported.text
    state = imported.json()
    assert state["project"]["dataset"]["cells"] == 6
    assert len(state["project"]["manifest"]["samples"]) == 2
    sample = state["project"]["manifest"]["samples"][0]
    identity = headers["X-SCMM-Workspace"]
    with manager.access(identity) as workspace:
        project = workspace.project
        project.workspace.put_result(
            "differential", {"group_key": "group"}, project.workspace.token
        )
        project.workspace.put_result("network", {"edges": []}, project.workspace.token)
        project.saved_reports = {"differential": {"group_key": "group"}, "network": {"edges": []}}
        project.views = {"figures": {"volcano": "old", "network_plot": "retain"}}
    edits = {key: sample[key] for key in ("id", "name", "group", "subject", "batch")}
    edits.update(group="new-control", subject="animal-1")
    response = client.patch(
        "/api/v1/workspace/samples", headers=headers, json={"revision": 2, "samples": [edits]}
    )
    assert response.status_code == 200
    with manager.access(identity) as workspace:
        project = workspace.project
        assert set(project.workspace.results) == {"network"}
        assert set(project.saved_reports) == {"network"}
        assert project.views["figures"] == {"network_plot": "retain"}
        assert project.workspace._original.obs.loc["c0", "subject"] == "animal-1"
        assert project.workspace.data.obs.loc["c0", "group"] == "new-control"
        np.testing.assert_array_equal(project.workspace.data.X, data.X)


def test_failed_import_and_snapshot_preserve_current_state(api, monkeypatch):
    client, manager, _, _, results = api
    write_dataset(results)
    (results / "broken.h5ad").write_text("not HDF5")
    headers = session(client)
    state = create(client, headers)
    failed = client.post(
        "/api/v1/workspace/dataset/import",
        headers=headers,
        json={"revision": 1, "root": "Results", "path": "broken.h5ad"},
    )
    assert failed.status_code == 400
    assert client.get("/api/v1/workspace", headers=headers).json() == state
    client.post(
        "/api/v1/workspace/dataset/import",
        headers=headers,
        json={"revision": 1, "root": "Results", "path": "input.h5ad"},
    )
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        manifest = workspace.project.folder / "project.json"
        before = manifest.read_bytes()

        def fail(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(workspace.project.workspace, "save_h5ad", fail)
    failed = client.post("/api/v1/workspace/project/save", headers=headers, json={"revision": 2})
    assert failed.status_code == 400
    assert manifest.read_bytes() == before
    assert client.get("/api/v1/workspace", headers=headers).json()["revision"] == 2


def test_import_save_reopen_preserves_full_reset_point(api):
    client, manager, _, _, results = api
    original = write_dataset(results)
    headers = session(client)
    create(client, headers)
    state = client.post(
        "/api/v1/workspace/dataset/import",
        headers=headers,
        json={"revision": 1, "root": "Results", "path": "input.h5ad"},
    ).json()
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.project.workspace.filter(min_total=30)
    response = client.post("/api/v1/workspace/project/save", headers=headers, json={"revision": 2})
    assert response.status_code == 200, response.text
    path = state["project"]["path"]
    client.post(
        "/api/v1/workspace/project/open", headers=headers, json={"revision": 3, "path": path}
    )
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        assert workspace.project.workspace.data.n_obs < 6
        workspace.project.workspace.reset()
        np.testing.assert_array_equal(workspace.project.workspace.data.X, original.X)


def test_manual_mapping_and_invalid_target_are_atomic(api):
    client, _, _, _, results = api
    write_dataset(results, ("source-1", "source-2"))
    headers = session(client)
    create(client, headers)
    added = add(client, headers)
    state = client.post(
        "/api/v1/workspace/dataset/import",
        headers=headers,
        json={"revision": 2, "root": "Results", "path": "input.h5ad"},
    ).json()
    mapping = client.get("/api/v1/workspace/samples/mapping", headers=headers).json()
    assert mapping["rows"] == [
        {"value": "source-1", "sample_id": ""},
        {"value": "source-2", "sample_id": ""},
    ]
    failed = client.put(
        "/api/v1/workspace/samples/mapping",
        headers=headers,
        json={"revision": 3, "source_key": "sample", "mapping": {"source-1": "unknown"}},
    )
    assert failed.status_code == 400
    assert client.get("/api/v1/workspace", headers=headers).json() == state
    values = {
        f"source-{i + 1}": sample["id"]
        for i, sample in enumerate(added["project"]["manifest"]["samples"])
    }
    response = client.put(
        "/api/v1/workspace/samples/mapping",
        headers=headers,
        json={"revision": 3, "source_key": "sample", "mapping": values},
    )
    assert response.status_code == 200, response.text
    assert response.json()["project"]["manifest"]["sample_mapping"] == values


def test_csv_validation_remove_and_relocate_do_not_touch_raw(api):
    client, _, raw, _, _ = api
    headers = session(client)
    create(client, headers)
    state = add(client, headers)
    bad = client.post(
        "/api/v1/workspace/samples/csv",
        headers=headers,
        json={"revision": 2, "csv": "name,group\nalpha,ok\nmissing,fail"},
    )
    assert bad.status_code == 400
    assert client.get("/api/v1/workspace", headers=headers).json() == state
    response = client.post(
        "/api/v1/workspace/samples/csv",
        headers=headers,
        json={"revision": 2, "csv": "\ufeffname,group,subject\nalpha,对照,来源1\nbeta,处理,来源2"},
    )
    assert response.status_code == 200
    sample_id = state["project"]["manifest"]["samples"][0]["id"]
    (raw / "relocated.raw").write_text("synthetic")
    response = client.post(
        "/api/v1/workspace/samples/relocate",
        headers=headers,
        json={"revision": 3, "sample_id": sample_id, "root": "Raw", "path": "relocated.raw"},
    )
    assert response.status_code == 200
    response = client.post(
        "/api/v1/workspace/samples/remove",
        headers=headers,
        json={"revision": 4, "ids": [sample_id]},
    )
    assert response.status_code == 200
    assert len(list(raw.iterdir())) == 3


def test_parameter_help_uses_existing_defaults(api):
    client, manager, *_ = api
    config = client.get("/api/v1/configuration").json()
    values = {item["name"]: item for item in config["processing"]}
    assert (
        values["extraction_method"]["default"]
        == manager.defaults.processing.extraction_method
        == "snr_v1"
    )
    assert values["ref_mz"]["help"]
    assert config["project_root"] == str(manager.store.root)


def test_mutation_origin_and_strict_request_validation(api):
    client, *_ = api
    assert client.post("/api/v1/workspaces", headers={"X-SCMM-Client": ""}).status_code == 403
    assert (
        client.post("/api/v1/workspaces", headers={"Origin": "https://foreign.invalid"}).status_code
        == 403
    )
    headers = session(client)
    for body in ({"revision": True, "name": "test"}, {"revision": 0, "name": "test", "unknown": 1}):
        response = client.post("/api/v1/workspace/project", headers=headers, json=body)
        assert response.status_code == 422
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"
    assert client.get("/api/v1/not-a-route").status_code == 404


def test_expiry_capacity_and_concurrent_duplicate_revision(api):
    client, manager, *_ = api
    headers = session(client)
    state = create(client, headers)
    identity = headers["X-SCMM-Workspace"]

    def change(name):
        try:
            manager.edit_project(identity, state["revision"], name, "")
            return "ok"
        except RuntimeError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(change, ["one", "two"])) == ["conflict", "ok"]
    manager.capacity = 1
    assert client.post("/api/v1/workspaces").status_code == 503
    with manager.access(identity) as workspace:
        pass
    workspace.touched -= manager.idle_seconds + 1
    assert client.get("/api/v1/workspace", headers=headers).status_code == 404
    assert client.post("/api/v1/workspaces").status_code == 201


def test_static_routes_and_assets_are_served_without_api_fallback(api, tmp_path):
    _, manager, *_ = api
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>scMM Vue</html>")
    (static / "assets/app.js").write_text("console.log('scMM')")
    options, credential = auth_options(tmp_path)
    app = create_app(
        manager.storage.roots,
        project_root=manager.store.root,
        defaults=manager.defaults,
        static_root=static,
        **options,
    )
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        assert client.get("/samples").text == "<html>scMM Vue</html>"
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/v1/missing").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404
        assert "scMM Vue" not in client.get("/api/v1/missing").text


def test_explicit_trust_is_required_for_legacy_pickle(api):
    client, _, _, _, results = api
    legacy = results / "legacy"
    legacy.mkdir()
    (legacy / ".meta").write_text(json.dumps({}))
    (legacy / "data.pkl").write_bytes(b"must never be unpickled")
    headers = session(client)
    before = create(client, headers)
    response = client.post(
        "/api/v1/workspace/dataset/import",
        headers=headers,
        json={"revision": 1, "root": "Results", "path": "legacy"},
    )
    assert response.status_code == 403
    assert client.get("/api/v1/workspace", headers=headers).json() == before


def test_vue_cli_starts_without_panel_and_preserves_storage_options(api, monkeypatch):
    import sys

    import uvicorn

    from scMM.api import app as web_app
    from scMM.api.cli import main

    _, manager, raw, projects, results = api
    from scMM.application.monitor_store import MonitorStore
    from scMM.application.server_config import DEFAULTS

    monitor = MonitorStore.initialize(raw.parent / "monitor.sqlite3")
    config_path = raw.parent / "server.json"
    values = {
        **DEFAULTS,
        "auth_db": str(raw.parent / "auth.sqlite3"),
        "monitor_db": str(monitor.path),
        "project_root": str(projects),
        "storage": {"Raw": str(raw)},
        "output": {"Results": str(results)},
        "cache_root": str(results),
        "temp_root": str(results),
        "recycle_root": str(results),
        "preferences": str(projects / "preferences.json"),
        "cookie_secure": False,
    }
    config_path.write_text(json.dumps(values))
    import os

    monkeypatch.setattr(os, "environ", os.environ.copy())
    calls = []
    real_create = web_app.create_app
    monkeypatch.setenv("SCMM_PREFERENCES", str(projects / "preferences.json"))
    monkeypatch.setitem(sys.modules, "panel", None)
    monkeypatch.setattr(
        web_app,
        "create_app",
        lambda *args, **kwargs: real_create(*args, **kwargs, static_root=None),
    )
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    assert (
        main(
            [
                "--server-config",
                str(config_path),
                "--storage",
                f"Raw={raw}",
                "--output",
                f"Results={results}",
                "--project-root",
                str(projects),
                "--isolated-storage",
                "--port",
                "5118",
            ]
        )
        == 0
    )
    app, options = calls[0]
    assert options == {
        "host": "127.0.0.1",
        "port": 5118,
        "workers": 1,
        "proxy_headers": False,
        "timeout_graceful_shutdown": 15,
    }
    assert app.state.workspaces.store.root == manager.store.root
    assert [root.label for root in app.state.workspaces.storage.roots] == ["Raw"]


def test_scoped_artifact_cleanup_protects_live_and_disk_references(api, tmp_path):
    from pathlib import Path

    client, manager, *_ = api
    manager.trash_root = tmp_path / "scoped-trash"
    headers = session(client)
    create(client, headers)
    identity = headers["X-SCMM-Workspace"]
    with manager.access(identity) as workspace:
        project = workspace.project
        project.workspace.replace(AnnData(np.ones((3, 2))))
        manager.store.save(project)
        old_snapshot = project.folder / Path(project.manifest["artifacts"]["current"]).parent
        manager.store.save(project)
        current_snapshot = project.folder / Path(project.manifest["artifacts"]["current"]).parent
        old_batch = project.folder / "processing" / "old-batch"
        old_batch.mkdir()
        (old_batch / "request.json").write_text("{}")
        (old_batch / "state.json").write_text('{"status":"completed"}')
        project.workspace.source = str(old_batch / "state.json")

    def post(endpoint, **values):
        revision = client.get("/api/v1/workspace", headers=headers).json()["revision"]
        return client.post(
            "/api/v1/workspace" + endpoint, headers=headers, json={"revision": revision, **values}
        )

    listing = client.get("/api/v1/workspace/saved/artifacts?scope=snapshots", headers=headers)
    assert listing.status_code == 200, listing.text
    assert next(r for r in listing.json() if r["path"] == str(current_snapshot))["protection"]
    assert not next(r for r in listing.json() if r["path"] == str(old_snapshot))["protection"]
    assert post("/saved/plan", root="项目结果", path=str(old_batch), scope="batches").is_error
    assert post("/saved/plan", root="项目结果", path=str(project.folder), scope="batches").is_error
    plan = post("/saved/plan", root="项目结果", path=str(old_snapshot), scope="snapshots")
    assert plan.status_code == 200, plan.text
    # A late unsaved reference invalidates the reviewed plan even without a disk save.
    with manager.access(identity) as workspace:
        workspace.project.views["source"] = str(old_snapshot)
    assert post("/saved/move", token=plan.json()["token"]).is_error
    assert old_snapshot.exists()
    with manager.access(identity) as workspace:
        workspace.project.views.pop("source")
    plan = post("/saved/plan", root="项目结果", path=str(old_snapshot), scope="snapshots")
    moved = post("/saved/move", token=plan.json()["token"])
    assert moved.status_code == 200, moved.text
    assert not old_snapshot.exists() and current_snapshot.is_dir()
    assert post("/saved/restore", entry=moved.json()["entry"]).status_code == 200
    assert old_snapshot.is_dir()
    # An unsaved import into a different project also protects its source.
    imported = session(client)
    imported_state = create(client, imported, "另一个项目")
    with manager.access(imported["X-SCMM-Workspace"]) as peer:
        peer.project.workspace.replace(
            AnnData(np.ones((2, 2))), source=str(old_snapshot / "source.h5ad")
        )
    assert post("/saved/plan", root="项目结果", path=str(old_snapshot), scope="snapshots").is_error
    client.post(
        "/api/v1/workspace/project/close",
        headers=imported,
        json={"revision": imported_state["revision"]},
    ).raise_for_status()
    # A second workspace protects the entire project, including otherwise unused history.
    other = session(client)
    client.post(
        "/api/v1/workspace/project/open",
        headers=other,
        json={"revision": 0, "path": str(project.folder)},
    ).raise_for_status()
    assert post("/saved/plan", root="项目结果", path=str(old_snapshot), scope="snapshots").is_error


def test_two_batch_comparison_http_is_read_only_and_project_scoped(api):
    from scMM.application.projects import write_json

    client, manager, *_ = api
    headers = session(client)
    create(client, headers)
    identity = headers["X-SCMM-Workspace"]
    with manager.access(identity) as workspace:
        project = workspace.project
        paths = []
        for label in ("A", "B"):
            folder = project.folder / "processing" / label
            folder.mkdir()
            write_json(
                folder / "request.json",
                {
                    "parameters": {"cell_snr": 5},
                    "samples": [
                        {"id": "same-id", "name": "保留输入", "parameters": {}, "path": "/raw/test"}
                    ],
                },
            )
            write_json(
                folder / "state.json",
                {
                    "status": "failed",
                    "samples": [
                        {"id": "same-id", "status": "failed", "error": "synthetic failure"}
                    ],
                },
            )
            paths.append(str(folder / "state.json"))
        before = project.folder.joinpath("project.json").read_bytes()
    revision = client.get("/api/v1/workspace", headers=headers).json()["revision"]
    response = client.post(
        "/api/v1/workspace/extraction/compare",
        headers=headers,
        json={
            "revision": revision,
            "path_a": paths[0],
            "path_b": paths[1],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["samples"][0]["name_A"] == "保留输入"
    assert response.json()["warnings"]
    assert response.json()["figures"] == []
    current = client.get("/api/v1/workspace", headers=headers).json()
    assert current["revision"] == revision and current["project"]["dataset"] is None
    assert project.folder.joinpath("project.json").read_bytes() == before
    for body in (
        {"revision": revision - 1, "path_a": paths[0], "path_b": paths[1]},
        {"revision": revision, "path_a": paths[0], "path_b": "/other/state.json"},
        {"revision": revision, "path_a": paths[0], "path_b": paths[0]},
    ):
        assert client.post(
            "/api/v1/workspace/extraction/compare", headers=headers, json=body
        ).is_error
