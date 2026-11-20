"""HTTP migration parity, transactional state, task ownership and export boundaries."""

import time
from concurrent.futures import Future
from copy import deepcopy
from io import StringIO

import pandas as pd

from scMM.application.cell_preview import run_preview
from scMM.application.projects import write_json
from tests.support.workflow import get, import_data, raw_samples


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
        "/analysis/operation",
        {"operation": "cluster", "options": {"method": "kmeans", "unknown_parameter": 4}},
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


def test_stop_preview_blocks_collection_until_worker_reaches_safe_point(workflow, monkeypatch):
    sample = raw_samples(workflow)[0]
    post = workflow[-1]
    post("/raw/open", {"sample_id": sample["id"]}).raise_for_status()
    future = Future()
    future.set_running_or_notify_cancel()
    path = workflow[5] / "preview-state.json"
    write_json(path, {"status": "running", "message": "test"})
    monkeypatch.setattr("scMM.application.web_raw.submit_preview", lambda _: (future, path))
    job = post(
        "/raw/preview",
        {
            "sample_id": sample["id"],
            "parameters": workflow[6].manifest["parameters"],
        },
    ).json()["value"]
    assert get(workflow, "/tasks/active").json()["preview"]["id"] == job["id"]
    assert post("/raw/preview/stop", {"job_id": "old"}).status_code == 400
    response = post("/raw/preview/stop", {"job_id": job["id"]})
    assert response.json()["value"]["status"] == "stopping"
    future.set_result({})
    assert get(workflow, "/raw/preview").json()["status"] == "stopped"
    assert get(workflow, "/tasks/active").json()["preview"] is None
    assert post("/raw/preview/collect", {"job_id": job["id"]}).status_code == 400


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
    signal = workflow[-1]("/extraction/signal", {"path": path, "sample_id": ids[0]})
    assert signal.status_code == 200, signal.text
    assert len(signal.json()["value"]["figure"]["data"]) >= 3
    project = workflow[2]._workspaces[workflow[1]["X-SCMM-Workspace"]].project
    cells = project.workspace.data.obs_names[[0, -1]].tolist()
    for source in ("matrix", "window", "apex"):
        response = workflow[-1](
            "/analysis/cell-spectra",
            {"cells": cells, "source": source, "normalization": "max", "mirror": True},
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["value"]["data"]) == 2
        tables = response.json()["value"]["layout"]["meta"]["export_tables"]
        assert "1_source.csv" in tables and "2_display.csv" in tables
    assert get(workflow, "/results/download?kind=batch_log&key=/tmp/not-owned").status_code == 400
    assert get(workflow, f"/results/download?kind=batch_log&key={path}").status_code == 200


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


def test_vue_snr_only_rejects_unsupported_without_mutating_saved_project(workflow):
    samples = raw_samples(workflow)
    before = workflow[-2]()
    params = deepcopy(workflow[6].manifest["parameters"])
    params["extraction_method"] = "unsupported"
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
    assert workflow[-2]()["project"]["manifest"]["parameters"]["extraction_method"] == "unsupported"
    assert samples


def test_independent_raw_diagnostic_is_readonly_and_input_bound(workflow):
    samples = raw_samples(workflow)
    sample_id = samples[0]["id"]
    assert workflow[-1]("/raw/open", {"sample_id": sample_id}).status_code == 200
    before = workflow[-2]()
    options = {
        "sample_id": sample_id,
        "signal": "eic",
        "references": [150.0, 151.0],
        "baseline": "median",
        "window": 5,
    }

    def diagnostic(values):
        return workflow[0].post(
            "/api/v1/workspace/raw/diagnostic",
            headers=workflow[1],
            json={"revision": workflow[-2]()["revision"], **values},
        )

    response = diagnostic(options)
    assert response.status_code == 200, response.text
    value = response.json()["value"]
    assert value["table"]["total"] == 62
    meta = value["figure"]["layout"]["meta"]
    assert meta["provenance"]["sample_id"] == sample_id
    assert isinstance(meta["input_identity"]["mtime_ns"], str)
    exported = workflow[0].post(
        "/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": value["figure"]}
    )
    assert exported.status_code == 200
    assert "rank_residual" in meta["export_tables"]["diagnostic.csv"]
    after = workflow[-2]()
    assert after["revision"] == before["revision"] + 1
    assert after["project"]["manifest"]["parameters"] == before["project"]["manifest"]["parameters"]
    assert after["project"]["dataset"] is None
    before = after
    saved = get(workflow, f"/raw/diagnostic?sample_id={sample_id}")
    assert saved.json()["figure"] == value["figure"]
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert (
        get(workflow, f"/raw/diagnostic?sample_id={sample_id}").json()["figure"] == value["figure"]
    )
    assert workflow[-1]("/raw/open", {"sample_id": sample_id}).status_code == 200
    before = workflow[-2]()
    for change in (
        {"signal": ""},
        {"baseline": ""},
        {"window": 4},
        {"references": []},
        {"rt_range": [3.0, 1.0]},
        {"lam": -1},
    ):
        assert diagnostic({**options, **change}).status_code in {400, 422}
        assert workflow[-2]() == before
    with (workflow[3] / "a.mzML").open("a") as handle:
        handle.write("\n")
    assert diagnostic(options).status_code == 400
    assert (
        workflow[0]
        .post(
            "/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": value["figure"]}
        )
        .status_code
        == 400
    )


def test_raw_diagnostic_rechecks_input_after_numeric_work(workflow, monkeypatch):
    import scMM.analysis.signal_diagnostics as domain

    sample_id = raw_samples(workflow)[0]["id"]
    assert workflow[-1]("/raw/open", {"sample_id": sample_id}).status_code == 200
    before = workflow[-2]()
    original = domain.signal_diagnostics

    def changed(*args, **kwargs):
        output = original(*args, **kwargs)
        with (workflow[3] / "a.mzML").open("a") as handle:
            handle.write("\n")
        return output

    monkeypatch.setattr(domain, "signal_diagnostics", changed)
    response = workflow[0].post(
        "/api/v1/workspace/raw/diagnostic",
        headers=workflow[1],
        json={
            "revision": before["revision"],
            "sample_id": sample_id,
            "signal": "tic",
            "baseline": "zero",
        },
    )
    assert response.status_code == 400
    assert workflow[-2]() == before


def test_batch_matrix_http_download_before_review_and_project_isolation(workflow):
    import json

    from scMM.application.project_batch import preflight, run_batch
    from scMM.application.projects import write_json

    client, headers, manager, _, _, _, reference, current, post = workflow
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        project = workspace.project
        project.manifest["parameters"] = dict(reference.manifest["parameters"])
        project.add_files(manager.storage, "Raw", ["a.mzML", "b.mzML"])
        request = preflight(project, manager.storage)
        request["created_at"] = "2026-11-16T11:30:00Z"
        folder = project.folder / "processing" / "download"
        folder.mkdir()
        write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    path = str(folder / "state.json")
    before = current()
    info = client.get(
        "/api/v1/workspace/results/matrix",
        headers=headers,
        params={"source": "extracted", "batch_path": path},
    )
    assert info.status_code == 200 and info.json()["available"], info.text
    result = post("/results/matrix/download", {"source": "extracted", "batch_path": path})
    assert result.status_code == 200 and result.text.startswith("Sample,Label,")
    assert current() == before and current()["project"]["dataset"] is None
    result = post(
        "/results/matrix/download",
        {"source": "extracted", "batch_path": str(folder / "foreign.json")},
    )
    assert result.status_code == 400
    assert json.loads(json.dumps(current())) == before


def test_redetect_range_only_returns_a_form_candidate(workflow):
    current, post = workflow[-2:]
    assert post("/samples", {"root": "Raw", "paths": ["a.mzML"]}).status_code == 200
    sample = current()["project"]["manifest"]["samples"][0]["id"]
    assert post("/raw/open", {"sample_id": sample}).status_code == 200
    before = current()
    response = post("/raw/range", {"sample_id": sample})
    assert response.status_code == 200, response.text
    assert response.json()["value"]["range"] == [100, 200]
    assert current() == before
    assert post("/raw/range", {"sample_id": "unknown"}).status_code == 400
    assert current() == before
