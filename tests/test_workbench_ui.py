import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

pytest.importorskip("panel")
pytest.importorskip("plotly")

from scMM.application import OutputRoot, StorageRoot
from scMM.application.parameters import load_defaults
from scMM.ui.app import PreviewWorkspace


def _workspace(tmp_path, defaults=None):
    output = tmp_path / "results"
    output.mkdir(exist_ok=True)
    return PreviewWorkspace(
        (StorageRoot("云盘", tmp_path),), (OutputRoot("Results", output),), defaults=defaults
    )


def _dataset(path):
    data = AnnData(
        np.random.default_rng(42).uniform(1, 5, (80, 5)),
        obs=pd.DataFrame(
            {"group": ["a", "b"] * 40, "sample": np.repeat(np.arange(20).astype(str), 4)},
            index=[f"c{i}" for i in range(80)],
        ),
    )
    data.write_h5ad(path)
    return data


def _load(ui, path):
    ui.path.value = str(path)
    ui.run(ui._load)
    assert ui.state.data is not None, ui.status.object


def test_reusable_views_h5ad_differential_and_lifecycle(tmp_path):
    path = tmp_path / "数据.h5ad"
    _dataset(path)
    workspace = _workspace(tmp_path)
    assert len(workspace.tabs) == 2
    ui = workspace.analysis
    _load(ui, path)
    assert ui.group_a.value == "a"
    assert ui.group_b.value == "b"
    ui.run(ui._differentiate)
    assert not ui.diff_download.disabled, ui.status.object
    ui.diff_download._transfer()
    assert ui.diff_download.data
    before = ui.diff_table.object.copy()
    ui.hide_zero.value = True
    ui.features.value = ["0", "1"]
    pd.testing.assert_frame_equal(ui.diff_table.object, before)
    ui.run(lambda: ui.state.normalize("total"))
    assert ui.diff_download.disabled
    assert ui.diff_download.data is None
    assert ui.diff_table.object.empty
    assert len(ui.state.data.layers) == 2
    ui.run(ui._differentiate)
    assert not ui.diff_download.disabled
    _load(ui, path)
    assert ui.diff_download.disabled
    assert ui.model_report.object == {}
    assert workspace.preview is None


def test_model_parameters_invalidate_outputs_and_lsqr_disables_latent(tmp_path):
    path = tmp_path / "data.h5ad"
    _dataset(path)
    ui = _workspace(tmp_path).analysis
    _load(ui, path)
    ui.sample_group.value = "sample"
    ui.cv.value = 3
    ui.model.value = "lda"
    ui.lda_solver.value = "lsqr"
    ui.run(ui._train)
    assert not ui.model_download.disabled, ui.status.object
    assert ui.latent_button.disabled
    assert ui.pr.object.data
    ui.test_size.value = 0.3
    assert ui.model_download.disabled
    assert not ui.pr.object.data
    ui.lda_solver.value = "svd"
    ui.run(ui._train)
    assert not ui.latent_button.disabled
    ui.run(lambda: ui.state.save_latent("X_latent"))
    assert "X_latent" in ui.state.data.obsm
    ui.run(lambda: ui.state.normalize("total"))
    assert ui.model_download.disabled
    assert not ui.state.data.obsm


def test_save_requires_current_confirmation_and_preserves_history(tmp_path):
    path = tmp_path / "data.h5ad"
    _dataset(path)
    ui = _workspace(tmp_path).analysis
    _load(ui, path)
    ui.run(ui._save)
    assert "确认" in ui.status.object
    ui.confirm_save.value = True
    ui.run(lambda: ui.state.normalize("total"))
    assert not ui.confirm_save.value
    ui.export_name.value = "saved.h5ad"
    ui.confirm_save.value = True
    ui.run(ui._save)
    assert (tmp_path / "saved.h5ad").is_file(), ui.status.object
    stored = read_h5ad(tmp_path / "saved.h5ad")
    assert len(stored.layers) == 2
    ui.confirm_save.value = True
    ui.export_name.value = "changed.h5ad"
    assert not ui.confirm_save.value


def test_json_defaults_reach_processing_and_analysis_widgets(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "processing": {
                    "ref_mz": 150.0,
                    "mz_min": 140.0,
                    "mz_max": 160.0,
                    "feature_block_size": 32,
                },
                "analysis": {
                    "cv": 3,
                    "reduction": "isomap",
                    "network_top_features": 12,
                    "shap_samples": 4,
                },
            }
        )
    )
    workspace = _workspace(tmp_path, load_defaults(path))
    parameters = workspace.processing._parameters()
    assert parameters.ref_mz == 150
    assert parameters.mz_min == 140
    assert parameters.feature_block_size == 32
    assert workspace.analysis.cv.value == 3
    assert workspace.analysis.reduction.value == "isomap"
    assert workspace.analysis.network_top_features.value == 12
    assert workspace.analysis.shap_samples.value == 4
    assert "feature_snr_threshold" in workspace.processing.parameter_help[0].object


def test_raw_preview_integration_and_parameter_invalidation(tmp_path):
    import pyopenms as oms

    from scMM.file.io import save_spectra

    spectra = []
    for i in range(31):
        spectrum = oms.MSSpectrum()
        spectrum.setMSLevel(1)
        spectrum.setRT(float(i))
        spectrum.set_peaks(
            (np.array([149.9, 150.0, 150.1]), np.array([0.0, 20.0 if i == 8 else 1.0, 0.0]))
        )
        spectra.append(spectrum)
    path = save_spectra(spectra, tmp_path / "raw.mzML")
    workspace = _workspace(tmp_path)
    workspace._selector.value = [str(path)]
    workspace._load_selected(None)
    workspace.more_references.value = "150,151"
    workspace._refresh_all(None)
    assert set(workspace.eic.reference_mz) >= {150.0, 151.0}
    workspace.scan_index.value = 8
    workspace._show_scan()
    assert "Scan 8" in workspace.scan_pane.object.layout.title.text
    processing = workspace.processing
    processing.ref_mz.value = 150
    processing.resolution.value = 5000
    processing.points_per_fwhm.value = 2
    processing.ppm_tol.value = 500
    processing.baseline_size.value = 5
    workspace._preview_cells()
    assert not workspace.cell_download.disabled, workspace.cell_status.object
    processing.cell_snr.value = 6
    assert workspace.cell_download.disabled
    assert workspace.cell_frame.empty


def test_native_windows_path_parsing_and_cli_config():
    from scMM.ui.cli import build_parser, parse_storage_root

    label, path = parse_storage_root(r"云盘=D:\实验 数据")
    assert label == "云盘"
    assert path == Path(r"D:\实验 数据")
    assert build_parser().parse_args(["--config", "params.json"]).config == Path("params.json")


def test_windows_minimal_mode_disables_only_background_tasks(tmp_path, monkeypatch):
    from scMM.application import tasks

    monkeypatch.setattr(tasks, "fcntl", None)
    path = tmp_path / "data.h5ad"
    _dataset(path)
    workspace = _workspace(tmp_path)
    assert workspace.processing.preflight_button.disabled
    assert workspace.processing.submit_button.disabled
    assert workspace.processing.tasks.list() == ()
    with pytest.raises(RuntimeError, match="only on Linux"):
        workspace.processing.tasks.submit(None)
    _load(workspace.analysis, path)
    workspace.analysis.run(workspace.analysis._differentiate)
    assert not workspace.analysis.diff_download.disabled


def test_all_pages_build_and_serialize_bokeh_documents(tmp_path):
    from bokeh.document import Document

    path = tmp_path / "data.h5ad"
    _dataset(path)
    workspace = _workspace(tmp_path)
    _load(workspace.analysis, path)
    workspace.analysis.run(workspace.analysis._differentiate)
    document = Document()
    root = workspace.tabs.get_root(document)
    document.add_root(root)
    for index in range(len(workspace.tabs)):
        workspace.tabs.active = index
        document.validate()
        serialized = document.to_json()
        assert (serialized.content if hasattr(serialized, "content") else serialized)["roots"]
    workspace.tabs._cleanup(root)


@pytest.mark.filterwarnings(
    "ignore:The set_(bad|under|over) function will be deprecated:PendingDeprecationWarning:shap.plots.colors._colors"
)
def test_marker_network_shap_exports_and_invalidation(tmp_path):
    pytest.importorskip("shap")
    path = tmp_path / "data.h5ad"
    data = _dataset(path)
    ui = _workspace(tmp_path).analysis
    _load(ui, path)
    ui.run(lambda: ui.state.markers("group"))
    assert len(ui.marker_table.object) == 2 * data.n_vars, ui.status.object
    ui.network_threshold.value = 0
    ui.run(ui._network)
    assert len(ui.network_table.object) == 10, ui.status.object
    assert ui.network_plot.object.data
    ui.cv.value = 3
    ui.run(ui._train)
    ui.shap_background.value = 8
    ui.shap_samples.value = 4
    ui.run(lambda: ui.state.explain_shap(max_background=8, max_samples=4, seed=42))
    assert len(ui.shap_table.object) == data.n_vars, ui.status.object
    expected = np.abs(ui.state.result("supervised").shap_explanation_.values).mean(axis=0)
    actual = ui.shap_table.object.set_index("feature_id").loc[data.var_names, "mean_abs_shap"]
    np.testing.assert_allclose(actual, expected)
    assert ui.shap_plot.object.data
    for download in ui.extra_downloads.values():
        assert not download.disabled
        download._transfer()
        assert download.data
    ui.export_name.value = "reports.h5ad"
    ui.confirm_save.value = True
    ui.run(ui._save)
    reports = json.loads(read_h5ad(tmp_path / "reports.h5ad").uns["scmm_workbench"]["reports_json"])
    assert {"markers", "network", "supervised", "shap"} <= reports.keys()
    assert len(reports["network"]["nodes"]) == 5
    assert len(reports["shap"]["obs_names"]) == 4
    ui.shap_samples.value = 5
    assert ui.shap_table.object.empty
    assert not ui.model_download.disabled
    ui.run(lambda: ui.state.explain_shap(max_background=8, max_samples=4, seed=42))
    ui.model.value = "lda"
    assert ui.shap_table.object.empty
    assert ui.shap_button.disabled
    ui.network_threshold.value = 0.9
    assert ui.network_table.object.empty
    ui.diff_method.value = "welch"
    assert ui.marker_table.object.empty
    for download in ui.extra_downloads.values():
        assert download.disabled
        assert download.data is None


def test_network_keeps_isolated_nodes_and_selected_layer(tmp_path):
    from scMM.ui.analysis_plots import network_figure

    data = _dataset(tmp_path / "data.h5ad")
    ui = _workspace(tmp_path).analysis
    ui.state.replace(data)
    ui.state.data.layers["constant"] = np.ones(data.shape)
    result = ui.state.network(layer="constant", top_features=3)
    assert len(result["graph"]) == 3
    assert result["table"].empty
    assert len(network_figure(result["graph"]).data[-1].x) == 3
    ui.state.normalize("total")
    assert not ui.state.results
