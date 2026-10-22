"""Numerical contracts for classifier markers, PCA dimensions and replot exports."""

import io
import zipfile

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.analysis.heatmap import heatmap_figure
from scMM.analysis.markers import classifier_markers
from scMM.application.web_support import figure_view
from scMM.plot.export import data_archive, publication_pdf
from scMM.plot.workbench import embedding_figure


def dataset():
    rng = np.random.default_rng(42)
    matrix = rng.uniform(0, 1, (60, 5))
    matrix[:20, 0] += 8
    matrix[20:40, 1] += 8
    matrix[40:, 2] += 8
    return AnnData(
        matrix,
        obs=pd.DataFrame(
            {"group": ["A"] * 20 + ["B"] * 20 + ["C"] * 20, "sample": ["one"] * 10 + ["two"] * 50},
            index=[f"c{i}" for i in range(60)],
        ),
        var=pd.DataFrame({"mz": np.arange(5) + 100.0}, index=[f"f{i}" for i in range(5)]),
    )


def test_classifier_marker_direction_and_stability():
    data = dataset()
    result = classifier_markers(data, "group", cv=3)
    assert len(result) == 15
    for group, feature in [("A", "f0"), ("B", "f1"), ("C", "f2")]:
        first = result[result.group == group].iloc[0]
        assert first.feature_id == feature
        assert first.weight > 0 and first.sign_stability == 1
    np.testing.assert_array_equal(result.weight, classifier_markers(data, "group", cv=3).weight)


def test_heatmap_sample_equal_aggregation_and_no_mutation():
    data = dataset()
    before = data.X.copy()
    figure = heatmap_figure(
        data, features=["f0", "f1"], group_key="group", sample_key="sample", equal_samples=True
    )
    tables = figure.layout.meta["export_tables"]
    actual = pd.read_csv(io.StringIO(tables["aggregate.csv"]), index_col=0)
    expected = (
        data.to_df()
        .join(data.obs)
        .groupby(["group", "sample"])[["f0", "f1"]]
        .mean()
        .groupby(level=0)
        .mean()
        .T
    )
    np.testing.assert_allclose(actual, expected)
    np.testing.assert_array_equal(data.X, before)
    display = pd.read_csv(io.StringIO(tables["display.csv"]), index_col=0)
    np.testing.assert_allclose(display.mean(axis=1), 0, atol=1e-15)
    archive = zipfile.ZipFile(io.BytesIO(data_archive(figure_view(figure))))
    assert {"source.csv", "aggregate.csv", "display.csv", "annotations.csv"} <= set(
        archive.namelist()
    )


def test_heatmap_selected_samples_keep_order_and_acquisition_time_without_mutation():
    data = AnnData(
        np.arange(12.0).reshape(6, 2),
        obs=pd.DataFrame(
            {
                "sample": ["A", "B", "A", "C", "B", "C"],
                "group": ["keep", "keep", "keep", "other", "keep", "other"],
                "rt": [2, 8, 1, 1, 3, 2],
            },
            index=list("abcdef"),
        ),
        var=pd.DataFrame(index=["f0", "f1"]),
    )
    scope = {
        "sample_key": "sample",
        "samples": ["B", "A"],
        "group_key": "group",
        "groups": ["keep"],
    }
    figure = heatmap_figure(
        data,
        features=["f0", "f1"],
        scope=scope,
        cluster_columns=False,
        cluster_rows=False,
        zscore=False,
        colorscale="Cividis",
        color_min=0,
        color_max=10,
    )
    assert figure.layout.meta["column_order"] == ["e", "b", "c", "a"]
    assert list(figure.layout.xaxis.categoryarray) == ["e", "b", "c", "a"]
    assert figure.layout.meta["selected_cells"] == 4
    source = pd.read_csv(
        io.StringIO(figure.layout.meta["export_tables"]["source.csv"]), index_col=0
    )
    np.testing.assert_array_equal(source.to_numpy(), data[list("ebca")].X.T)
    assert figure.data[0].zmin == 0 and figure.data[0].zmax == 10
    group_strip = figure.data[1]
    assert group_strip.zmin == -0.5 and group_strip.zmax == 0.5
    assert group_strip.colorscale[0][1] == group_strip.colorscale[-1][1] == "#0072B2"
    assert data.obs_names.tolist() == list("abcdef")
    averaged = heatmap_figure(
        data, features=["f0"], scope=scope, group_key="sample", cluster_columns=False
    )
    assert averaged.layout.meta["column_order"] == ["B", "A"]
    for invalid in (
        {**scope, "samples": []},
        {**scope, "groups": ["missing"]},
        {**scope, "groups": ["other"]},
    ):
        with pytest.raises(ValueError):
            heatmap_figure(data, features=["f0"], scope=invalid)
    with pytest.raises(ValueError, match="色阶"):
        heatmap_figure(data, features=["f0"], color_min=1)


def test_heatmap_without_rt_keeps_stable_order_and_zscore_uses_selected_scope():
    data = dataset()
    figure = heatmap_figure(
        data,
        features=["f0"],
        cluster_columns=False,
        scope={
            "sample_key": "sample",
            "samples": ["two", "one"],
            "group_key": "group",
            "groups": ["A"],
        },
    )
    assert figure.layout.meta["column_order"] == [f"c{i}" for i in [*range(10, 20), *range(10)]]
    display = np.asarray(figure.data[0].z)
    assert display.shape == (1, 20)
    np.testing.assert_allclose(display.mean(axis=1), 0, atol=1e-14)
    np.testing.assert_allclose(display.std(axis=1), 1)


def test_cell_pdf_requires_real_arial_instead_of_silent_substitution(monkeypatch):
    from matplotlib import font_manager

    def missing(*args, **kwargs):
        raise ValueError("Arial unavailable")

    monkeypatch.setattr(font_manager, "findfont", missing)
    with pytest.raises(ValueError, match="Arial"):
        publication_pdf(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"/>',
            85,
            65,
            font_family="Arial",
        )


def test_pca_selected_axes_ratio_and_complete_export():
    from scMM.analysis.embedding import reduce_dimension

    data = dataset()
    reduce_dimension(data, "pca", store_key="X_pca", n_components=4)
    figure = embedding_figure(data, "X_pca", dimensions=[2, 3, 4], color="obs:group")
    assert figure.data[0].type == "scatter3d"
    assert figure.layout.meta["dimensions"] == [2, 3, 4]
    assert "PC2" in figure.layout.scene.xaxis.title.text
    frame = pd.read_csv(io.StringIO(figure.layout.meta["export_tables"]["coordinates"]))
    assert len(frame) == 60 and "component_4" in frame
    with pytest.raises(ValueError):
        embedding_figure(data, "X_pca", dimensions=[1, 1])


def test_pdf_is_vector_and_rejects_external_resources():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><text x="2" y="20">Science</text><path d="M0 30L90 30" stroke="black"/></svg>'
    pdf = publication_pdf(svg, 89, 65)
    assert pdf.startswith(b"%PDF-") and b"/Subtype /Image" not in pdf
    for bad in [
        '<image href="http://127.0.0.1/secret"/>',
        "<script>hi</script>",
        '<path style="fill:url(file:///etc/passwd)"/>',
    ]:
        with pytest.raises(ValueError):
            publication_pdf('<svg xmlns="http://www.w3.org/2000/svg">' + bad + "</svg>", 89, 65)


def test_candidate_sum_composition_preserves_linkage():
    from scMM.util.lipid_names import species_label

    assert species_label("PC(16:1/18:0)") == species_label("PC(16:0/18:1)") == "PC(34:1)"
    assert species_label("PC(O-16:0/18:1)") == "PC(O-34:1)"
    assert species_label("PC(P-16:0/18:1)") != "PC(34:1)"


def test_fraction_filter_uses_all_input_features_and_keeps_equality():
    from scMM.application.workbench import AnalysisWorkspace

    state = AnalysisWorkspace()
    state.replace(AnnData(np.array([[1.0, 0, 0, 0, 0], [1.0, 1, 0, 0, 0], [0.0, 0, 0, 0, 0]])))
    state.filter(min_detected=0.2, min_feature_fraction=0.8)
    assert state.data.shape == (2, 1)
    assert state._original.shape == (3, 5)
    assert state.history()[-1]["parameters"]["min_detected"] == 0.2


def test_dehydrated_protonated_adduct_matches_ion_chemistry():
    from pyopenms import EmpiricalFormula

    from scMM.util.lipid_isotopes import adduct_shift, fine_distribution

    np.testing.assert_allclose(
        adduct_shift("[M+H-H2O]+"),
        adduct_shift("[M+H]+") - EmpiricalFormula("H2O").getMonoWeight(),
        rtol=0,
        atol=1e-12,
    )
    assert fine_distribution("C34H66NO8P", "[M+H-H2O]+", 3)


def test_binary_plot_arrays_keep_precision_and_encode_missing_breaks():
    import plotly.graph_objects as go

    figure = go.Figure(
        go.Scatter(x=np.array([1.0, np.nan, 3.0]), y=np.array([1.2345678901234567, np.nan, 1e-19]))
    )
    archive = zipfile.ZipFile(io.BytesIO(data_archive(figure_view(figure))))
    payload = __import__("json").loads(archive.read("figure.json"))
    assert payload["data"][0]["x"] == [1.0, None, 3.0]
    assert payload["data"][0]["y"][0] == 1.2345678901234567
    assert payload["data"][0]["y"][2] == 1e-19


def test_non_network_statistics_import_without_networkx(monkeypatch):
    import importlib
    import sys

    import scMM.analysis.statistics as statistics

    monkeypatch.setitem(sys.modules, "networkx", None)
    module = importlib.reload(statistics)
    data = dataset()
    assert not module.marker_features(data, "group").empty
    with pytest.raises(ImportError, match="networkx"):
        module.feature_correlation_network(data)


def test_pdf_preserves_svg_definition_namespace_and_clipping(caplog):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><defs><clipPath id="plotclip"><rect width="10" height="20"/></clipPath></defs><g clip-path="url(#plotclip)"><path d="M0 0L90 30" stroke="black"/></g></svg>'
    assert publication_pdf(svg, 89, 65).startswith(b"%PDF-")
    assert "Unable to find a clipping path" not in caplog.text


def test_violin_cell_identity_survives_hidden_zeros():
    from scMM.plot.workbench import violin_figure

    data = dataset()
    data.X[0, 0] = 0
    result = {
        "group_key": "group",
        "layer": None,
        "group_a": "A",
        "group_b": "B",
        "table": pd.DataFrame({"feature_id": ["f0"], "mz": [100.0], "fdr": [0.02]}),
    }
    figure = violin_figure(data, result, ["f0"], hide_zero=True)
    assert figure.layout.meta["point_kind"] == "cell"
    cells = np.asarray(figure.data[0].customdata)[:, 0]
    assert "c0" not in cells and cells.tolist() == data.obs_names[1:20].tolist()
    np.testing.assert_array_equal(figure.data[0].y, data[cells, "f0"].X[:, 0])
