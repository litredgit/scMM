import json
import os
import time

import pytest

from scMM.application.project_batch import (
    preflight,
    read_batch,
    reviewed_dataset,
    run_batch,
    submit,
)
from scMM.application.projects import write_json
from scMM.util.intensity import intensity_states
from tests.support.project import setup_project


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
    assert state["stage"] == "review"
    assert state["started_at"] <= state["updated_at"] == state["finished_at"]
    assert [r["status"] for r in state["samples"]] == ["succeeded", "succeeded"], state
    assert all(r["progress"] == 1 and r["stage"] == "completed" for r in state["samples"])
    data = reviewed_dataset(folder / "state.json", [s["id"] for s in project.samples])
    assert data.n_obs == 4
    assert data.obs["sample_id"].nunique() == 2
    assert (data.var.mz.between(140, 160)).all()
    assert intensity_states(data)["X"] == "raw"
    (folder / "stop.requested").touch()
    run_batch(folder / "state.json")
    assert read_batch(folder / "state.json")["status"] == "stopped"


@pytest.mark.parametrize("strategy", ["shared", "independent"])
@pytest.mark.parametrize("method", ["snr_v1"])
def test_batch_uses_per_sample_net_signal_gate(tmp_path, strategy, method):
    project, catalog = setup_project(tmp_path)
    project.manifest["feature_strategy"] = strategy
    project.manifest["parameters"].update(
        extraction_method=method, cell_min_signal=18, reference_ppm_tol=500.0
    )
    project.samples[1]["parameters"] = {**project.manifest["parameters"], "cell_min_signal": 19}
    request = preflight(project, catalog)
    request["created_at"] = "test"
    folder = project.folder / "processing" / "gate"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    state = read_batch(folder / "state.json")
    assert state["status"] == "completed", state
    assert [row["status"] for row in state["samples"]] == ["succeeded", "failed"], state
    assert state["samples"][0]["cells"] == 2
    assert state["samples"][1]["error"] == "No cells or features retained"


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


def test_two_batch_comparison_matches_ids_and_preserves_inputs(tmp_path):
    import numpy as np
    from anndata import AnnData

    from scMM.application.batch_comparison import compare_batches
    from scMM.application.preview_cache import digest_file

    paths = []
    for index, cells in enumerate((2, 3)):
        folder = tmp_path / f"batch-{index}"
        folder.mkdir()
        data = AnnData(np.arange(cells * 2, dtype=float).reshape(cells, 2))
        data.obs_names = [f"c{i}" for i in range(cells)]
        data.write_h5ad(folder / "sample.h5ad")
        write_json(
            folder / "request.json",
            {
                "parameters": {"cell_snr": 5 + index},
                "feature_strategy": "shared",
                "samples": [
                    {
                        "id": "stable",
                        "name": "中文输入",
                        "path": "/raw/file",
                        "input_identity": {"sha": "same"},
                        "parameters": {"cell_snr": 5 + index},
                    }
                ],
            },
        )
        write_json(
            folder / "state.json",
            {
                "status": "completed",
                "samples": [
                    {
                        "id": "stable",
                        "status": "succeeded",
                        "cells": cells,
                        "features": 2,
                        "output": "sample.h5ad",
                        "sha256": digest_file(folder / "sample.h5ad"),
                    }
                ],
            },
        )
        paths.append(folder / "state.json")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = compare_batches(*paths)
    assert result["samples"][0]["input"] == "same"
    assert result["samples"][0]["cell_difference"] == 1
    assert result["samples"][0]["name_A"] == "中文输入"
    assert result["qc"].groupby("comparison_batch").size().to_dict() == {"A": 2, "B": 3}
    assert len([r for r in result["parameters"] if r["changed"]]) == 2
    assert all(path.read_bytes() == value for path, value in before.items())
    with pytest.raises(ValueError, match="不同"):
        compare_batches(paths[0], paths[0])
    request = json.loads(paths[1].with_name("request.json").read_text(encoding="utf-8"))
    request["samples"][0].pop("input_identity")
    write_json(paths[1].with_name("request.json"), request)
    unknown = compare_batches(*paths)
    assert unknown["samples"][0]["input"] == "unknown"
    assert unknown["samples"][0]["cell_difference"] is None
    assert unknown["warnings"]
    # Digest mismatch removes only that side's QC and reports the missing evidence.
    paths[1].with_name("sample.h5ad").write_bytes(b"changed")
    broken = compare_batches(*paths)
    assert set(broken["qc"].comparison_batch) == {"A"}
    assert any("摘要" in warning for warning in broken["warnings"])
    write_json(paths[1], {"status": "running", "samples": []})
    with pytest.raises(ValueError, match="结束"):
        compare_batches(*paths)


def test_batch_export_without_current_dataset_is_scoped_and_readonly(tmp_path):
    import numpy as np

    from scMM.application.matrix_export import export_matrix

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    request["created_at"] = "2026-11-16T11:30:00Z"
    folder = project.folder / "processing" / "export"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    token = project.workspace.token
    data = export_matrix(project, "extracted", batch_path=str(folder / "state.json"))
    expected = reviewed_dataset(folder / "state.json", [s["id"] for s in project.samples])
    np.testing.assert_array_equal(data.X, expected.X)
    assert project.workspace.data is None and project.workspace.token == token
    with pytest.raises(ValueError, match="不属于"):
        export_matrix(project, "extracted", batch_path=str(tmp_path / "foreign/state.json"))
    with pytest.raises(ValueError, match="只有提取"):
        export_matrix(project, "current", batch_path=str(folder / "state.json"))
    state = read_batch(folder / "state.json")
    state["status"] = "running"
    state["pid"] = None
    write_json(folder / "state.json", state)
    with pytest.raises(ValueError, match="停止"):
        export_matrix(project, "extracted", batch_path=str(folder / "state.json"))


def test_target_list_quantifies_off_reference_and_preserves_full_spectrum(tmp_path):
    import numpy as np
    import pyopenms as oms

    from scMM.application import mz_lists
    from scMM.application.extraction_spectra import describe_profile
    from scMM.application.preview_cache import save_preview, signature
    from scMM.application.processing import ProcessingParameters
    from scMM.application.projects import ProjectStore
    from scMM.application.raw_preview import RawPreviewService
    from scMM.file.io import save_spectra

    project, catalog = setup_project(tmp_path)
    spectra = []
    for frame in range(31):
        scan = oms.MSSpectrum()
        scan.setMSLevel(1)
        scan.setRT(frame)
        peak = frame in {8, 22}
        scan.set_peaks(
            (
                np.array([149.9, 150, 150.1, 154.9, 155, 155.1]),
                np.array([0, 20 if peak else 1, 0, 0, 40 if peak else 2, 0], dtype=float),
            )
        )
        spectra.append(scan)
    for sample in project.samples:
        save_spectra(spectra, sample["path"])
    wet_list = mz_lists.imported(
        project,
        "target.csv",
        "targets",
        'mz,note\n155,"a,b"\n157,absent\n165,outside\n155,duplicate\n',
    )
    assert wet_list["count"] == 3
    assert [item["id"] for item in mz_lists.catalog(project)][:2] == [
        "preset:mammalian_cells",
        "preset:algae",
    ]
    with pytest.raises(ValueError, match="第 2 行"):
        mz_lists.parse("m/z\tnote\nnan\tinvalid\n")
    project.manifest.update(feature_strategy="list", feature_list_id=wet_list["id"])
    store = ProjectStore(tmp_path)
    store.save(project)
    project = store.open(project.folder)
    request = preflight(project, catalog)
    assert request["effective_targets"] == 2
    sample = project.samples[0]
    params = ProcessingParameters(**request["parameters"])
    preview = RawPreviewService(catalog).open(sample["storage"], sample["path"])
    detection = preview.cell_detection(params, targets=[155.0, 157.0], targeted=True)
    assert detection.reference_mz == (150.0,)
    assert detection.cell_count == 2
    assert list(preview.last_dataset.data.columns) == [155.0]
    digest = wet_list["sha256"]
    sample["preview"] = {
        "artifact": save_preview(
            project,
            sample,
            preview,
            params,
            signature(sample["path"], params, digest),
            mz_list=digest,
        ),
    }

    request = preflight(project, catalog)
    request["created_at"] = "test"
    folder = project.folder / "processing" / "targeted"
    folder.mkdir()
    write_json(folder / "request.json", request)
    path = folder / "state.json"
    run_batch(path)
    state = read_batch(path)
    assert [row["status"] for row in state["samples"]] == ["succeeded", "succeeded"], state
    assert state["samples"][0]["reused_preview"]
    result = reviewed_dataset(path, [row["id"] for row in state["samples"]])
    assert result.var.mz.tolist() == [155.0]
    view = describe_profile(path, state, request, None)
    assert view["source"]["sha256"] == digest
    assert [item["status"] for item in view["features"]] == ["retained", "unretained", "outside"]
    assert view["features"][0]["detected_cells"] == 4
    assert view["contributors"] == ["a", "b"]
    assert view["figure"]["layout"]["meta"]["batch_spectrum"]["sha256"] == state["spectrum_sha256"]
