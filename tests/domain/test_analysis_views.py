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
    assert figure.layout.xaxis.tickformat == figure.layout.xaxis.hoverformat == ".1e"
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
    assert template.count(".1e") == 2
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


def scatter_data():
    return AnnData(
        np.array([[0.0, 1.0], [1.0, 3.0], [2.0, 5.0], [3.0, 7.0]]),
        obs=pd.DataFrame(
            {"sample": ["a", "a", "b", "b"], "continuous": [1.0, np.nan, 3.0, 4.0]},
            index=["cell-A", "cell-B", "cell-C", "cell-D"],
        ),
        var=pd.DataFrame({"mz": [150.0, 151.0]}, index=["feature-a", "feature-b"]),
    )


def test_exact_feature_scatter_fit_zeros_and_full_export():
    from io import StringIO

    from scMM.analysis.feature_scatter import feature_scatter_figure

    data = scatter_data()
    before = data.copy()
    figure = feature_scatter_figure(
        data, feature_a="feature-a", feature_b="feature-b", color_key="sample"
    )
    fit = figure.layout.meta["regression"]
    assert (
        fit["n_cells"] == 4
        and fit["slope"] == 2
        and fit["intercept"] == 1
        and fit["r_squared"] == 1
    )
    frame = pd.read_csv(StringIO(figure.layout.meta["export_tables"]["cells.csv"]))
    assert frame.cell_id.tolist() == data.obs_names.tolist()
    assert frame.x_value.tolist() == [0, 1, 2, 3]
    assert frame.included.all()
    np.testing.assert_array_equal(data.X, before.X)
    with pytest.raises(ValueError, match="稳定特征 ID"):
        feature_scatter_figure(data, feature_a="150.001", feature_b="feature-b")
    with pytest.raises(ValueError, match="不同"):
        feature_scatter_figure(data, feature_a="feature-a", feature_b="feature-a")


@pytest.mark.parametrize("kind", ["constant-x", "constant-y", "nonfinite", "extreme"])
def test_scatter_degeneracies_are_explicit_and_preserve_source(kind):
    from io import StringIO

    from scMM.analysis.feature_scatter import feature_scatter_figure

    data = scatter_data()
    matrix = data.X.copy()
    if kind == "constant-x":
        matrix[:, 0] = 0
    elif kind == "constant-y":
        matrix[:, 1] = 5
    elif kind == "nonfinite":
        matrix[1, 0] = np.nan
    else:
        matrix[:, 0] = [-1e308, -5e307, 5e307, 1e308]
    data.layers["chosen"] = matrix
    figure = feature_scatter_figure(
        data, feature_a="feature-a", feature_b="feature-b", layer="chosen"
    )
    fit = figure.layout.meta["regression"]
    assert figure.layout.meta["notes"]
    frame = pd.read_csv(StringIO(figure.layout.meta["export_tables"]["cells.csv"]))
    assert len(frame) == 4
    assert (
        fit["status"]
        == {
            "constant-x": "insufficient_or_constant_x",
            "constant-y": "constant_y",
            "nonfinite": "fitted",
            "extreme": "numerical_failure",
        }[kind]
    )
    assert int(frame.included.sum()) == (3 if kind == "nonfinite" else 4)
    np.testing.assert_array_equal(data.layers["chosen"], matrix)


def test_missing_color_keeps_every_finite_cell_and_no_finite_pairs_fail():
    from scMM.analysis.feature_scatter import feature_scatter_figure

    data = scatter_data()
    for key in ("continuous", "sample"):
        data.obs.loc["cell-B", key] = None
        figure = feature_scatter_figure(
            data, feature_a="feature-a", feature_b="feature-b", color_key=key, regression=False
        )
        assert sum(len(trace.x) for trace in figure.data) == 4
        assert figure.layout.meta["regression"]["status"] == "disabled"
    data.layers["invalid"] = np.full((4, 2), np.nan)
    with pytest.raises(ValueError, match="共同有限值"):
        feature_scatter_figure(data, feature_a="feature-a", feature_b="feature-b", layer="invalid")
