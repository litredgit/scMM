"""Matrix normalization methods used by scMM preprocessing."""

from collections.abc import Callable, Mapping

import numpy as np

NORM_REGISTRY: dict[str, Callable] = {}


def register_norm(name):
    def wrapper(func):
        if name in NORM_REGISTRY:
            raise ValueError(f"Normalization method already registered: {name}")
        NORM_REGISTRY[name] = func
        return func

    return wrapper


def _check_array(X):
    X = np.asarray(X, dtype=float)
    if X.ndim != 2:
        raise ValueError("Input data must be a 2D array (n_samples, n_features)")
    return X


@register_norm("total")
def norm_total(X, params):

    X = _check_array(X)
    scale = params.get("scale", 1.0)

    row_sum = X.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0] = 1.0

    return X / row_sum * scale


@register_norm("max")
def norm_max(X, params):

    X = _check_array(X)
    max_val = X.max(axis=params.get("axis", 1), keepdims=True)
    max_val[max_val == 0] = 1.0

    return X / max_val


@register_norm("quantile")
def norm_quantile(X, params):
    X = _check_array(X)
    active = np.flatnonzero(np.any(X != 0, axis=1))
    Xn = np.zeros_like(X)
    if not len(active) or not X.shape[1]:
        return Xn
    mean_quantiles = np.sort(X[active], axis=1).mean(axis=0)
    for i in active:
        order = np.argsort(X[i], kind="stable")
        values = X[i, order]
        starts = np.r_[0, np.flatnonzero(np.diff(values)) + 1]
        stops = np.r_[starts[1:], len(values)]
        for start, stop in zip(starts, stops, strict=True):
            Xn[i, order[start:stop]] = mean_quantiles[start:stop].mean()

    return Xn


@register_norm("pqn")
def norm_pqn(X, params):
    return pqn_with_counts(X, params)[0]


def _abundance(X):
    X = _check_array(X)
    if not np.isfinite(X).all() or (X < 0).any():
        raise ValueError("归一化输入必须是有限的非负强度。")
    return X


def pqn_with_counts(X, params):
    """Normalize by the median ratio over paired positive detections."""
    X = _abundance(X)
    present = X > 0
    active = present.any(axis=1)
    reference = params.get("reference", "median")
    if isinstance(reference, str):
        reducers = {"median": np.nanmedian, "mean": np.nanmean}
        if reference not in reducers:
            raise ValueError("PQN reference must be median, mean or a feature vector")
        defined = present.any(axis=0)
        ref = np.zeros(X.shape[1])
        if defined.any():
            detections = X[np.ix_(active, defined)]
            detections[detections == 0] = np.nan
            ref[defined] = reducers[reference](detections, axis=0)
    else:
        ref = np.asarray(reference, dtype=float)

    if ref.shape != (X.shape[1],):
        raise ValueError("PQN reference must have one value per feature")

    if not np.isfinite(ref).all() or (ref < 0).any():
        raise ValueError("PQN 参考必须为有限非负强度。")
    shared = present & (ref > 0)
    counts = shared.sum(axis=1)
    missing = np.flatnonzero(active & (counts == 0))
    if len(missing):
        examples = ", ".join(str(index + 1) for index in missing[:10])
        raise ValueError(f"PQN 有 {len(missing)} 行缺少共同检出特征。行号示例 {examples}。")
    scale = np.ones(len(X))
    if active.any():
        ratios = np.full((int(active.sum()), X.shape[1]), np.nan)
        np.divide(X[active], ref, where=shared[active], out=ratios)
        scale[active] = np.nanmedian(ratios, axis=1)
    if not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError("PQN 缩放因子必须为有限正数。")
    return X / scale[:, None], counts


@register_norm("zscore")
def norm_zscore(X, params):

    X = _check_array(X)

    axis = params.get("axis", 0)

    mean = X.mean(axis=axis, keepdims=True)
    std = X.std(axis=axis, keepdims=True)

    std[std == 0] = 1.0
    return (X - mean) / std


@register_norm("log")
def norm_log(X, params):
    if "pseudo" in params:
        raise ValueError("对数变换已改用 log1p(X)。请移除旧参数 pseudo 后重试。")
    return np.log1p(_abundance(X))


@register_norm("minmax")
def norm_minmax(X, params):

    X = _check_array(X)

    axis = params.get("axis", 0)

    xmin = X.min(axis=axis, keepdims=True)
    xmax = X.max(axis=axis, keepdims=True)

    denom = xmax - xmin
    denom[denom == 0] = 1.0

    return (X - xmin) / denom


def _run_normalization(X, method, params):
    if method not in NORM_REGISTRY:
        raise ValueError(
            f"Unknown normalization method: {method}\nAvailable: {sorted(NORM_REGISTRY)}"
        )
    return NORM_REGISTRY[method](X, params)


def normalize(X, method="total", norm_kwargs=None, return_params=False):
    """
    Parameters
    ----------
    X : array-like (n_samples, n_features)
    method : str
        total | max | quantile | pqn | zscore | log | minmax
    norm_kwargs : dict
        Parameters for normalization function.
    return_params : bool
        When true, normalization parameters will be returned in a dict.
    """

    if norm_kwargs is None:
        norm_kwargs = {}
    elif not isinstance(norm_kwargs, Mapping):
        raise TypeError("norm_kwargs must be a mapping or None")
    else:
        norm_kwargs = dict(norm_kwargs)

    Xn = _run_normalization(X, method, norm_kwargs)

    if return_params:
        return {"X_norm": Xn, "method": method, "norm_params": norm_kwargs}

    return Xn
