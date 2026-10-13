"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from test_project_batch import setup_project

from scMM.application import RawPreviewService
from scMM.application.preferences import cpu_default, load_preferences, save_preferences
from scMM.application.preview_cache import reusable_preview, save_preview, signature
from scMM.application.processing import ProcessingParameters
from scMM.application.project_batch import preflight, read_batch, run_batch
from scMM.application.projects import write_json
from scMM.application.workbench import AnalysisWorkspace
from scMM.plot.presentation import qc_file_table


def test_metadata_preserves_matrix_layers_embedding_and_unrelated_results():
    state = AnalysisWorkspace()
    data = AnnData(
        np.arange(1.0, 25.0).reshape(6, 4),
        obs=pd.DataFrame(
            {
                "sample_id": ["a"] * 3 + ["b"] * 3,
                "sample": ["one"] * 3 + ["two"] * 3,
                "group": ["old"] * 3 + ["control"] * 3,
            },
            index=list("abcdef"),
        ),
    )
    data.obsm["X_pca"] = np.ones((6, 2))
    state.replace(data)
    state.differential("group", "old", "control")
    state.put_result("network", {"table": pd.DataFrame()}, state.token)
    samples = [
        {"id": "a", "name": "renamed", "group": "new", "subject": "s1", "batch": "b1"},
        {"id": "b", "name": "two", "group": "control", "subject": "s2", "batch": "b2"},
    ]
    changed = state.sync_sample_metadata(samples)
    assert "group" in changed
    assert "differential" not in state.results and "network" in state.results
    np.testing.assert_array_equal(state.data.X, data.X)
    np.testing.assert_array_equal(state.data.obsm["X_pca"], data.obsm["X_pca"])
    assert state.data.layers
    state.reset()
    assert state.data.obs.group.iloc[0] == "new"
    assert state.data.obs["sample"].iloc[0] == "renamed"


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


def test_global_presets_and_cpu_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("SCMM_PREFERENCES", str(tmp_path / "preferences.json"))
    assert load_preferences()["presets"]["哺乳动物"] == 760.5851
    save_preferences({"custom": 123.4567}, "custom")
    assert load_preferences()["selected"] == "custom"
    monkeypatch.setattr("os.cpu_count", lambda: 12)
    monkeypatch.setattr("os.sched_getaffinity", lambda _: {0, 1})
    assert cpu_default() == 2


def test_qc_reference_rows_preserve_nearby_ions_and_omit_empty_sample_records():
    from scMM.analysis.quality import quality_metrics

    data = AnnData(
        np.ones((4, 2)),
        obs=pd.DataFrame(
            {
                "source_file": ["a", "a", "b", "b"],
                "reference_intensity_760.58331": [1.23456789, 2, np.nan, np.nan],
                "reference_intensity_760.58332": [np.nan, np.nan, 3, 4],
            },
            index=list("abcd"),
        ),
    )
    original = quality_metrics(data)["file"]
    displayed = qc_file_table(original)
    refs = displayed[displayed.metric.str.startswith("参考强度")]
    assert len(refs) == 2
    assert refs.source_file.tolist() == ["a", "b"]
    assert refs.reference_mz.tolist() == ["760.5833", "760.5833"]
    assert original.columns.get_level_values(0).nunique() == 4
    assert refs["cell_count"].tolist() == [2, 2]
    assert refs.iloc[0]["mean"] == original.loc["a", ("reference_intensity_760.58331", "mean")]
    assert not isinstance(displayed.columns, pd.MultiIndex)


def test_display_precision_preserves_tiny_values():
    from scMM.plot.presentation import count_number, ordinary_number, probability_number

    assert count_number(123.33333333333333) == "123.3"
    assert count_number(123.0) == "123"
    assert ordinary_number(-1.23456789) == "-1.235"
    assert ordinary_number(0.0000123456789) == "0.0000123"
    assert probability_number(0.123456789) == "1.23e-01"
    assert probability_number(1.23456789e-12) == "1.23e-12"
    assert probability_number(0) == "0"


def test_pca_input_dimension_validation_and_provenance():
    from scMM.analysis.embedding import reduce_dimension

    data = AnnData(np.random.default_rng(42).normal(size=(30, 25)))
    reduce_dimension(data, "pca", pca_components=20, n_components=2, whiten=True)
    assert data.uns["X_pca_params"]["pca_components"] == 20
    with pytest.raises(ValueError, match="PCA input dimensions"):
        reduce_dimension(data, "umap", pca_components=40)


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


def test_automatic_ranges_do_not_freeze_project_defaults(tmp_path):
    from scMM.application.projects import sample_parameters

    project, _ = setup_project(tmp_path)
    project.manifest["auto_ranges"] = True
    project.samples[0]["auto_mz_range"] = [140.0, 160.0]
    project.samples[1]["auto_mz_range"] = [130.0, 170.0]
    assert sample_parameters(project, project.samples[0])["mz_min"] == 130.0
    project.manifest["parameters"]["cell_snr"] = 8.0
    assert sample_parameters(project, project.samples[0])["cell_snr"] == 8.0
    project.manifest["feature_strategy"] = "independent"
    assert sample_parameters(project, project.samples[0])["mz_min"] == 140.0
    project.manifest["manual_parameters"] = True
    project.manifest["parameters"]["mz_min"] = 120.0
    assert sample_parameters(project, project.samples[0])["mz_min"] == 120.0
