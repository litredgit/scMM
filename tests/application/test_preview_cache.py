"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

from dataclasses import asdict

import numpy as np

from scMM.application import RawPreviewService
from scMM.application.preview_cache import reusable_preview, save_preview, signature
from scMM.application.processing import ProcessingParameters
from scMM.application.project_batch import preflight, read_batch, run_batch
from scMM.application.projects import write_json
from tests.support.project import setup_project


def test_preview_cache_skips_extraction_and_rejects_changed_inputs(tmp_path, monkeypatch):
    project, catalog = setup_project(tmp_path)
    project.manifest["feature_strategy"] = "independent"
    sample = project.samples[0]
    params = ProcessingParameters(**project.manifest["parameters"])
    preview = RawPreviewService(catalog).open(sample["storage"], sample["path"])
    before = signature(sample["path"], params)
    preview.cell_detection(params)
    artifact = save_preview(project, sample, preview, params, before)
    sample["preview"] = {"parameters": asdict(params), "artifact": artifact, "confirmed": True}
    request = preflight(project, catalog)
    resolved = request["samples"][0]
    assert reusable_preview(project.folder, resolved) is not None
    assert reusable_preview(project.folder, resolved, np.array([999.0])) is None
    resolved["group"] = "changed"
    assert reusable_preview(project.folder, resolved) is not None
    from scMM.file.data import CyESIData

    original = CyESIData.load_from_file

    def guarded(path, *args, **kwargs):
        assert str(path) != sample["path"], "cached sample must not be extracted again"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(CyESIData, "load_from_file", guarded)
    folder = project.folder / "processing" / "batch-test"
    folder.mkdir()
    request["created_at"] = "test"
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    result = read_batch(folder / "state.json")
    assert result["status"] == "completed"
    assert result["samples"][0]["reused_preview"]
    assert all(row["status"] == "succeeded" for row in result["samples"])
    changed = {**resolved, "parameters": {**resolved["parameters"], "cell_snr": 7.0}}
    assert reusable_preview(project.folder, changed) is None
    from pathlib import Path

    Path(sample["path"]).touch()
    assert reusable_preview(project.folder, resolved) is None


def test_shared_preview_reuses_exact_batch_features(tmp_path, monkeypatch):
    from scMM.application.preview_cache import prepare_shared_targets
    from scMM.application.projects import ProjectStore
    from scMM.file.data import CyESIData

    project, catalog = setup_project(tmp_path)
    request = preflight(project, catalog)
    targets = prepare_shared_targets(project, request)
    sample = project.samples[0]
    params = ProcessingParameters(**request["samples"][0]["parameters"])
    preview = RawPreviewService(catalog).open(sample["storage"], sample["path"])
    before = signature(sample["path"], params)
    preview.cell_detection(params, targets=targets)
    expected = preview.last_dataset.data.copy()
    sample["preview"] = {
        "artifact": save_preview(project, sample, preview, params, before),
        "parameters": asdict(params),
    }
    store = ProjectStore(tmp_path)
    store.save(project)
    project = store.open(project.folder)
    original = __import__(
        "scMM.application.project_batch", fromlist=["load_single_file"]
    ).load_single_file

    def guard(path):
        assert str(path) != sample["path"], "shared spectrum and cells should both be reused"
        return original(path)

    monkeypatch.setattr("scMM.application.project_batch.load_single_file", guard)
    request = preflight(project, catalog)
    request["created_at"] = "test"
    folder = project.folder / "processing" / "shared-batch"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    rows = read_batch(folder / "state.json")["samples"]
    assert all(row["status"] == "succeeded" for row in rows), rows
    assert rows[0]["reused_preview"]
    actual = CyESIData.read_h5ad(folder / rows[0]["output"])
    np.testing.assert_array_equal(actual.data.to_numpy(), expected.to_numpy())
    np.testing.assert_array_equal(actual.data.columns, expected.columns)
