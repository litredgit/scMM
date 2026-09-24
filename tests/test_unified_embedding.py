import sys
from types import SimpleNamespace

import numpy as np
import pytest
from anndata import AnnData

from scMM.analysis.embedding import reduce_dimension


def test_x_and_obsm_are_explicit_for_pca_and_umap(monkeypatch):
    data = AnnData(np.arange(60.0).reshape(20, 3))
    data.obsm["input"] = np.random.default_rng(1).normal(size=(20, 3))
    seen = []

    class UMAP:
        def __init__(self, **kwargs):
            self.options = kwargs

        def fit_transform(self, X):
            seen.append(X.copy())
            return X[:, :2]

    monkeypatch.setitem(sys.modules, "umap", SimpleNamespace(UMAP=UMAP))
    reduce_dimension(data, "umap", n_neighbors=5)
    np.testing.assert_array_equal(seen[-1], data.X)
    reduce_dimension(data, "umap", use_rep="input", n_neighbors=5)
    np.testing.assert_array_equal(seen[-1], data.obsm["input"])
    original = reduce_dimension(data, "pca", store_key="raw")
    selected = reduce_dimension(data, "pca", use_rep="input")
    assert not np.allclose(original, selected)
    assert data.uns["X_pca_params"]["source"] == "obsm:input"
    assert data.uns["X_umap_params"]["n_neighbors"] == 5


def test_duplicate_neighbors_exclude_self():
    from scMM.plot._engine_clustering import _build_neighbor_edges

    edges = _build_neighbor_edges(np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 1.0]]), 1)
    assert all(left != right for left, right in edges)
    assert len(edges) == 3


@pytest.mark.parametrize(
    "method,options",
    [
        ("umap", {"n_neighbors": 20}),
        ("pca", {"n_components": 4}),
        ("tsne", {"perplexity": 20}),
        ("lle", {"n_neighbors": 2, "n_components": 2}),
    ],
)
def test_small_sample_settings_fail_without_silent_changes(method, options):
    data = AnnData(np.ones((10, 3)))
    with pytest.raises(ValueError):
        reduce_dimension(data, method, **options)
    assert not data.obsm
