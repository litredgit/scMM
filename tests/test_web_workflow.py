"""HTTP migration parity, transactional state, task ownership and export boundaries."""
# ruff: noqa: RUF001

import json
import time
from concurrent.futures import Future
from copy import deepcopy
from io import StringIO

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad
from fastapi.testclient import TestClient
from test_project_batch import setup_project

from scMM.api.app import create_app
from scMM.application.cell_preview import run_preview
from scMM.application.projects import write_json
from scMM.application.storage import StorageRoot
from scMM.application.trash import SavedItems


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    raw, output, projects = [tmp_path / name for name in ("raw", "output", "projects")]
    for folder in (raw, output, projects):
        folder.mkdir()
    reference, _ = setup_project(raw)
    reference.manifest["parameters"].update(extraction_method="snr_v1", reference_ppm_tol=50.0)
    monkeypatch.setenv("SCMM_PREFERENCES", str(tmp_path / "preferences.json"))
    app = create_app(
        [StorageRoot("Raw", raw)],
        [StorageRoot("Output", output)],
        project_root=projects,
        static_root=None,
    )
    manager = app.state.workspaces
    monkeypatch.setattr(
        manager,
        "saved_items",
        lambda: SavedItems(
            manager.store,
            [StorageRoot("Output", output)],
            active_paths=manager.active_paths,
            trash_root=tmp_path / "trash",
        ),
    )
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        identity = client.post("/api/v1/workspaces").json()["workspace_id"]
        headers = {"X-SCMM-Workspace": identity}
        client.post(
            "/api/v1/workspace/project",
            headers=headers,
            json={"revision": 0, "name": "HTTP workflow"},
        ).raise_for_status()

        def current():
            return client.get("/api/v1/workspace", headers=headers).json()

        def post(path, values=None, method="POST"):
            return client.request(
                method,
                f"/api/v1/workspace{path}",
                headers=headers,
                json={"revision": current()["revision"], **(values or {})},
            )

        yield client, headers, manager, raw, output, projects, reference, current, post


def import_data(workflow):
    _, _, _, _, output, _, _, _, post = workflow
    rng = np.random.default_rng(12)
    data = AnnData(
        rng.uniform(1, 10, (64, 8)),
        obs=pd.DataFrame(
            {
                "sample": np.repeat([f"s{i}" for i in range(8)], 8),
                "group": ["a"] * 32 + ["b"] * 32,
                "subject": np.repeat([f"s{i}" for i in range(8)], 8),
            },
            index=[f"c{i}" for i in range(64)],
        ),
        var=pd.DataFrame({"mz": np.arange(8.0) + 150}, index=[f"f{i}" for i in range(8)]),
    )
    data.X[:32, 0] *= 5
    data.write_h5ad(output / "data.h5ad")
    result = post("/dataset/import", {"root": "Output", "path": "data.h5ad"})
    assert result.status_code == 200, result.text
    return data


def get(workflow, path):
    return workflow[0].get(f"/api/v1/workspace{path}", headers=workflow[1])


def operation(workflow, name, options=None, preview=False):
    result = workflow[-1](
        "/analysis/operation", {"operation": name, "options": options or {}, "preview": preview}
    )
    assert result.status_code == 200, result.text
    return result.json()


def raw_samples(workflow):
    post = workflow[-1]
    assert post("/samples", {"root": "Raw", "paths": ["a.mzML", "b.mzML"]}).status_code == 200
    params = workflow[6].manifest["parameters"]
    assert post("/parameters", {"parameters": params}, "PUT").status_code == 200
    return workflow[-2]()["project"]["manifest"]["samples"]


def test_qc_candidate_apply_failure_history_and_complete_reset(workflow):
    data = import_data(workflow)
    before = workflow[-2]()
    qc = get(workflow, "/analysis/qc").json()
    assert qc["cells"]["total"] == 64
    candidate = operation(workflow, "normalize", {"method": "total"}, preview=True)
    assert candidate["workspace"] == before
    assert workflow[-2]() == before
    operation(workflow, "filter", {"min_total": float(np.median(data.X.sum(axis=1)))})
    assert workflow[-2]()["project"]["dataset"]["cells"] < 64
    current = workflow[-2]()
    failure = workflow[-1](
        "/analysis/operation", {"operation": "filter", "options": {"min_total": 1e9}}
    )
    assert failure.status_code == 400
    assert workflow[-2]() == current
    operation(workflow, "normalize", {"method": "total"})
    history = get(workflow, "/analysis").json()["history"]
    assert [row["operation"] for row in history] == ["filter", "normalize"]
    operation(workflow, "reset")
    restored = get(workflow, "/results/download?kind=matrix").text
    np.testing.assert_allclose(pd.read_csv(StringIO(restored), index_col=0).to_numpy(), data.X)


def test_analysis_plots_results_staleness_and_saved_report_reload(workflow):
    import_data(workflow)
    operation(workflow, "reduce", {"method": "pca", "store_key": "X_pca"})
    operation(workflow, "cluster", {"method": "kmeans", "key": "clusters", "n_clusters": 2})
    current = workflow[-2]()
    failure = workflow[-1](
        "/analysis/operation",
        {"operation": "reduce", "options": {"method": "pca", "store_key": "X_pca"}},
    )
    assert failure.status_code == 400 and workflow[-2]() == current
    operation(workflow, "differential", {"group_key": "group", "group_a": "a", "group_b": "b"})
    operation(workflow, "markers", {"group_key": "clusters"})
    operation(workflow, "network", {"top_features": 5, "min_abs_correlation": 0.2})
    for kind, options in [
        ("embedding", {"key": "X_pca", "color": "feature:f0"}),
        ("volcano", {}),
        ("violin", {"features": ["f0"], "hide_zero": True}),
        ("network_plot", {}),
    ]:
        response = workflow[-1]("/analysis/plot", {"kind": kind, "options": options})
        assert response.status_code == 200, response.text
        assert response.json()["value"]["data"]
    assert (
        get(workflow, "/analysis/results/differential?offset=2&limit=2").json()["table"]["total"]
        == 8
    )
    complete = get(workflow, "/analysis/results/differential?limit=100").json()["table"]["rows"]
    assert (
        get(workflow, "/analysis/results/differential?offset=2&limit=2").json()["table"]["rows"]
        == complete[2:4]
    )
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert "differential" in get(workflow, "/analysis").json()["results"]
    assert get(workflow, "/results/download?kind=differential").status_code == 200
    assert workflow[-1]("/analysis/plot", {"kind": "volcano"}).status_code == 200
    operation(workflow, "normalize", {"method": "total"})
    assert get(workflow, "/analysis").json()["embeddings"] == []
    assert get(workflow, "/results/download?kind=differential").status_code == 400
    assert get(workflow, "/results/download?kind=figure&key=volcano").status_code == 400


@pytest.mark.filterwarnings(
    "ignore:The set_(bad|under|over) function will be deprecated:PendingDeprecationWarning:shap.plots.colors._colors"
)
def test_supervised_grouped_cv_shap_and_readonly_reload(workflow):
    import_data(workflow)
    operation(
        workflow,
        "train",
        {
            "label_key": "group",
            "group_key": "subject",
            "model": "lda",
            "cv": 2,
            "test_size": 0.5,
            "calibration_bins": 2,
        },
    )
    result = get(workflow, "/analysis/results/supervised").json()
    assert set(result["train_obs"]).isdisjoint(result["test_obs"])
    train_groups = {int(name[1:]) // 8 for name in result["train_obs"]}
    test_groups = {int(name[1:]) // 8 for name in result["test_obs"]}
    assert train_groups.isdisjoint(test_groups)
    for kind in ("roc", "pr", "calibration"):
        assert workflow[-1]("/analysis/plot", {"kind": kind}).status_code == 200
    operation(workflow, "save_latent", {"key": "X_latent"})
    assert "X_latent" in get(workflow, "/analysis").json()["embeddings"]
    operation(workflow, "explain_shap", {"max_background": 4, "max_samples": 2})
    assert get(workflow, "/analysis/results/shap").json()["table"]["total"] == 8
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    info = get(workflow, "/analysis").json()
    assert not info["live_results"] and not info["latent_supported"]
    assert workflow[-1]("/analysis/plot", {"kind": "roc"}).status_code == 200
    failure = workflow[-1]("/analysis/operation", {"operation": "explain_shap"})
    assert failure.status_code == 400
    assert get(workflow, "/results/download?kind=supervised").status_code == 200


def test_strict_parameters_options_and_preview_state(workflow):
    samples = raw_samples(workflow)
    before = workflow[-2]()
    invalid = workflow[-1]("/parameters", {"parameters": {"ref_mz": -1.0}}, "PUT")
    assert invalid.status_code == 400 and workflow[-2]() == before
    params = deepcopy(workflow[6].manifest["parameters"])
    params["cell_snr"] = 6.0
    assert (
        workflow[-1](
            "/parameters", {"parameters": params, "sample_id": samples[0]["id"]}, "PUT"
        ).status_code
        == 200
    )
    assert get(workflow, f"/parameters?sample_id={samples[0]['id']}").json()["cell_snr"] == 6.0
    assert workflow[-1]("/parameters/clear", {"sample_id": samples[0]["id"]}).status_code == 200
    assert get(workflow, f"/parameters?sample_id={samples[0]['id']}").json()["cell_snr"] == 5.0
    import_data(workflow)
    current = workflow[-2]()
    bad = workflow[-1](
        "/analysis/operation", {"operation": "cluster", "options": {"method": "kmeans", "eps": 4}}
    )
    assert bad.status_code == 422 and workflow[-2]() == current
    bad = workflow[-1]("/analysis/plot", {"kind": "violin", "options": {"features": ["f0"] * 13}})
    assert bad.status_code == 422


def test_raw_plots_full_csv_identity_and_cross_workspace(workflow):
    samples = raw_samples(workflow)
    opened = workflow[-1]("/raw/open", {"sample_id": samples[0]["id"]})
    assert opened.status_code == 200, opened.text
    assert opened.json()["value"]["summary"]["scan_count"] == 31
    for kind in ("tic", "eic", "sum", "single"):
        response = workflow[0].post(
            "/api/v1/workspace/raw/plot",
            headers=workflow[1],
            json={
                "sample_id": samples[0]["id"],
                "kind": kind,
                "references": [150.0],
                "mz_range": [140.0, 160.0],
                "bins": 300,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["figure"]["data"]
        assert get(workflow, f"/results/download?kind=raw&key={kind}").status_code == 200
    csv = get(workflow, "/results/download?kind=raw&key=tic").text
    assert len(pd.read_csv(StringIO(csv))) == 31
    other = workflow[0].post("/api/v1/workspaces").json()["workspace_id"]
    assert (
        workflow[0]
        .get(
            "/api/v1/workspace/results/download?kind=raw&key=tic",
            headers={"X-SCMM-Workspace": other},
        )
        .status_code
        == 400
    )
    with (workflow[3] / "a.mzML").open("a") as handle:
        handle.write("\n")
    assert get(workflow, "/results/download?kind=raw&key=tic").status_code == 400


def test_preview_actual_spawn_and_stale_revision(workflow):
    samples = raw_samples(workflow)
    assert workflow[-1]("/raw/open", {"sample_id": samples[0]["id"]}).status_code == 200
    start = workflow[-1](
        "/raw/preview",
        {"sample_id": samples[0]["id"], "parameters": workflow[6].manifest["parameters"]},
    )
    assert start.status_code == 200, start.text
    job = start.json()["value"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = get(workflow, "/raw/preview").json()
        if status["status"] in {"ready", "failed"}:
            break
        time.sleep(0.03)
    assert status["status"] == "ready", status
    assert workflow[0].get("/api/v1/health").status_code == 200
    collected = workflow[-1]("/raw/preview/collect", {"job_id": job["id"]})
    assert collected.status_code == 200, collected.text
    assert collected.json()["value"]["cell_count"] == 2
    assert workflow[-2]()["project"]["dataset"] is None
    assert workflow[-2]()["project"]["manifest"]["samples"][0]["preview"]["artifact"]


def test_preview_old_parameters_never_apply(workflow, monkeypatch):
    samples = raw_samples(workflow)
    assert workflow[-1]("/raw/open", {"sample_id": samples[0]["id"]}).status_code == 200
    future = Future()
    requests = []

    def submit(request):
        requests.append(request)
        path = workflow[5] / "preview-state.json"
        write_json(path, {"status": "queued", "message": "test"})
        return future, path

    monkeypatch.setattr("scMM.application.web_raw.submit_preview", submit)
    start = workflow[-1](
        "/raw/preview",
        {"sample_id": samples[0]["id"], "parameters": workflow[6].manifest["parameters"]},
    )
    assert start.status_code == 200
    job = start.json()["value"]
    assert (
        workflow[-1](
            "/raw/preview",
            {"sample_id": samples[0]["id"], "parameters": workflow[6].manifest["parameters"]},
        ).status_code
        == 400
    )
    future.set_result(
        run_preview({**requests[0], "created_at": "test"}, workflow[5] / "finished-state.json")
    )
    changed = deepcopy(workflow[6].manifest["parameters"])
    changed["cell_snr"] = 6.0
    assert workflow[-1]("/parameters", {"parameters": changed}, "PUT").status_code == 200
    before = workflow[-2]()
    assert workflow[-1]("/raw/preview/collect", {"job_id": job["id"]}).status_code == 400
    assert workflow[-2]() == before


def test_detached_extraction_preflight_review_and_retry_identity(workflow):
    samples = raw_samples(workflow)
    checked = workflow[-1]("/extraction/preflight")
    assert checked.status_code == 200
    assert workflow[-2]()["project"]["dataset"] is None
    started = workflow[-1]("/extraction/start")
    assert started.status_code == 200, started.text
    path = started.json()["value"]["path"]
    assert workflow[-2]()["project"]["dataset"] is None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batches = get(workflow, "/extraction/batches").json()
        if batches[0]["status"] not in {"queued", "running"}:
            break
        time.sleep(0.05)
    assert batches[0]["status"] == "completed", batches
    ids = [s["id"] for s in samples]
    before = workflow[-2]()
    compared = workflow[-1]("/extraction/review", {"path": path, "ids": ids, "compare": True})
    assert compared.status_code == 200, compared.text
    assert compared.json()["value"]["cells"] == 4
    assert workflow[-2]() == before
    assert workflow[-1]("/extraction/review", {"path": path, "ids": ids}).status_code == 200
    assert workflow[-2]()["project"]["dataset"]["cells"] == 4
    assert get(workflow, "/results/download?kind=batch_log&key=/tmp/not-owned").status_code == 400
    assert get(workflow, f"/results/download?kind=batch_log&key={path}").status_code == 200


def test_export_snapshot_and_shared_recycle_protections(workflow):
    data = import_data(workflow)
    assert workflow[-1]("/project/save").status_code == 200
    response = workflow[-1]("/results/export", {"root": "Output", "filename": "export.h5ad"})
    assert response.status_code == 200, response.text
    np.testing.assert_array_equal(read_h5ad(response.json()["value"]["path"]).X, data.X)
    assert (
        workflow[-1]("/results/export", {"root": "Output", "filename": "export.h5ad"}).status_code
        == 400
    )
    assert (
        workflow[-1](
            "/results/export", {"root": "Output", "filename": "../escape.h5ad"}
        ).status_code
        == 400
    )
    assert get(workflow, "/results/download?kind=snapshot&filename=data.h5ad").content.startswith(
        b"\x89HDF"
    )
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/saved/plan", {"root": "项目结果", "path": path}).status_code == 409
    assert workflow[-1]("/project/close").status_code == 200
    plan = workflow[-1]("/saved/plan", {"root": "项目结果", "path": path})
    assert plan.status_code == 200, plan.text
    assert workflow[-1]("/saved/move", {"token": plan.json()["token"]}).status_code == 200
    trash = get(workflow, "/saved/trash").json()
    assert len(trash) == 1
    assert workflow[-1]("/saved/restore", {"entry": trash[0]["entry"]}).status_code == 200
    assert not get(workflow, "/saved/trash").json()
    assert workflow[-1]("/saved/clear").json() == 0


def test_runtime_detects_unsaved_busy_and_clean_sessions(workflow):
    client, _, manager, *_ = workflow
    assert client.get("/api/v1/runtime").json()["unsaved_workspaces"] == 0
    raw_samples(workflow)
    assert client.get("/api/v1/runtime").json()["unsaved_workspaces"] == 1
    assert workflow[-1]("/project/save").status_code == 200
    assert client.get("/api/v1/runtime").json()["unsaved_workspaces"] == 0
    assert manager.runtime()["busy_workspaces"] == 0


def test_panel_saved_view_compatibility_and_independent_legends(workflow):
    import_data(workflow)
    identity = workflow[1]["X-SCMM-Workspace"]
    manager = workflow[2]
    with manager.access(identity) as workspace:
        workspace.project.views = {
            "settings": {
                "reduction": "pca",
                "embedding_key": "X_old",
                "color": "feature:f1",
                "cv": 2,
            },
            "figures": {
                "roc": json.dumps(
                    {"data": [{"type": "scatter", "x": [0, 1], "y": [0, 1]}], "layout": {}}
                )
            },
        }
        workspace.project.saved_reports = {"supervised": {"diagnostics": {"test_accuracy": 1.0}}}
    info = get(workflow, "/analysis").json()
    assert info["settings"]["reduction"]["store_key"] == "X_old"
    assert info["settings"]["colorSource"] == "feature"
    figure = workflow[-1]("/analysis/plot", {"kind": "roc"}).json()["value"]
    assert isinstance(figure, dict) and figure["data"]
    assert get(workflow, "/analysis/figures/roc").json() == figure
    assert get(workflow, "/analysis").json()["figures"] == ["roc"]
    downloaded = get(workflow, "/results/download?kind=figure&key=roc&filename=roc.json")
    assert downloaded.status_code == 200 and downloaded.json() == figure
    assert (
        workflow[-1](
            "/presentation", {"key": "analysis.roc", "position": "hidden"}, "PUT"
        ).status_code
        == 200
    )
    assert workflow[-2]()["project"]["presentation"] == {"analysis.roc": "hidden"}
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert workflow[-2]()["project"]["presentation"] == {"analysis.roc": "hidden"}


def test_failed_batch_submission_keeps_saved_workspace_revision_consistent(workflow, monkeypatch):
    raw_samples(workflow)

    def fail(*_args, **_kwargs):
        raise OSError("cannot start worker")

    monkeypatch.setattr("scMM.application.web_raw.submit", fail)
    before = workflow[-2]()
    response = workflow[-1]("/extraction/start")
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "extraction_not_started"
    )
    current = workflow[-2]()
    assert current["revision"] == before["revision"] + 1
    assert not current["project"]["unsaved"]
    assert workflow[-1]("/project/save").status_code == 200


def test_qc_stable_total_axis_preserves_precision_zeros_and_file_identity(workflow):
    data = import_data(workflow)
    data.X[0] = 0
    data.obs["source_file"] = ["/a/same.raw"] * 32 + ["/b/same.raw"] * 32
    data.write_h5ad(workflow[4] / "data.h5ad")
    assert (
        workflow[-1]("/dataset/import", {"root": "Output", "path": "data.h5ad"}).status_code == 200
    )
    operation(workflow, "normalize", {"method": "total"})
    result = get(workflow, "/analysis/qc").json()
    assert result["figure"]["layout"]["xaxis"]["range"] == [-0.05, 1.05]
    assert result["figure"]["layout"]["yaxis"]["dtick"] == 1
    traces = result["figure"]["data"]
    assert [t["name"] for t in traces] == ["same.raw（1）", "same.raw（2）"]
    assert {t["customdata"][0][0] for t in traces} == {"/a/same.raw", "/b/same.raw"}
    values = np.array([r["total_intensity"] for r in result["cells"]["rows"]])
    assert values[0] == 0
    np.testing.assert_allclose(values[1:], 1, rtol=0, atol=1e-14)
    exported = pd.read_csv(
        StringIO(get(workflow, "/results/download?kind=qc").text), float_precision="round_trip"
    )["total_intensity"].to_numpy()
    assert np.any(exported[1:] != 1)  # Actual exported totals retain the summation differences.
    operation(workflow, "normalize", {"method": "log"})
    changed = get(workflow, "/analysis/qc").json()
    assert "range" not in changed["figure"]["layout"]["xaxis"]
    assert all(r["detected_features"] == data.n_vars for r in changed["cells"]["rows"])


def test_result_browser_latest_snapshot_excludes_baseline_and_caches(workflow):
    import_data(workflow)
    assert workflow[-1]("/project/save").status_code == 200
    view = workflow[-2]()["project"]
    project = workflow[2].store.open(view["path"])
    preview = project.folder / "processing" / "preview-new"
    preview.mkdir()
    AnnData(np.ones((2, 2))).write_h5ad(preview / "data.h5ad")
    response = workflow[0].get(
        "/api/v1/storage/entries", params={"root": "项目结果", "kind": "results"}
    )
    assert response.status_code == 200, response.text
    latest = response.json()["latest"]
    assert latest["role"] == "当前快照"
    assert latest["path"].endswith(project.manifest["artifacts"]["current"])
    assert latest["project_name"] == project.manifest["name"]
    browse = {"root": "项目结果", "kind": "results", "path": view["path"]}
    entries = workflow[0].get("/api/v1/storage/entries", params=browse).json()["entries"]
    assert all(not e["internal"] for e in entries)
    entries = (
        workflow[0]
        .get("/api/v1/storage/entries", params={**browse, "include_internal": True})
        .json()["entries"]
    )
    assert {e["name"] for e in entries} >= {"processing", "snapshots"}
    assert any(e["role"] == "当前快照目录" for e in entries)


def test_vue_snr_only_rejects_legacy_without_mutating_saved_project(workflow):
    samples = raw_samples(workflow)
    before = workflow[-2]()
    params = deepcopy(workflow[6].manifest["parameters"])
    params["extraction_method"] = "legacy"
    rejected = workflow[-1]("/parameters", {"parameters": params}, "PUT")
    assert rejected.status_code == 400 and "snr" in rejected.text
    assert workflow[-2]() == before
    # Old projects remain readable, but a new batch requires explicit SNR parameters.
    folder = workflow[2].store._folder(before["project"]["path"])
    manifest = workflow[2].store._manifest(folder)
    manifest["parameters"] = params
    write_json(folder / "project.json", manifest)
    assert workflow[-1]("/project/open", {"path": str(folder)}).status_code == 200
    assert workflow[-1]("/extraction/preflight").status_code == 400
    assert workflow[-1]("/extraction/start").status_code == 400
    assert not list((folder / "processing").glob("*/request.json"))
    assert workflow[-2]()["project"]["manifest"]["parameters"]["extraction_method"] == "legacy"
    assert samples


def test_latest_export_and_foreign_project_are_classified_without_cross_root_open(workflow):
    import os

    from scMM.application.projects import ProjectStore

    import_data(workflow)
    assert workflow[-1]("/project/save").status_code == 200
    folder = workflow[2].store._folder(workflow[-2]()["project"]["path"])
    export = folder / "exports" / "last-export.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(export)
    future = time.time() + 60
    os.utime(export, (future, future))
    current = (
        workflow[0]
        .get("/api/v1/storage/entries", params={"root": "项目结果", "kind": "results"})
        .json()
    )
    assert current["latest"]["name"] == "last-export.h5ad"
    assert current["latest"]["role"] == "独立导出 H5AD"
    foreign_store = ProjectStore(workflow[4])
    foreign = foreign_store.create("other environment")
    foreign.workspace.replace(AnnData(np.ones((2, 2))))
    foreign_store.save(foreign)
    listing = (
        workflow[0]
        .get("/api/v1/storage/entries", params={"root": "Output", "kind": "results"})
        .json()
    )
    item = next(e for e in listing["entries"] if e["name"] == foreign.folder.name)
    assert item["project_name"] == "other environment"
    assert item["project_path"] is None
    assert "所属环境" in item["protection"]
    assert workflow[-1]("/project/open", {"path": str(foreign.folder)}).status_code == 403
