"""Explicit-input reduction without changing existing PlotEngine method signatures."""

import numpy as np
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE, Isomap, LocallyLinearEmbedding
from sklearn.preprocessing import StandardScaler


def reduce_dimension(
    data,
    method="pca",
    *,
    use_rep=None,
    n_components=2,
    scale=False,
    random_state=42,
    n_neighbors=15,
    perplexity=30.0,
    min_dist=0.3,
    store_key=None,
):
    """Compute and store an embedding from X or an explicitly named obsm.

    Invalid small-sample settings fail instead of silently changing the input or
    requested dimensions. Metadata records every effective algorithm parameter.
    """
    source = "X" if use_rep in {None, "X"} else f"obsm:{use_rep}"
    matrix = data.X if source == "X" else data.obsm[use_rep]
    values = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or min(values.shape) < 1 or not np.isfinite(values).all():
        raise ValueError("reduction requires a finite non-empty matrix")
    if isinstance(n_components, bool) or not isinstance(n_components, int) or n_components < 1:
        raise ValueError("n_components must be a positive integer")
    if values.shape[0] < 3:
        raise ValueError("reduction requires at least three observations")
    if scale:
        values = StandardScaler().fit_transform(values)
    method = method.lower()
    params = {"n_components": n_components}
    if method == "pca":
        if n_components > min(values.shape):
            raise ValueError("PCA dimensions exceed observations or input features")
        params["random_state"] = random_state
        model = PCA(**params)
    elif method == "tsne":
        if not np.isfinite(perplexity) or not 0 < perplexity < len(values):
            raise ValueError("perplexity must be positive and below n_obs")
        params.update(
            perplexity=perplexity,
            random_state=random_state,
            init="random",
            learning_rate="auto",
            method="exact" if n_components > 3 else "barnes_hut",
        )
        model = TSNE(**params)
    elif method in {"umap", "isomap", "lle"}:
        if (
            isinstance(n_neighbors, bool)
            or not isinstance(n_neighbors, int)
            or not 2 <= n_neighbors < len(values)
        ):
            raise ValueError("n_neighbors must be an integer between 2 and n_obs - 1")
        params["n_neighbors"] = n_neighbors
        if method == "umap":
            from umap import UMAP

            if not np.isfinite(min_dist) or not 0 <= min_dist <= 1:
                raise ValueError("min_dist must be between zero and one")
            params.update(min_dist=min_dist, random_state=random_state, init="random", n_jobs=1)
            model = UMAP(**params)
        elif method == "isomap":
            if n_components >= len(values):
                raise ValueError("Isomap dimensions must be below n_obs")
            model = Isomap(**params)
        else:
            if n_components >= n_neighbors or n_components > values.shape[1]:
                raise ValueError(
                    "LLE dimensions must be below n_neighbors and not exceed input features"
                )
            params.update(random_state=random_state, eigen_solver="dense")
            model = LocallyLinearEmbedding(**params)
    else:
        raise ValueError("method must be pca, umap, tsne, isomap or lle")
    key = store_key or f"X_{method}"
    if not isinstance(key, str) or not key or "/" in key:
        raise ValueError("store_key must be a nonempty H5AD-safe key")
    embedding = model.fit_transform(values)
    if not np.isfinite(embedding).all():
        raise ValueError("reduction produced non-finite coordinates")
    data.obsm[key] = embedding
    data.uns[f"{key}_params"] = {"method": method, "source": source, "scale": scale, **params}
    return embedding
