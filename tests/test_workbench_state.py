import json
import os

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.application import StorageCatalog, StorageRoot
from scMM.application.workbench import AnalysisWorkspace, read_dataset


def example():
    return AnnData(
        np.random.default_rng(12).uniform(1, 3, (80, 5)),
        obs=pd.DataFrame(
            {"condition": ["a", "b"] * 40, "sample": np.repeat(np.arange(20).astype(str), 4)},
            index=[f"cell{i}" for i in range(80)],
        ),
        var=pd.DataFrame({"mz": np.arange(100.0, 105.0)}, index=list(map(str, range(100, 105)))),
    )


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
