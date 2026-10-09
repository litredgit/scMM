"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from test_project_batch import setup_project
from test_project_ui import workspace

from scMM.application import RawPreviewService, StorageCatalog, StorageRoot
from scMM.application.preferences import cpu_default, load_preferences, save_preferences
from scMM.application.preview_cache import reusable_preview, save_preview, signature
from scMM.application.processing import ProcessingParameters
from scMM.application.project_batch import preflight, read_batch, run_batch
from scMM.application.projects import write_json
from scMM.application.workbench import AnalysisWorkspace
from scMM.ui.analysis_plots import violin_figure, volcano_figure
from scMM.ui.file_browser import FileBrowser


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


def test_browser_cross_directory_selection_and_root_boundary(tmp_path):
    (tmp_path / "a.mzML").touch()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/b.raw").touch()
    browser = FileBrowser(StorageCatalog([StorageRoot("data", tmp_path)]), "data")
    browser.choose(tmp_path / "a.mzML")
    browser.open(tmp_path / "sub")
    browser.choose(tmp_path / "sub/b.raw")
    assert len(browser.value) == 2
    browser.open(tmp_path.parent)
    assert browser.directory == tmp_path / "sub"
    browser.selected.value = browser.value[:1]
    assert len(browser.value) == 1


def test_global_presets_and_cpu_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("SCMM_PREFERENCES", str(tmp_path / "preferences.json"))
    assert load_preferences()["presets"]["哺乳动物"] == 760.5851
    save_preferences({"custom": 123.4567}, "custom")
    assert load_preferences()["selected"] == "custom"
    monkeypatch.setattr("os.cpu_count", lambda: 12)
    monkeypatch.setattr("os.sched_getaffinity", lambda _: {0, 1})
    assert cpu_default() == 2


def test_imported_samples_edit_and_persist(tmp_path):
    ui = workspace(tmp_path)
    data = AnnData(
        np.ones((6, 2)),
        obs=pd.DataFrame(
            {"sample": ["a"] * 3 + ["b"] * 3, "group": ["x"] * 3 + ["y"] * 3}, index=list("abcdef")
        ),
    )
    ui.project.workspace.replace(data)
    ui._prepare_sample_mapping()
    assert len(ui.project.samples) == 2
    assert ui.project.workspace.data.obs.sample_id.nunique() == 2
    ui.project.samples[0]["group"] = "new"
    ui._sync_metadata()
    ui._save()
    reopened = ui.store.open(ui.project.folder)
    assert reopened.workspace.data.obs.group.iloc[0] == "new"
    assert reopened.workspace._original.obs.group.iloc[0] == "new"


def test_volcano_click_layout_and_input_precision(tmp_path):
    ui = workspace(tmp_path)
    data = AnnData(
        np.arange(1.0, 73.0).reshape(12, 6),
        obs=pd.DataFrame({"group": ["a"] * 6 + ["b"] * 6}, index=[f"c{i}" for i in range(12)]),
        var=pd.DataFrame(index=[str(100.123456 + i) for i in range(6)]),
    )
    ui.project.workspace.replace(data)
    ui.analysis.refresh()
    ui.analysis._differentiate()
    ui.analysis.refresh()
    feature = data.var_names[0]
    event = SimpleNamespace(new={"points": [{"customdata": [feature]}]})
    ui.analysis._volcano_click(event)
    assert ui.analysis.features.value == [feature]
    ui.analysis._volcano_click(event)
    assert ui.analysis.features.value == []
    result = ui.project.workspace.result("differential")
    figure = violin_figure(data, result, list(data.var_names), columns=3)
    assert figure.layout.height == 680
    assert "100.1235" in figure.layout.annotations[0].text
    assert data.var_names[0] == "100.123456"
    assert volcano_figure(result["table"]).layout.plot_bgcolor == "white"
    ui.go(5)
    assert ui.analysis_navigation.visible
    assert ui.purpose not in ui.analysis_page.objects


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


def test_mixed_imported_annotations_are_preserved_until_explicit_edit(tmp_path):
    ui = workspace(tmp_path)
    data = AnnData(
        np.ones((4, 2)),
        obs=pd.DataFrame(
            {"sample": ["one"] * 4, "group": ["a", "b", "a", "b"]}, index=list("abcd")
        ),
    )
    ui.project.workspace.replace(data)
    ui._prepare_sample_mapping()
    assert ui.project.workspace.data.obs.group.tolist() == ["a", "b", "a", "b"]
    ui._edit_sample(SimpleNamespace(row=0, column="group", value="new"))
    assert ui.project.workspace.data.obs.group.tolist() == ["new"] * 4


def test_explicit_config_parameters_override_global_defaults(tmp_path):
    import json

    from scMM.application.parameters import load_defaults
    from scMM.ui.app import ProjectWorkspace

    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"processing": {"ref_mz": 150.0, "mz_min": 140.0, "mz_max": 160.0}})
    )
    ui = ProjectWorkspace(
        (StorageRoot("data", tmp_path),), project_root=tmp_path, defaults=load_defaults(config)
    )
    ui.name.value = "configured project"
    ui._create()
    assert ui.project.manifest["parameters"]["ref_mz"] == 150.0
    assert not ui.project.manifest["auto_ranges"]
