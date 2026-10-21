"""Explicit preprocessing options, without changing legacy numerical defaults."""

import re
from numbers import Integral, Real

import numpy as np


def integer(name, value, low, high=None):
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or value < low
        or (high is not None and value > high)
    ):
        raise ValueError(f"{name} is outside the supported integer range")
    return int(value)


def real(name, value, low=0, *, inclusive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not np.isfinite(value)
        or (value < low if inclusive else value <= low)
    ):
        raise ValueError(f"{name} must be finite and in the supported range")
    return float(value)


def normalization_options(method, *, scale=1.0, axis=None, reference="median", pseudo=1e-6):
    if method == "total":
        return {"scale": real("scale", scale)}
    if method in {"max", "zscore", "minmax"}:
        if axis is None:
            axis = 1 if method == "max" else 0
        return {"axis": integer("axis", axis, 0, 1)}
    if method == "pqn":
        if reference not in {"median", "mean"}:
            raise ValueError(
                "reference must be median or mean; custom vectors use the Python normalization API"
            )
        return {"reference": reference}
    if method == "log":
        return {"pseudo": real("pseudo", pseudo, inclusive=True)}
    if method != "quantile":
        raise ValueError("unsupported normalization method")
    return {}


def imputation_estimator(method, cells, neighbors=5, weights="uniform"):
    from sklearn.impute import KNNImputer, SimpleImputer

    if method == "knn":
        # Existing defaults allow <5 cells; record the effective capped donor count.
        neighbors = integer("n_neighbors", neighbors, 1)
        if weights not in {"uniform", "distance"}:
            raise ValueError("weights must be uniform or distance")
        params = {"n_neighbors": min(neighbors, cells), "weights": weights}
        return KNNImputer(missing_values=0, keep_empty_features=True, **params), params
    if method not in {"mean", "median", "most_frequent"}:
        raise ValueError("unsupported imputation method")
    return SimpleImputer(strategy=method, missing_values=0, keep_empty_features=True), {
        "strategy": method
    }


def _subsample(name, value, maximum, *, auto=False):
    if isinstance(value, str):
        if auto and value == "auto":
            return "auto"
        if re.fullmatch(r"[0-9]+", value):
            value = int(value)
        elif re.fullmatch(r"[0-9]*\.[0-9]+", value):
            value = float(value)
        else:
            raise ValueError(f"{name} must be an integer count or decimal fraction")
    if isinstance(value, Integral) and not isinstance(value, bool):
        return integer(name, value, 1, maximum)
    value = real(name, value)
    if value > 1:
        raise ValueError(f"{name} fraction must be within (0, 1]")
    if name == "max_samples" and int(value * maximum) < 1:
        raise ValueError("max_samples fraction selects no cells")
    return value


def outlier_options(
    shape, *, contamination, random_state, n_estimators, max_samples, max_features, bootstrap
):
    if shape[0] < 2:
        raise ValueError("outlier detection requires at least two cells")
    contamination = real("contamination", contamination)
    if contamination > 0.5:
        raise ValueError("contamination must be within (0, 0.5]")
    if not isinstance(bootstrap, bool):
        raise ValueError("bootstrap must be boolean")
    return {
        "contamination": contamination,
        "random_state": integer("random_state", random_state, 0, 2147483647),
        "n_estimators": integer("n_estimators", n_estimators, 1, 10000),
        "max_samples": _subsample("max_samples", max_samples, shape[0], auto=True),
        "max_features": _subsample("max_features", max_features, shape[1]),
        "bootstrap": bootstrap,
    }
