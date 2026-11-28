import json

import numpy as np
import pandas as pd
import pyopenms as oms
import pytest
from anndata import AnnData

from scMM.analysis.exploration import association, correlated_features, memberships
from scMM.analysis.external_annotations import (
    align_annotations,
    fragment_match,
    msms_search,
    read_table,
    write_annotations,
)
from scMM.application.selection_labels import update
from scMM.application.workbench import AnalysisWorkspace
from scMM.file.io import align_frame, extract_peaks, sum_spec
from scMM.file.selection import selected_frames


def dataset():
    return AnnData(
        np.array([[1.0, 0, 3], [2, 1, 4], [3, 0, 5], [4, 1, 6], [5, 0, 7], [6, 1, 8]]),
        obs=pd.DataFrame(
            {
                "group": ["a"] * 3 + ["b"] * 3,
                "rep": ["r1", "r1", "r2", "r2", "r3", "r3"],
                "numeric": np.arange(6.0),
            },
            index=[f"c{i}" for i in range(6)],
        ),
        var=pd.DataFrame({"mz": [500.0, 600.0, 700.0]}, index=["a", "b", "c"]),
    )


def test_valley_centroids_separate_adjacent_peaks_and_keep_apex():
    spectrum = oms.MSSpectrum()
    spectrum.set_peaks(
        (
            500 + np.arange(17) * 0.001,
            np.array([0, 0, 0, 1, 3, 10, 7, 4, 3, 5, 8, 5, 2, 1, 0, 0, 0], float),
        )
    )
    mz, intensity = extract_peaks(spectrum, resolution_200=35000)
    np.testing.assert_allclose(mz, [500.0056785714286, 500.0103333333333], rtol=0, atol=1e-10)
    np.testing.assert_array_equal(intensity, [10, 8])
    assert mz[0] < mz[1]


def test_selection_original_frames_inclusive_ms1_and_empty():
    experiment = oms.MSExperiment()
    for i in range(5):
        spectrum = oms.MSSpectrum()
        spectrum.setRT(float(i))
        spectrum.setMSLevel(2 if i == 1 else 1)
        spectrum.set_peaks((np.array([499.99, 500.0, 500.01]), np.array([0.0, 10.0, 0.0])))
        experiment.addSpectrum(spectrum)
    assert [i for i, _ in selected_frames(experiment, rt_range=[1, 4], frame_range=[1, 3])] == [
        2,
        3,
    ]
    frame, meta = align_frame(experiment, [500.0], rt_range=[1, 4], frame_range=[1, 3])
    assert list(frame.index) == [2, 3] and list(meta.rt) == [2, 3]
    spectrum = sum_spec(experiment, mz_range=(499.98, 500.02), rt_range=[1, 4], frame_range=[1, 3])
    assert spectrum.getMetaValue("n_summed_spectra") == 2
    with pytest.raises(ValueError, match="No spectra"):
        sum_spec(experiment, mz_range=(499.98, 500.02), frame_range=[10, 20])
    with pytest.raises(ValueError):
        list(selected_frames(experiment, rt_range=[0, np.nan]))


def test_correlations_zeros_constant_and_replicate_permutation():
    data = dataset()
    figure = correlated_features(data, target="feature:a", include_zeros=False)
    table = pd.read_csv(
        __import__("io").StringIO(figure.layout.meta["export_tables"]["correlations"])
    )
    assert table.set_index("feature_id").loc["b", "n"] == 3
    assert table.set_index("feature_id").loc["c", "correlation"] == pytest.approx(1)
    with pytest.raises(ValueError, match="重复"):
        association(data, x="feature:a", y="feature:c", permutations=9)
    a = association(data, x="feature:a", y="feature:c", replicate_key="rep", permutations=99)
    b = association(data, x="feature:a", y="feature:c", replicate_key="rep", permutations=99)
    assert a.layout.meta["association"] == b.layout.meta["association"]
    assert a.layout.meta["association"]["n"] == 3


@pytest.mark.parametrize("method", ["spearman", "kendall"])
def test_rank_permutations_use_the_selected_statistic(method):
    from scipy import stats

    data = dataset()
    a, b = np.arange(6), np.array([0, 1, 1, 1, 2, 100])
    data.obs = data.obs.assign(a=a, b=b, rep=data.obs_names)
    statistic = {"spearman": stats.spearmanr, "kendall": stats.kendalltau}[method]
    rng = np.random.default_rng(19)
    observed = abs(statistic(a, b).statistic)
    expected = (
        1
        + sum(
            abs(statistic(a, rng.permutation(b)).statistic) >= observed - 1e-12 for _ in range(99)
        )
    ) / 100
    figure = association(
        data, x="obs:a", y="obs:b", replicate_key="rep", permutations=99, method=method, seed=19
    )
    assert figure.layout.meta["association"]["permutation_p"] == expected
    assert figure.data[2].name == "OLS mean-response interval"


def test_memberships_keep_stable_ids_not_names():
    data = dataset()
    data.var["name"] = ["same", "same", "other"]
    figure = memberships(data, group_key="group", groups=["a", "b"], annotation_key="name")
    text = figure.layout.meta["export_tables"]["membership"]
    assert "a,same" in text and "b,same" in text
    assert "Feature set" in figure.layout.title.text


def test_qc_histograms_and_sample_heatmap_preserve_layer_and_metadata():
    from io import StringIO

    from scMM.analysis.qc_plots import distribution_figure, sample_correlation_figure

    data = dataset()
    data.obs["sample_id"] = ["id1"] * 3 + ["id2"] * 3
    data.obs["sample"] = ["First"] * 3 + ["Second"] * 3
    data.obs["batch"] = ["Day 1"] * 3 + ["Day 2"] * 3
    inputs = data.X.copy()
    data.layers["scaled"] = data.X * 2
    figure = distribution_figure(
        data,
        metric="feature:a",
        group_key="batch",
        layer="scaled",
        relative=True,
    )
    tables = figure.layout.meta["export_tables"]
    bins = pd.read_csv(StringIO(tables["histograms"]))
    np.testing.assert_allclose(bins.groupby("group_id").fraction.sum(), [1, 1])
    np.testing.assert_array_equal(
        bins[bins.group_id == "Day 1"].left, bins[bins.group_id == "Day 2"].left
    )
    table = pd.read_csv(StringIO(tables["observations"]))
    np.testing.assert_allclose(table.value, inputs[:, 0] * 2)
    heatmap = sample_correlation_figure(data, sample_key="sample_id", square=True)
    np.testing.assert_allclose(np.diag(heatmap.data[0].z), [1, 1])
    assert list(heatmap.layout.xaxis.ticktext) == ["First", "Second"]
    assert "Day 1" in str(heatmap.data[0].customdata[0])
    np.testing.assert_array_equal(data.X, inputs)


def test_embedding_color_transform_preserves_coordinates_and_source_values():
    from io import StringIO

    from scMM.plot.workbench import embedding_figure

    data = dataset()
    data.obsm["X_test"] = np.arange(12.0).reshape(6, 2)
    data.layers["signed"] = data.X - 3.0
    figure = embedding_figure(
        data,
        "X_test",
        "feature:a",
        transform="log1p",
        colorscale="Cividis",
        color_layer="signed",
    )
    coloring = pd.read_csv(StringIO(figure.layout.meta["export_tables"]["color_values"]))
    np.testing.assert_array_equal(coloring.raw_color, [-2, -1, 0, 1, 2, 3])
    assert coloring.display_color.isna().sum() == 2
    np.testing.assert_allclose(coloring.display_color.iloc[2:], np.log1p([0, 1, 2, 3]))
    assert figure.data[-1].name == "Color unavailable"
    np.testing.assert_array_equal(data.obsm["X_test"], np.arange(12.0).reshape(6, 2))


def test_selection_rollback_toggle_and_origin_independence():
    state = AnalysisWorkspace()
    state.replace(dataset())
    original = state._original.copy()
    update(state, name="review", ids=["c0", "c1", "c2"])
    assert state.data.n_obs == 3 and state._selection_source.n_obs == 6
    token = state.token
    with pytest.raises(ValueError):
        update(state, name="none", ids=[])
    assert state.token == token
    with pytest.raises(ValueError, match="标签"):
        state.normalize(method="total")
    update(state, name="review", mode="toggle", enabled=False)
    np.testing.assert_array_equal(state.data.X, original.X)
    assert json.loads(state.data.uns["scmm_selection_json"])["cell_keep_review"]["enabled"] is False
    update(state, name="review", mode="toggle", enabled=True)
    assert state.data.n_obs == 3
    np.testing.assert_array_equal(state._original.X, original.X)


def test_annotations_no_positional_fallback_no_ambiguous_writes():
    data = dataset()
    frame = read_table("id,name\na,one\na,two\nc,three\n")
    table, matched = align_annotations(
        data, frame, mapping={"name": "manual_name"}, source_key="id"
    )
    assert list(table.status) == ["ambiguous", "unmatched", "matched"]
    with pytest.raises(ValueError, match="匹配"):
        write_annotations(data, table, matched, mapping={"name": "manual_name"})
    assert "manual_name" not in data.var
    frame = read_table("id,name\na,one\nc,three\n")
    table, matched = align_annotations(
        data, frame, mapping={"name": "manual_name"}, source_key="id"
    )
    updated = write_annotations(data, table, matched, mapping={"name": "manual_name"})
    assert list(updated.var.manual_name) == ["one", "", "three"]
    assert "manual_name" not in data.var


def test_fragment_matching_one_to_one_and_all_candidates():
    score, matches = fragment_match([[100, 4], [100.0001, 9], [200, 1]], [[100, 4], [200, 1]], 20)
    assert len(matches) == 2 and 0 < score < 1
    text = "BEGIN IONS\nTITLE=pool scan\nPEPMASS=500\n100 4\n200 1\nEND IONS\n"
    lib = text.replace("pool scan", "candidate one") + text.replace("pool scan", "candidate two")
    figure = msms_search(
        dataset(),
        measured=text,
        library=lib,
        sample_pool="pooled samples",
        polarity="positive",
        minimum_matches=2,
    )
    table = pd.read_csv(
        __import__("io").StringIO(figure.layout.meta["export_tables"]["candidates"])
    )
    assert len(table) == 2 and table.passes_threshold.all()
    assert table.candidate_id.nunique() == 2
    assert (table.scope == "pool_evidence_not_individual_cell_identity").all()


def test_standalone_filtered_matrix_cannot_invent_missing_pool():
    state = AnalysisWorkspace()
    state.replace(dataset())
    update(state, name="review", ids=["c0", "c1", "c2"])
    imported = AnalysisWorkspace()
    imported.replace(state.data)
    with pytest.raises(ValueError, match="恢复池"):
        update(imported, name="review", mode="toggle", enabled=False)


def test_manual_mass_alignment_ignores_invalid_reference_masses():
    frame = read_table("mass,name\n0,invalid\nNaN,missing\n500,valid\n")
    table, matched = align_annotations(
        dataset(), frame, mapping={"name": "manual_name"}, source_key="mass", target_key="mz"
    )
    assert matched.tolist() == [True, False, False]
    assert table.manual_name.iloc[0] == "valid"


def test_msms_polarity_contradiction_is_rejected():
    spectrum = "BEGIN IONS\nPEPMASS=500\nCHARGE=1-\n100 1\nEND IONS\n"
    with pytest.raises(ValueError, match="极性"):
        msms_search(
            dataset(), measured=spectrum, library=spectrum, sample_pool="pool", polarity="positive"
        )
