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
