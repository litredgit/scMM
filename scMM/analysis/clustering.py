"""Validated clustering of an explicitly selected matrix, with effective parameters."""

from numbers import Integral, Real

import numpy as np


def _integer(name, value, minimum, maximum=None):
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ValueError(f"{name} is outside the supported integer range")
    return int(value)


def _real(name, value, *, positive=True):
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not np.isfinite(value)
        or (value <= 0 if positive else value < 0)
    ):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return float(value)


def cluster_matrix(
    values,
    method,
    *,
    n_clusters=3,
    n_neighbors=15,
    random_state=42,
    eps=0.5,
    min_samples=5,
    resolution=1.0,
    n_init=10,
    max_iter=300,
    tol=1e-4,
    linkage="ward",
    metric="euclidean",
    n_iterations=2,
    threshold=1e-7,
    max_level=None,
):
    from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans

    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or min(values.shape) < 1 or not np.isfinite(values).all():
        raise ValueError("clustering requires a finite non-empty matrix")
    seed = _integer("random_state", random_state, 0, 2147483647)
    if method in {"kmeans", "hierarchical"}:
        count = _integer("n_clusters", n_clusters, 2, len(values))
    if method in {"dbscan", "hierarchical"} and metric not in {"euclidean", "manhattan", "cosine"}:
        raise ValueError("metric must be euclidean, manhattan or cosine")
    if method == "kmeans":
        params = {
            "n_clusters": count,
            "random_state": seed,
            "n_init": _integer("n_init", n_init, 1),
            "max_iter": _integer("max_iter", max_iter, 1),
            "tol": _real("tol", tol, positive=False),
        }
        labels = KMeans(**params).fit_predict(values)
    elif method == "hierarchical":
        if linkage not in {"ward", "complete", "average", "single"}:
            raise ValueError("unsupported hierarchical linkage")
        if linkage == "ward" and metric != "euclidean":
            raise ValueError("ward linkage requires euclidean distance")
        params = {"n_clusters": count, "linkage": linkage, "metric": metric}
        labels = AgglomerativeClustering(**params).fit_predict(values)
    elif method == "dbscan":
        params = {
            "eps": _real("eps", eps),
            "min_samples": _integer("min_samples", min_samples, 1),
            "metric": metric,
        }
        labels = DBSCAN(**params).fit_predict(values)
    elif method in {"leiden", "louvain"}:
        from scMM.plot._engine_clustering import _build_neighbor_edges, _cluster_graph

        neighbors = _integer("n_neighbors", n_neighbors, 1, len(values) - 1)
        params = {
            "resolution": _real("resolution", resolution),
            "random_state": seed,
            "n_neighbors": neighbors,
        }
        if method == "leiden":
            if (
                n_iterations == -1
                and isinstance(n_iterations, Integral)
                and not isinstance(n_iterations, bool)
            ):
                iterations = -1
            else:
                iterations = _integer("n_iterations", n_iterations, 1)
            algorithm = {"n_iterations": iterations}
        else:
            algorithm = {
                "threshold": _real("threshold", threshold, positive=False),
                "max_level": None if max_level is None else _integer("max_level", max_level, 1),
            }
        params.update(algorithm)
        labels = _cluster_graph(
            method,
            len(values),
            _build_neighbor_edges(values, neighbors),
            params["resolution"],
            seed,
            algorithm,
        )
    else:
        raise ValueError("unsupported clustering method")
    return np.asarray(labels), params
