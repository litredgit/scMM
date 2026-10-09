import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

pytest.importorskip("plotly")

from scMM.application.workbench import AnalysisWorkspace
from scMM.ui.analysis_plots import violin_figure, volcano_figure
from scMM.ui.presentation import style_figure


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


def test_plot_display_uses_scientific_notation_only_for_intensity():
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
    assert "0.000000001" in volcano.data[0].customdata[0]
    assert "0.00000001" in volcano.data[0].customdata[0]
    assert volcano.layout.yaxis.tickformat == ".3~f"
    pd.testing.assert_frame_equal(table, original)
