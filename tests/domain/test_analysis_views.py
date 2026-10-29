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
    assert "Global FDR" in violin.layout.annotations[0].text
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


def test_feature_distances_preserve_existing_absolute_correlation_definition():
    from scMM.analysis.feature_embedding import feature_distance_matrix

    x = np.array([1.0, 2.0, 3.0, 4.0])
    values = np.column_stack([x, -x, [1.0, 3.0, 2.0, 4.0]])
    distance = feature_distance_matrix(values, "pearson")
    np.testing.assert_allclose(distance[0, 1], 0, atol=1e-7)
    np.testing.assert_allclose(distance[0, 2], np.sqrt(2 * (1 - 0.8)))
    np.testing.assert_array_equal(np.diag(distance), 0)
    np.testing.assert_allclose(
        feature_distance_matrix(values, "euclidean")[0, 1], np.linalg.norm(2 * x)
    )
    with pytest.raises(ValueError, match="constant"):
        feature_distance_matrix(np.ones((4, 3)), "pearson")
    with pytest.raises(ValueError, match="finite"):
        feature_distance_matrix([[1, 2], [np.nan, 4]], "euclidean")


def test_feature_embedding_seed_missing_names_and_complete_distances():
    from io import StringIO

    from scMM.analysis.feature_embedding import feature_embedding_figure

    data = AnnData(
        np.random.default_rng(18).uniform(1, 4, (20, 4)),
        var=pd.DataFrame(
            {"name": ["same", "same", None, " "], "class": ["a", None, "b", "b"]},
            index=["f0", "f1", "f2", "f3"],
        ),
    )
    first = feature_embedding_figure(data, name_key="name", class_key="class")
    second = feature_embedding_figure(data, name_key="name", class_key="class")
    assert first.layout.meta["export_tables"] == second.layout.meta["export_tables"]
    frame = pd.read_csv(StringIO(first.layout.meta["export_tables"]["features.csv"]))
    assert frame.feature_id.tolist() == ["f0", "f1", "f2", "f3"]
    assert frame.name.tolist() == ["same", "same", "f2", "f3"]
    distance = pd.read_csv(
        StringIO(first.layout.meta["export_tables"]["distances.csv"]), index_col=0
    )
    assert distance.shape == (4, 4)
    assert not data.obsm and not data.uns
    assert first.layout.meta["effective_parameters"]["n_neighbors"] == 3
    three = feature_embedding_figure(data, features=["f0", "f1", "f2"], metric="euclidean")
    assert three.layout.meta["effective_parameters"]["n_features"] == 3


@pytest.mark.parametrize(
    "options",
    [
        {"features": ["f0", "missing", "f1"]},
        {"features": ["f0", "f0", "f1"]},
        {"features": ["f0", "f1"]},
        {"name_key": "missing"},
        {"n_neighbors": 4},
        {"random_state": True},
        {"min_dist": float("nan")},
        {"layer": "missing"},
    ],
)
def test_feature_embedding_invalid_controls_do_not_mutate(options):
    from scMM.analysis.feature_embedding import feature_embedding_figure

    data = AnnData(
        np.random.default_rng(18).uniform(1, 4, (5, 4)),
        var=pd.DataFrame(index=["f0", "f1", "f2", "f3"]),
    )
    before = data.X.copy()
    with pytest.raises(ValueError):
        feature_embedding_figure(data, **options)
    np.testing.assert_array_equal(data.X, before)
    assert not data.uns and not data.obsm


def test_feature_embedding_rejects_all_zero_distances_and_allocation_before_fit():
    from scMM.analysis.feature_embedding import feature_embedding_figure

    for data, match in (
        (AnnData(np.ones((4, 3))), "zero distance"),
        (AnnData(np.ones((4, 501))), "500"),
        (AnnData(np.ones((10001, 200))), "2000000"),
    ):
        with pytest.raises(ValueError, match=match):
            feature_embedding_figure(data, metric="euclidean")


def test_stability_qc_keeps_source_order_empty_windows_and_exact_full_values():
    from io import StringIO

    from scMM.analysis.stability import stability_figure, stability_tables

    data = AnnData(
        np.array(
            [
                [0.0, 2.0, 4.0],
                [2.0, 4.0, 6.0],
                [4.0, 6.0, 8.0],
                [6.0, 8.0, 10.0],
                [100.0, 100.0, 100.0],
            ]
        ),
        obs=pd.DataFrame(
            {"source": ["a", "a", "b", "b", "c"], "rt": [0.0, 1.0, 5.0, 6.0, np.nan]},
            index=["c0", "c1", "c2", "c3", "c4"],
        ),
        var=pd.DataFrame(index=["f0", "f1", "f2"]),
    )
    options = dict(
        source_key="source", feature="f0", time_key="rt", time_kind="acquisition_seconds", bins=4
    )
    result = stability_tables(data, **options)
    assert result["cells"].cell_id.tolist() == data.obs_names.tolist()
    assert result["cells"].included.tolist() == [True, True, True, True, False]
    assert result["cells"].time_bin.tolist() == [1, 1, 4, 4, 0]
    assert result["windows"].cell_count.tolist() == [2, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0]
    assert result["windows"].median_reference.iloc[0] == 1.0
    assert np.isnan(result["windows"].median_reference.iloc[1])
    np.testing.assert_array_equal(result["profiles"].loc["a"], [1, 3, 5])
    assert result["correlation"].loc["a", "b"] == 1.0
    assert result["correlation"].loc["c"].isna().all()
    assert result["dependencies"] == ["source", "rt"]
    figure = stability_figure(data, **options)
    exported = pd.read_csv(StringIO(figure.layout.meta["export_tables"]["cells.csv"]))
    np.testing.assert_array_equal(exported.reference_intensity, [0, 2, 4, 6, 100])
    assert len(exported) == 5 and len(result["windows"]) == 12
    data.layers["alternate"] = data.X * 2
    doubled = stability_tables(data, **{**options, "layer": "alternate"})
    assert doubled["windows"].median_reference.iloc[0] == 2
    assert not data.uns and not data.obsm


def test_stability_stored_order_missing_labels_and_nonfinite_intensity():
    from scMM.analysis.stability import stability_tables

    data = AnnData(
        np.array([[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]]),
        obs=pd.DataFrame({"sample": [None, "（缺失来源）", " "]}, index=["a", "b", "c"]),  # noqa: RUF001
        var=pd.DataFrame(index=["f0", "f1"]),
    )
    data.layers["bad"] = np.array([[np.nan, np.inf], [2.0, 2.0], [4.0, 4.0]])
    result = stability_tables(
        data, source_key="sample", feature="f0", time_kind="stored_order", bins=2, layer="bad"
    )
    assert result["cells"].coordinate.tolist() == [0, 1, 2]
    assert result["cells"].source.nunique() == 2
    assert result["correlation"].isna().all().all()
    assert result["dependencies"] == ["sample"]
    assert result["windows"].cell_count.sum() == 3


@pytest.mark.parametrize(
    "options",
    [
        {"feature": "100.0001"},
        {"source_key": "missing"},
        {"time_kind": "unknown"},
        {"time_kind": "normalized_time"},
        {"bins": True},
        {"bins": 1},
        {"layer": "missing"},
        {"time_key": "source"},
        {"time_kind": "stored_order", "time_key": "rt"},
    ],
)
def test_stability_invalid_options_preserve_data(options):
    from scMM.analysis.stability import stability_tables

    data = AnnData(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        obs=pd.DataFrame({"source": ["a", "b"], "rt": [0.0, 2.0]}, index=["a", "b"]),
        var=pd.DataFrame(index=["f0", "f1"]),
    )
    before = data.X.copy()
    with pytest.raises(ValueError):
        stability_tables(
            data,
            **{
                "source_key": "source",
                "feature": "f0",
                "time_kind": "acquisition_seconds",
                "time_key": "rt",
                **options,
            },
        )
    np.testing.assert_array_equal(data.X, before)


def test_stability_rejects_constant_or_unrepresentable_time_bins():
    from scMM.analysis.stability import stability_tables

    for times in ([1.0, 1.0], [1e16, 1e16 + 2]):
        data = AnnData(
            np.ones((2, 2)),
            obs=pd.DataFrame({"source": ["a", "b"], "rt": times}, index=["a", "b"]),
            var=pd.DataFrame(index=["f0", "f1"]),
        )
        with pytest.raises(ValueError):
            stability_tables(
                data,
                source_key="source",
                feature="f0",
                time_key="rt",
                time_kind="acquisition_seconds",
                bins=10,
            )


def test_quality_pdf_chinese_pagination_and_complete_report_bundle():
    import io
    import json
    import zipfile

    from scMM.analysis.quality_pdf import quality_report_bytes, report_bundle

    names = ["中文来源 <b> & " + str(i) for i in range(75)]
    names[0] += "超长目录" * 500
    data = AnnData(
        np.random.default_rng(2).uniform(0, 1, (75, 3)),
        obs=pd.DataFrame(
            {
                "source_file": names,
                "cell_id": ["original"] * 75,
                "reference_intensity_100": [1.234567891234] * 75,
                "reference_intensity_missing": [None] * 75,
            },
            index=[f"c{i}" for i in range(75)],
        ),
    )
    metadata = {
        "project": "中文 & <script>",
        "dataset_id": "synthetic",
        "dataset_revision": 2,
        "unsaved": True,
        "history": [{"operation": "normalize", "parameters": {"scale": 100.123456789}}],
    }
    data.obsm["X_pca"] = np.arange(150.0).reshape(75, 2)
    before = data.copy()
    pdf = quality_report_bytes(data, metadata)
    assert pdf.startswith(b"%PDF-") and b"STSong-Light" in pdf
    assert pdf.count(b"/Type /Page\n") >= 3
    result = pd.DataFrame(
        {"feature_id": ["0", "1", "2"], "p_value": [1e-8, 0.123456789123, np.nan]}
    )
    bundle = report_bundle(
        data,
        metadata,
        {"differential": {"summary": {"defined": np.nan, "seed": np.int64(42)}, "table": result}},
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {
            "report.pdf",
            "metadata.json",
            "history.json",
            "cell_qc.csv",
            "source_qc.csv",
            "results.json",
            "results/differential.csv",
            "embeddings/embedding_001.csv",
        }
        assert json.loads(archive.read("metadata.json"))["unsaved"] is True
        assert json.loads(archive.read("results.json"))["differential"]["defined"] is None
        exported = pd.read_csv(io.BytesIO(archive.read("cell_qc.csv")))
        assert exported.cell_id.tolist() == data.obs_names.tolist()
        assert exported.obs_cell_id.tolist() == ["original"] * 75
        values = pd.read_csv(io.BytesIO(archive.read("results/differential.csv")))
        np.testing.assert_allclose(values.p_value[:2], result.p_value[:2], rtol=1e-15)
        assert json.loads(archive.read("history.json")) == metadata["history"]
    np.testing.assert_array_equal(data.X, before.X)
    pd.testing.assert_frame_equal(data.obs, before.obs)
    np.testing.assert_array_equal(data.obsm["X_pca"], before.obsm["X_pca"])


def test_quality_report_limits_invalid_metadata_and_failure_are_explicit(monkeypatch):
    from scipy import sparse

    from scMM.analysis.quality_pdf import quality_report_bytes, report_bundle, report_tables

    with pytest.raises(ValueError, match="100000"):
        report_tables(AnnData(sparse.csr_matrix((100001, 1))))
    data = AnnData(
        np.ones((2, 2)),
        obs=pd.DataFrame({"reference_intensity_1": ["not numeric", "2"]}, index=["a", "b"]),
    )
    with pytest.raises(ValueError, match="numeric"):
        quality_report_bytes(data, {})
    data.obs = pd.DataFrame(index=data.obs_names)
    with pytest.raises(ValueError, match="identifiers"):
        report_bundle(data, {}, {"../escape": {}})
    from reportlab.platypus import SimpleDocTemplate

    def fail(*_args, **_kwargs):
        raise OSError("synthetic PDF failure")

    monkeypatch.setattr(SimpleDocTemplate, "build", fail)
    with pytest.raises(OSError, match="synthetic PDF"):
        quality_report_bytes(data, {})
    assert not data.uns and not data.obsm
    np.testing.assert_array_equal(data.X, np.ones((2, 2)))
