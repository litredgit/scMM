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


def setup_project(tmp_path, *, storage_label="data", sample_names=("a", "b")):
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
    catalog = StorageCatalog((StorageRoot(storage_label, tmp_path),))
    project.add_files(catalog, storage_label, ["a.mzML", "b.mzML"])
    for sample, name in zip(project.samples, sample_names, strict=True):
        sample["name"] = name
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
    project.samples[1]["parameters"] = dict(project.manifest["parameters"])
    request = preflight(project, catalog)
    assert [row["parameter_source"] for row in request["samples"]] == ["project", "sample"]
    assert request["samples"][0]["parameters"] == request["samples"][1]["parameters"]
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
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
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
    with path.with_name("shared_features.npy").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="Shared feature artifact changed"):
        submit(project, catalog, retry_path=path)


@pytest.mark.skipif(os.name != "posix", reason="Linux project workers")
def test_detached_batch_reads_unicode_request_under_ascii_locale(tmp_path, monkeypatch):
    project, catalog = setup_project(
        tmp_path, storage_label="原始数据", sample_names=("对照一", "处理一")
    )
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("PYTHONUTF8", "0")
    path = submit(project, catalog)
    deadline = time.monotonic() + 30
    while read_batch(path)["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.1)
    state = read_batch(path)
    assert state["status"] == "completed", (state, (path.parent / "worker.log").read_bytes())
    assert [row["name"] for row in state["samples"]] == ["对照一", "处理一"]


def test_retry_rejects_replaced_input_and_modified_success_artifact(tmp_path):
    from scMM.application.preview_cache import file_identity

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    for sample in request["samples"]:
        sample["input_identity"] = file_identity(sample["path"])
    request["created_at"] = "test"
    folder = project.folder / "processing" / "identity"
    folder.mkdir()
    write_json(folder / "request.json", request)
    state = folder / "state.json"
    run_batch(state)
    succeeded = read_batch(state)["samples"][0]
    output = folder / succeeded["output"]
    with output.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="artifact changed"):
        submit(project, catalog, retry_path=state)
    raw = tmp_path / "a.mzML"
    contents = raw.read_bytes()
    raw.unlink()
    raw.write_bytes(contents)
    with pytest.raises(ValueError, match="unchanged input"):
        submit(project, catalog, retry_path=state)


def test_frozen_input_changed_before_worker_does_not_extract(tmp_path):
    from scMM.application.preview_cache import file_identity

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    for sample in request["samples"]:
        sample["input_identity"] = file_identity(sample["path"])
    request["created_at"] = "test"
    folder = project.folder / "processing" / "changed"
    folder.mkdir()
    write_json(folder / "request.json", request)
    with (tmp_path / "a.mzML").open("a") as handle:
        handle.write("\n")
    run_batch(folder / "state.json")
    state = read_batch(folder / "state.json")
    assert state["status"] == "failed" and "Input changed" in state["message"]
    assert not list(folder.glob("*.h5ad"))


def test_frozen_input_changed_during_extraction_does_not_publish(tmp_path, monkeypatch):
    from scMM.application.preview_cache import file_identity
    from scMM.file.data import CyESIData

    project, catalog = setup_project(tmp_path)
    project.manifest["feature_strategy"] = "independent"
    request = preflight(project, catalog)
    for sample in request["samples"]:
        sample["input_identity"] = file_identity(sample["path"])
    request["created_at"] = "test"
    folder = project.folder / "processing" / "changed-during-extraction"
    folder.mkdir()
    write_json(folder / "request.json", request)
    original = CyESIData.load_from_file

    def changed(filename, *args, **kwargs):
        result = original(filename, *args, **kwargs)
        if str(filename) == project.samples[0]["path"]:
            with open(filename, "a") as handle:
                handle.write("\n")
        return result

    monkeypatch.setattr(CyESIData, "load_from_file", changed)
    run_batch(folder / "state.json")
    state = read_batch(folder / "state.json")
    assert state["samples"][0]["status"] == "failed"
    assert "Input changed" in state["samples"][0]["error"]
    assert not (folder / f"{project.samples[0]['id']}.h5ad").exists()
    assert state["samples"][1]["status"] == "succeeded"
