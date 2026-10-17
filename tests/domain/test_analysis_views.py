"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.workbench import AnalysisWorkspace
from scMM.plot.presentation import qc_file_table

pytest.importorskip("plotly")

from scMM.plot.presentation import style_figure
from scMM.plot.workbench import violin_figure, volcano_figure


def test_feature_selection_and_hiding_zero_never_recompute_fdr(monkeypatch):
    data = AnnData(
        np.array([[0, 1], [2, 1], [4, 1], [1, 2], [3, 2], [5, 2.0]]),
        obs=pd.DataFrame({"group": ["a"] * 3 + ["b"] * 3}, index=list("abcdef")),
    )
    state = AnalysisWorkspace()
    state.replace(data)
    result = state.differential("group", "a", "b")
    expected = result["table"].copy()

    def no_retest(*args, **kwargs):
        raise AssertionError("plots must use the already corrected full feature table")

    monkeypatch.setattr("scMM.analysis.statistics.differential_features", no_retest)
    volcano = volcano_figure(expected)
    violin = violin_figure(state.data, result, ["0"], hide_zero=True)
    assert len(volcano.data[0].x) == 2
    assert len(violin.data[0].y) == 2
    assert "全局 FDR" in violin.layout.annotations[0].text
    pd.testing.assert_frame_equal(expected, result["table"])


def test_plot_display_formats_intensity_and_probabilities_without_rounding_data():
    import plotly.graph_objects as go

    figure = style_figure(
        go.Figure().update_layout(xaxis_title="total_intensity", yaxis_title="detected_features")
    )
    assert figure.layout.xaxis.tickformat == figure.layout.xaxis.hoverformat == ".3e"
    assert figure.layout.yaxis.tickformat == figure.layout.yaxis.hoverformat == "d"
    table = pd.DataFrame(
        {
            "feature_id": ["100.123456"],
            "fdr": [1e-8],
            "p_value": [1e-9],
            "log2_fold_change": [2.0],
            "mean_a": [1e6],
            "mean_b": [2e6],
        }
    )
    original = table.copy()
    volcano = volcano_figure(table)
    template = volcano.data[0].hovertemplate
    assert template.count(".3e") == 2
    assert "1.00e-09" in volcano.data[0].customdata[0]
    assert "1.00e-08" in volcano.data[0].customdata[0]
    assert volcano.layout.yaxis.tickformat == ".3~f"
    pd.testing.assert_frame_equal(table, original)


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
