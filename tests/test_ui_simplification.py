from html import unescape

import numpy as np
import pandas as pd
import panel as pn
import plotly.express as px
import pytest
from anndata import AnnData
from bokeh.document import Document

from scMM.analysis.quality import quality_metrics
from scMM.application import StorageRoot
from scMM.application.parameters import PROCESSING_HELP
from scMM.ui.app import ProjectWorkspace
from scMM.ui.preflight import ParameterTable, parameter_table
from scMM.ui.presentation import QCDataFrame, apply_presentation, qc_file_table


def workspace(tmp_path):
    ui = ProjectWorkspace((StorageRoot("data", tmp_path),), project_root=tmp_path)
    ui.saved_items.manager.trash_root = tmp_path / "recycle"
    ui.name.value = "显示检查"
    ui._create()
    return ui


def test_qc_merges_centered_cells_without_merging_same_basename_or_mutating_data():
    data = AnnData(
        np.ones((5, 2)),
        obs=pd.DataFrame(
            {
                "source_file": ["/one/<sample>.raw"] * 3 + ["/two/<sample>.raw"] * 2,
                "reference_intensity_100.12345": [1, np.nan, 3, np.nan, np.nan],
                "reference_intensity_200.12345": [np.nan] * 3 + [4, 5],
            },
            index=list("abcde"),
        ),
    )
    metrics = quality_metrics(data)["file"]
    original = metrics.copy(deep=True)
    frame = qc_file_table(metrics)
    assert frame.cell_count.tolist() == [3] * 3 + [2] * 3
    assert frame.source_file.tolist() == ["<sample>.raw"] * 6
    pane = QCDataFrame(frame, index=False)
    apply_presentation(pn.Column(pane))
    model = pane.get_root(Document())
    html = unescape(model.text)
    assert html.count('rowspan="3"') == 6
    assert html.count("&lt;sample&gt;.raw</td>") == 2
    assert "<sample>" not in html
    assert 'title="/one/&lt;sample&gt;.raw"' in html
    assert "vertical-align: middle" in pane.stylesheets[-1]
    assert "text-align: center" in pane.stylesheets[-1]
    pd.testing.assert_frame_equal(metrics, original)
    pane._cleanup(model)


def test_parameter_hover_help_has_no_explanation_column(tmp_path):
    from dataclasses import asdict

    ui = workspace(tmp_path)
    for key, widget in ui.components.processing.parameter_widgets.items():
        assert widget.description == PROCESSING_HELP[key]
    for name in (
        "min_total",
        "normalization",
        "embedding_key",
        "pca_input",
        "max_iter",
        "cluster_key",
    ):
        assert getattr(ui.analysis, name).description
    frame = parameter_table(asdict(ui.defaults.processing))
    assert "Explanation" not in frame and "解释" not in frame
    pane = ParameterTable(frame, index=False)
    model = pane.get_root(Document())
    assert PROCESSING_HELP["ref_mz"] in unescape(model.text)
    assert "<span title=" in unescape(model.text)
    pane._cleanup(model)
    checkbox = ui.analysis.pca_input
    model = checkbox.get_root(Document())
    assert model.html_attributes["title"] == checkbox.description
    checkbox._cleanup(model)


def test_direct_apply_failure_preserves_data_and_old_results(tmp_path):
    ui = workspace(tmp_path)
    ui.project.workspace.replace(AnnData(np.arange(1.0, 13.0).reshape(4, 3)))
    before = ui.project.workspace.data.copy()
    ui.analysis.min_total.value = 1e30
    with pytest.raises(ValueError):
        ui._apply_operation()
    np.testing.assert_array_equal(ui.project.workspace.data.X, before.X)
    ui.analysis.min_total.value = 10
    ui._apply_operation()
    assert ui.project.workspace.data.n_obs < 4
    ui._reset()
    np.testing.assert_array_equal(ui.project.workspace.data.X, before.X)
    assert ui.analysis.root.value == "项目任务"
    assert not ui.panel.select(pn.widgets.Checkbox)


def test_legend_position_survives_recalculation_save_reopen_and_export(tmp_path):
    ui = workspace(tmp_path)
    ui.project.workspace.replace(AnnData(np.ones((4, 2))))
    ui.analysis.refresh()
    ui.go(4)
    ui.legend_chart.value = "analysis.qc_plot"
    ui.legend_position.value = "bottom_left"
    assert ui.analysis.qc_plot.object.layout.legend.x == 0.01
    ui.analysis.refresh()
    assert ui.analysis.qc_plot.object.layout.legend.y == 0.01
    ui.legend_position.value = "hidden"
    assert ui.analysis.qc_plot.object.layout.showlegend is False
    ui.legend_position.value = "top_right"
    assert ui.analysis.qc_plot.object.layout.showlegend is not False
    assert '"x":0.99' in ui.analysis.qc_plot.object.to_json()
    ui._save()
    ui.activate(ui.store.open(ui.project.folder))
    ui.go(4)
    assert ui.project.views["legend_positions"]["analysis.qc_plot"] == "top_right"
    assert ui.analysis.qc_plot.object.layout.legend.x == 0.99
    ui.analysis.embedding_plot.object = px.scatter(x=[1, 2], y=[2, 3], color=[5.0, 6.0])
    ui._apply_legend(ui.analysis.embedding_plot, "analysis.embedding_plot")
    ui.project.views["legend_positions"]["analysis.embedding_plot"] = "bottom_left"
    ui._apply_legend(ui.analysis.embedding_plot, "analysis.embedding_plot")
    colorbar = ui.analysis.embedding_plot.object.layout.coloraxis.colorbar
    assert colorbar.x == 0.01 and colorbar.y == 0.01 and colorbar.len == 0.35


def test_task_stage_translation_preserves_sample_name_and_diagnostic_errors():
    from scMM.ui.help import task_message

    assert task_message("Extracting A.raw") == "正在提取 A.raw"
    assert task_message("A.raw: 25% Extracting SNR cell features") == "A.raw: 25% 提取 SNR 细胞特征"
    assert task_message("Reader error code 17") == "Reader error code 17"


def test_repeated_legend_updates_reach_attached_model_without_changing_arrays(tmp_path):
    ui = workspace(tmp_path)
    data = np.array([1.234567891234e-12, 2.345678912345, 3.456789123456])
    ui.analysis.qc_plot.object = px.scatter(x=data, y=data, color=["a", "b", "a"])
    ui.legend_chart.options = {"QC": "analysis.qc_plot"}
    ui.legend_chart.value = "analysis.qc_plot"
    pane = ui.analysis.qc_plot
    model = pane.get_root(Document())
    old_layout = model.layout
    for _ in range(2):
        for position, x, y in (
            ("bottom_left", 0.01, 0.01),
            ("top_right", 0.99, 0.99),
            ("hidden", 1.02, 1),
            ("top_left", 0.01, 0.99),
            ("bottom_right", 0.99, 0.01),
            ("right", 1.02, 1),
        ):
            ui.legend_position.value = position
            assert model.layout["legend"]["x"] == x
            assert model.layout["legend"]["y"] == y
            assert (model.layout.get("showlegend") is not False) == (position != "hidden")
            assert old_layout["legend"]["x"] == 1.02
            np.testing.assert_array_equal(pane.object.data[0].x, data[[0, 2]])
            np.testing.assert_array_equal(pane.object.data[1].x, data[[1]])
    pane._cleanup(model)


def test_help_uses_bounded_overlay_and_reserves_space_for_long_labels(tmp_path):
    from bokeh.models import Tooltip

    from scMM.ui.help import TOOLTIP_STYLE
    from scMM.ui.layout import FIELD_STYLE

    ui = workspace(tmp_path)
    ui.project.manifest["samples"].append({"id": "synthetic", "name": "synthetic"})
    ui.go(2)
    model = ui.panel.get_root(Document())
    tooltips = list(model.select({"type": Tooltip}))
    assert tooltips
    assert all(tip.position == "top_center" and tip.attachment == "vertical" for tip in tooltips)
    assert all(tip.stylesheets == [TOOLTIP_STYLE] for tip in tooltips)
    field = ui.components.processing.parameter_widgets["ms_peak_snr_threshold"]
    assert FIELD_STYLE in field.stylesheets
    assert field.width is None
    assert "minmax(0, 1fr) 28px" in FIELD_STYLE
    assert any(m.js_event_callbacks.get("document_ready") for m in model.references())
    tabs = ui.raw_page.select(pn.Tabs)[0]
    assert "scmm-refresh" in tabs.tags and tabs.dynamic
    callback = model.js_event_callbacks["document_ready"][0]
    old_fields = set(callback.args["widgets"])
    ui.project.workspace.replace(AnnData(np.ones((2, 2))))
    ui.analysis.refresh()
    ui.go(4)
    # Switching pages must release the old help models rather than retaining
    # them through CustomJS arguments and growing every subsequent traversal.
    assert set(callback.args["widgets"]) < old_fields | set(callback.args["widgets"])
    assert field._models.get(model.id) is None
    ui.panel._cleanup(model)


def test_violin_and_table_use_scientific_probabilities_without_rounding_source():
    from scMM.ui.analysis_plots import violin_figure
    from scMM.ui.presentation import probability_number

    assert probability_number(np.nan) == "—"
    assert probability_number(1.23456789e-20) == "1.23e-20"
    frame = pd.DataFrame({"p_value": [1.23456789e-20, np.nan], "fdr": [2.34567891e-19, 0.0]})
    table = pn.pane.DataFrame(frame, index=False)
    apply_presentation(pn.Column(table))
    model = table.get_root(Document())
    assert "1.23e-20" in unescape(model.text) and "2.35e-19" in unescape(model.text)
    assert "<td>—</td>" in unescape(model.text) and "<td>0</td>" in unescape(model.text)
    pd.testing.assert_frame_equal(table.object, frame)
    table._cleanup(model)
    data = AnnData(
        np.array([[1.0], [2.0], [3.0], [4.0]]),
        obs=pd.DataFrame({"group": ["a", "a", "b", "b"]}, index=list("abcd")),
        var=pd.DataFrame(index=["100.12345"]),
    )
    result = {
        "table": pd.DataFrame({"feature_id": ["100.12345"], "fdr": [2.34567891e-19]}),
        "group_key": "group",
        "group_a": "a",
        "group_b": "b",
        "layer": None,
    }
    figure = violin_figure(data, result, ["100.12345"])
    assert "全局 FDR=2.35e-19" in figure.layout.annotations[0].text
