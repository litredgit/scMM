"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

import json
import os

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.application import StorageCatalog, StorageRoot
from scMM.application.workbench import AnalysisWorkspace, read_dataset


def example():
    from scMM.util.intensity import write_intensity_states

    data = AnnData(
        np.random.default_rng(12).uniform(1, 3, (80, 5)),
        obs=pd.DataFrame(
            {"condition": ["a", "b"] * 40, "sample": np.repeat(np.arange(20).astype(str), 4)},
            index=[f"cell{i}" for i in range(80)],
        ),
        var=pd.DataFrame({"mz": np.arange(100.0, 105.0)}, index=list(map(str, range(100, 105)))),
    )
    write_intensity_states(data, {"X": "raw"})
    return data


def workspace():
    state = AnalysisWorkspace()
    state.replace(example(), source="synthetic")
    return state


def test_preprocessing_history_invalidation_and_reset():
    state = workspace()
    original = state.data.X.copy()
    token = state.token
    state.differential("condition", "a", "b")
    state.reduce("pca", store_key="X_pca")
    state.cluster("kmeans", use_rep="X_pca")
    state.normalize("total")
    assert not state.results
    assert not state.data.obsm
    assert "clusters" not in state.data.obs
    original_layer = state.data.uns["scmm_workbench"]["original_layer"]
    np.testing.assert_array_equal(state.data.layers[original_layer], original)
    np.testing.assert_allclose(state.data.X.sum(axis=1), 1)
    with pytest.raises(RuntimeError, match="stale"):
        state.put_result("old", {}, token)
    state.restore(original_layer)
    np.testing.assert_array_equal(state.data.X, original)
    state.filter(min_total=float(np.median(original.sum(axis=1))))
    assert state.data.n_obs == 40
    state.reset()
    np.testing.assert_array_equal(state.data.X, original)
    assert state.data.n_obs == 80
    state.replace(example())
    assert state.token[0] != token[0]
    assert not state.results


def test_failed_mutation_is_transactional():
    state = workspace()
    before = state.data.copy()
    token = state.token
    with pytest.raises(ValueError):
        state.filter(min_total=1e10)
    assert token == state.token
    np.testing.assert_array_equal(state.data.X, before.X)
    with pytest.raises(ValueError):
        state.normalize("unknown")
    assert token == state.token


def test_zero_imputation_preserves_shape_and_history():
    data = example()
    data.X[:, 0] = 0
    data.X[0, 1] = 0
    state = AnalysisWorkspace()
    state.replace(data)
    state.impute("knn")
    assert state.data.shape == data.shape
    assert np.isfinite(state.data.X).all()
    assert state.history()[-1]["operation"] == "impute"


def test_h5ad_history_safe_save_and_read(tmp_path):
    catalog = StorageCatalog([StorageRoot("云盘", tmp_path)])
    state = workspace()
    state.normalize("total")
    state.reduce("pca", store_key="X_pca")
    target = state.save_h5ad(catalog, "云盘", ".", "结果.h5ad")
    stored = read_h5ad(target)
    np.testing.assert_array_equal(stored.X, state.data.X)
    assert len(stored.layers) == 2
    assert json.loads(stored.uns["scmm_workbench"]["history_json"])[-1]["operation"] == "reduce"
    restored = read_dataset(catalog, "云盘", "结果.h5ad")
    np.testing.assert_array_equal(restored.obsm["X_pca"], stored.obsm["X_pca"])
    with pytest.raises(FileExistsError):
        state.save_h5ad(catalog, "云盘", ".", "结果.h5ad")
    with pytest.raises(ValueError):
        state.save_h5ad(catalog, "云盘", ".", "../escape.h5ad")
    if os.name != "nt":
        with pytest.raises(ValueError, match="Windows"):
            catalog.resolve("云盘", "C:\\data\\result.h5ad")


@pytest.mark.parametrize("operation", ["raw", "normalize", "impute"])
def test_imported_intensity_keeps_baseline_state_across_reset_restore(tmp_path, operation):
    from scMM.util.intensity import intensity_states
    from scMM.util.lipid_annotation import dataset_inputs
    from scMM.util.lipid_network import intensity_layers

    state = workspace()
    if operation != "raw":
        getattr(state, operation)("total" if operation == "normalize" else "median")
    path = tmp_path / "processed.h5ad"
    state.data.write_h5ad(path)
    imported = AnalysisWorkspace()
    imported.replace(read_h5ad(path))
    before = imported.data.X.copy()
    expected = {"raw": "raw", "normalize": "normalized", "impute": "transformed"}[operation]
    for _ in range(2):
        imported.impute()
        imported.reset()
        np.testing.assert_array_equal(imported.data.X, before)
        assert intensity_states(imported.data)["X"] == expected
        layers = intensity_layers(imported.data)
        assert ("X" in layers["raw"]) == (operation == "raw")
        assert ("X" in layers["molecule"]) == (operation != "impute")
        reset_layer = imported.history()[-1]["layer"]
        assert intensity_states(imported.data)[reset_layer] == expected
        imported.restore(reset_layer)
        assert intensity_states(imported.data)["X"] == expected
        if operation == "raw":
            dataset_inputs(imported.data, "X")
        else:
            with pytest.raises(ValueError):
                dataset_inputs(imported.data, "X")
        # The original input layer remains raw even when the import baseline is processed.
        dataset_inputs(imported.data)
        imported.data.write_h5ad(path)
        imported.replace(read_h5ad(path))


def test_invalid_provenance_import_preserves_usable_workspace():
    from scMM.util.intensity import PROVENANCE_KEY

    state = workspace()
    before, token = state.data, state.token
    bad = example()
    bad.uns[PROVENANCE_KEY] = '{"schema_version": 2, "states": {"X": "raw"}}'
    with pytest.raises(ValueError, match="intensity provenance"):
        state.replace(bad)
    assert state.data is before and state.token == token


@pytest.mark.parametrize("model,params", [("lda", {}), ("plsda", {})])
def test_latent_scores_align_and_roundtrip(tmp_path, model, params):
    state = workspace()
    state.data.obs.loc["cell0", "condition"] = None
    model_object = state.train(
        "condition", group_key="sample", model=model, cv=3, model_params=params
    )
    assert model_object.supports_latent_scores
    state.save_latent("X_latent")
    assert np.isnan(state.data.obsm["X_latent"][0]).all()
    assert state.data.obs.loc["cell0", "X_latent_split"] == "unlabeled"
    assert set(state.data.obs.X_latent_split) == {"train", "test", "unlabeled"}
    catalog = StorageCatalog([StorageRoot("Out", tmp_path)])
    target = state.save_h5ad(catalog, "Out", ".", "latent.h5ad")
    np.testing.assert_allclose(
        read_h5ad(target).obsm["X_latent"], state.data.obsm["X_latent"], equal_nan=True
    )


def test_lsqr_is_valid_classifier_without_latent_and_failed_training_clears_result():
    state = workspace()
    model = state.train("condition", model="lda", cv=3, model_params={"solver": "lsqr"})
    assert not model.supports_latent_scores
    with pytest.raises(ValueError, match="lsqr"):
        state.save_latent("latent")
    with pytest.raises(ValueError):
        state.train("condition", model="unknown")
    assert "supervised" not in state.results


def test_legacy_requires_trust_and_rejects_child_symlink(tmp_path):
    from scMM.file.data import CyESIData

    result = CyESIData.from_anndata(example()).save(tmp_path)
    catalog = StorageCatalog([StorageRoot("Root", result)])
    with pytest.raises(PermissionError, match="trust"):
        read_dataset(catalog, "Root", ".")
    assert read_dataset(catalog, "Root", ".", trust_pickle=True).shape == (80, 5)
    outside = tmp_path / "outside.pkl"
    (result / "data.pkl").rename(outside)
    (result / "data.pkl").symlink_to(outside)
    with pytest.raises(PermissionError, match="outside"):
        read_dataset(catalog, "Root", ".", trust_pickle=True)


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


def test_dbscan_parameters_change_labels_and_survive_h5ad(tmp_path):
    state = AnalysisWorkspace()
    matrix = np.array([[0, 0], [0, 0.1], [5, 5], [5, 5.1], [10, 0]], dtype=float)
    state.replace(AnnData(matrix))
    state.cluster("dbscan", key="tuned", eps=0.3, min_samples=2, metric="euclidean")
    assert state.data.obs["tuned"].astype(str).tolist() == ["0", "0", "1", "1", "-1"]
    state.cluster("dbscan", key="small_radius", eps=0.05, min_samples=2)
    assert set(state.data.obs["small_radius"].astype(str)) == {"-1"}
    effective = state.history()[-2]["parameters"]["effective_parameters"]
    assert effective == {"eps": 0.3, "min_samples": 2, "metric": "euclidean"}
    target = state.save_h5ad(
        StorageCatalog([StorageRoot("output", tmp_path)]), "output", ".", "clusters.h5ad"
    )
    loaded = AnalysisWorkspace()
    loaded.replace(read_h5ad(target))
    assert loaded.history()[-2]["parameters"]["effective_parameters"] == effective
    pd.testing.assert_series_equal(loaded.data.obs["tuned"], state.data.obs["tuned"])
    np.testing.assert_array_equal(state.data.X, matrix)


@pytest.mark.parametrize(
    "method,options",
    [
        ("dbscan", {"eps": 0}),
        ("dbscan", {"eps": float("nan")}),
        ("dbscan", {"min_samples": True}),
        ("dbscan", {"min_samples": 1.5}),
        ("hierarchical", {"linkage": "ward", "metric": "cosine"}),
        ("hierarchical", {"metric": "precomputed"}),
        ("kmeans", {"n_clusters": 81}),
        ("kmeans", {"n_init": 0}),
        ("kmeans", {"tol": -1}),
        ("leiden", {"resolution": 0}),
        ("leiden", {"n_iterations": 0}),
        ("leiden", {"n_iterations": -1.0}),
        ("louvain", {"threshold": -1}),
        ("louvain", {"max_level": 0}),
        ("leiden", {"n_neighbors": 80}),
    ],
)
def test_clustering_parameter_errors_are_atomic(method, options):
    state = workspace()
    before = state.data.copy()
    token = state.token
    with pytest.raises(ValueError):
        state.cluster(method, key="invalid", **options)
    assert state.token == token and not state.history()
    assert "invalid" not in state.data.obs
    np.testing.assert_array_equal(state.data.X, before.X)
    pd.testing.assert_frame_equal(state.data.obs, before.obs)


@pytest.mark.parametrize(
    "method,options",
    [
        ("kmeans", {"n_init": 4, "max_iter": 80, "tol": 0.001}),
        ("hierarchical", {"linkage": "average", "metric": "manhattan"}),
        ("leiden", {"resolution": 0.5, "n_neighbors": 5, "n_iterations": 3}),
        ("louvain", {"resolution": 0.7, "n_neighbors": 6, "threshold": 1e-6, "max_level": 2}),
    ],
)
def test_clustering_effective_parameters_and_output_key_protection(method, options):
    if method == "leiden":
        pytest.importorskip("leidenalg")
    state = workspace()
    state.cluster(method, key="explicit", **options)
    history = state.history()[-1]["parameters"]
    for key, value in options.items():
        assert history["effective_parameters"][key] == value
    before = state.token
    labels = state.data.obs["explicit"].copy()
    with pytest.raises(ValueError, match="already exists"):
        state.cluster(method, key="explicit", **options)
    assert state.token == before
    pd.testing.assert_series_equal(state.data.obs["explicit"], labels)


@pytest.mark.parametrize("method", ["leiden", "louvain"])
def test_graph_resolution_changes_real_partition(method):
    if method == "leiden":
        pytest.importorskip("leidenalg")
    from scMM.analysis.clustering import cluster_matrix

    matrix = np.random.default_rng(9).normal(size=(60, 4))
    low, _ = cluster_matrix(matrix, method, n_neighbors=6, resolution=0.1)
    high, _ = cluster_matrix(matrix, method, n_neighbors=6, resolution=4)
    repeated, _ = cluster_matrix(matrix, method, n_neighbors=6, resolution=4)
    assert len(np.unique(low)) < len(np.unique(high))
    np.testing.assert_array_equal(high, repeated)


def test_advanced_preprocessing_values_history_and_failure_atomicity(tmp_path):
    state = workspace()
    before = state.data.X.copy()
    state.normalize("total", scale=100)
    np.testing.assert_allclose(state.data.X.sum(axis=1), 100)
    assert state.history()[-1]["parameters"]["effective_parameters"] == {"scale": 100.0}
    state.reset()
    state.normalize("max", axis=0)
    np.testing.assert_allclose(state.data.X.max(axis=0), 1)
    state.reset()
    state.normalize("pqn", reference="mean")
    from scMM.util.normalize import normalize

    np.testing.assert_allclose(state.data.X, normalize(before, "pqn", {"reference": "mean"}))
    state.reset()
    state.normalize("log", pseudo=0)
    np.testing.assert_allclose(state.data.X, np.log1p(before))
    snapshot, token = state.data.copy(), state.token
    for invoke in (
        lambda: state.normalize("total", scale=float("nan")),
        lambda: state.normalize("zscore", axis=True),
        lambda: state.normalize("pqn", reference="unknown"),
        lambda: state.impute("knn", n_neighbors=0),
        lambda: state.impute("knn", n_neighbors=1.2),
        lambda: state.remove_outliers(n_estimators=True),
        lambda: state.remove_outliers(max_samples=81),
        lambda: state.remove_outliers(max_samples=0.001),
        lambda: state.remove_outliers(max_features=6),
        lambda: state.remove_outliers(max_samples="2garbage"),
        lambda: state.remove_outliers(bootstrap=1),
    ):
        with pytest.raises(ValueError):
            invoke()
        assert state.token == token
        np.testing.assert_array_equal(state.data.X, snapshot.X)
    state.data.X[:] = -2
    with pytest.raises(ValueError, match="undefined"):
        state.normalize("log")
    assert state.token == token


def test_advanced_imputation_donors_and_outlier_reproducibility():
    data = AnnData(np.array([[0.0, 0.0, 1.0], [2.0, 0.0, 2.0], [8.0, 0.0, 4.0], [2.0, 0.0, 8.0]]))
    state = AnalysisWorkspace()
    state.replace(data)
    state.impute("most_frequent")
    assert state.data.X[0, 0] == 2
    np.testing.assert_array_equal(state.data.X[:, 1], 0)
    state.reset()
    state.impute("knn", n_neighbors=1, weights="distance")
    assert state.data.X[0, 0] == 2
    assert state.history()[-1]["parameters"]["effective_parameters"] == {
        "n_neighbors": 1,
        "weights": "distance",
    }
    state.reset()
    state.impute("knn", n_neighbors=20)
    assert state.history()[-1]["parameters"]["effective_parameters"]["n_neighbors"] == 4
    first, second = workspace(), workspace()
    for target in (first, second):
        target.remove_outliers(
            n_estimators=13, max_samples="0.5", max_features="1.0", bootstrap=True, random_state=19
        )
    assert first.data.obs_names.equals(second.data.obs_names)
    params = first.history()[-1]["parameters"]["effective_parameters"]
    assert params["max_features"] == 1.0 and isinstance(params["max_features"], float)
    assert params["max_samples"] == 0.5 and params["n_estimators"] == 13


def test_explicit_subset_axes_layers_results_and_full_reset(tmp_path):
    state = workspace()
    state.data.layers["other"] = 3 * state.data.X
    initial = state.data.copy()
    state.reduce("pca", store_key="X_pca")
    state.differential("condition", "a", "b")
    state.subset(cell_ids=["cell5", "cell1", "cell3"], feature_ids=["104", "100"])
    assert state.data.obs_names.tolist() == ["cell5", "cell1", "cell3"]
    assert state.data.var_names.tolist() == ["104", "100"]
    from scMM.util.intensity import intensity_states

    assert intensity_states(state.data)["X"] == "raw"
    np.testing.assert_array_equal(
        state.data.X, initial[["cell5", "cell1", "cell3"], ["104", "100"]].X
    )
    assert state.data.obs.condition.tolist() == ["b", "b", "b"]
    assert not state.results and not state.data.obsm
    for matrix in state.data.layers.values():
        assert matrix.shape == (3, 2)
    for key in initial.layers:
        np.testing.assert_array_equal(
            state.data.layers[key], initial[["cell5", "cell1", "cell3"], ["104", "100"]].layers[key]
        )
    state.reset()
    np.testing.assert_array_equal(state.data.X, initial.X)
    assert state.data.obs_names.equals(initial.obs_names)
    assert state.data.var_names.equals(initial.var_names)


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"cell_ids": []},
        {"feature_ids": []},
        {"cell_ids": ["cell1", "cell1"]},
        {"cell_ids": ["missing"]},
        {"feature_ids": ["100.0001"]},
        {"cell_ids": [1]},
    ],
)
def test_subset_invalid_ids_preserve_every_state(options):
    state = workspace()
    token, matrix = state.token, state.data.X.copy()
    with pytest.raises(ValueError):
        state.subset(**options)
    assert state.token == token and state.history() == []
    np.testing.assert_array_equal(state.data.X, matrix)
