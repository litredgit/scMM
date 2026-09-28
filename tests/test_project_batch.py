import json
import os
import time
from dataclasses import asdict

import numpy as np
import pyopenms as oms
import pytest

from scMM.application import StorageCatalog, StorageRoot
from scMM.application.processing import ProcessingParameters
from scMM.application.project_batch import (
    preflight,
    read_batch,
    reviewed_dataset,
    run_batch,
    submit,
)
from scMM.application.projects import ProjectStore, write_json
from scMM.file.io import save_spectra


def setup_project(tmp_path):
    spectra = []
    for i in range(31):
        s = oms.MSSpectrum()
        s.setMSLevel(1)
        s.setRT(float(i))
        s.set_peaks(
            (np.array([149.9, 150.0, 150.1]), np.array([0.0, 20.0 if i in {8, 22} else 1.0, 0.0]))
        )
        spectra.append(s)
    save_spectra(spectra, tmp_path / "a.mzML")
    save_spectra(spectra, tmp_path / "b.mzML")
    store = ProjectStore(tmp_path)
    project = store.create("batch")
    catalog = StorageCatalog((StorageRoot("data", tmp_path),))
    project.add_files(catalog, "data", ["a.mzML", "b.mzML"])
    project.manifest["parameters"] = asdict(
        ProcessingParameters(
            ref_mz=150.0,
            mz_min=140.0,
            mz_max=160.0,
            resolution=5000.0,
            resample_points_per_fwhm=2.0,
            ppm_tol=500.0,
            baseline_filter_size=5,
        )
    )
    return project, catalog


@pytest.mark.parametrize("strategy", ["shared", "independent"])
def test_batch_real_mzml_review_and_stop(tmp_path, strategy):
    project, catalog = setup_project(tmp_path)
    project.manifest["feature_strategy"] = strategy
    request = preflight(project, catalog)
    request["created_at"] = "test"
    folder = project.folder / "processing" / "test"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    state = read_batch(folder / "state.json")
    assert state["status"] == "completed", state
    assert [r["status"] for r in state["samples"]] == ["succeeded", "succeeded"], state
    data = reviewed_dataset(folder / "state.json", [s["id"] for s in project.samples])
    assert data.n_obs == 4
    assert data.obs["sample_id"].nunique() == 2
    assert (data.var.mz.between(140, 160)).all()
    (folder / "stop.requested").touch()
    run_batch(folder / "state.json")
    assert read_batch(folder / "state.json")["status"] == "stopped"


def test_failure_continues_and_shared_parameters_checked(tmp_path):
    project, catalog = setup_project(tmp_path)
    project.samples[1]["parameters"] = {**project.manifest["parameters"], "ppm_tol": 400.0}
    with pytest.raises(ValueError, match="Shared feature"):
        preflight(project, catalog)
    project.samples[1]["parameters"] = None
    request = preflight(project, catalog)
    request["created_at"] = "test"
    request["samples"][0]["path"] = str(tmp_path / "missing.mzML")
    folder = project.folder / "processing" / "test"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    state = json.loads((folder / "state.json").read_text())
    assert [r["status"] for r in state["samples"]] == ["failed", "succeeded"], state


@pytest.mark.skipif(os.name != "posix", reason="Linux project workers")
def test_detached_batch_and_retry_reuse_successes(tmp_path):
    project, catalog = setup_project(tmp_path)
    path = submit(project, catalog)
    deadline = time.monotonic() + 30
    while read_batch(path)["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.1)
    state = read_batch(path)
    assert state["status"] == "completed", state
    assert all(row["status"] == "succeeded" for row in state["samples"]), state
    # Simulate a recorded per-sample failure; the retry must retain the other output.
    state["samples"][1]["status"] = "failed"
    write_json(path, state)
    retry = submit(project, catalog, retry_path=path)
    deadline = time.monotonic() + 30
    while read_batch(retry)["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.1)
    retried = read_batch(retry)
    assert retried["status"] == "completed", retried
    assert all(row["status"] == "succeeded" for row in retried["samples"]), retried
    first_name = state["samples"][0]["output"]
    assert (path.parent / first_name).read_bytes() == (retry.parent / first_name).read_bytes()
    assert (path.parent / "shared_features.npy").read_bytes() == (
        retry.parent / "shared_features.npy"
    ).read_bytes()
