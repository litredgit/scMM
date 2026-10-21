"""Primitive model parameter whitelist and solver/sample compatibility checks."""

from collections.abc import Mapping
from numbers import Integral

from .preprocessing import integer, real

DEFAULTS = {
    "logistic": {
        "C": 1.0,
        "tol": 1e-4,
        "max_iter": 5000,
        "solver": "lbfgs",
        "penalty": "l2",
        "class_weight": "balanced",
        "fit_intercept": True,
        "l1_ratio": None,
    },
    "lda": {
        "solver": "svd",
        "shrinkage": None,
        "n_components": None,
        "tol": 1e-4,
        "store_covariance": False,
    },
    "plsda": {"n_components": 2, "max_iter": 500},
    "random_forest": {
        "n_estimators": 500,
        "max_depth": None,
        "min_samples_split": 2,
        "min_samples_leaf": 1,
        "max_features": "sqrt",
        "bootstrap": True,
        "class_weight": "balanced",
        "criterion": "gini",
        "max_samples": None,
        "n_jobs": -1,
    },
}


def _boolean(name, value):
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _choice(name, value, choices):
    if not isinstance(value, (str, type(None))) or value not in choices:
        raise ValueError(f"unsupported {name}")
    return value


def _count_or_fraction(name, value, minimum):
    if isinstance(value, str):
        import re

        if re.fullmatch(r"[0-9]+", value):
            value = int(value)
        elif re.fullmatch(r"[0-9]*\.[0-9]+", value):
            value = float(value)
        else:
            raise ValueError(f"{name} requires an integer count or decimal fraction")
    if isinstance(value, Integral) and not isinstance(value, bool):
        return integer(name, value, minimum)
    value = real(name, value)
    if value > 1 or (name == "min_samples_leaf" and value == 1):
        raise ValueError(f"{name} fraction is outside the supported range")
    return value


def model_parameters(model, params=None, *, n_features=None, n_classes=None, min_fit_cells=None):
    if not isinstance(model, str):
        raise ValueError("model must be a supported name")
    model = {"lr": "logistic", "rf": "random_forest", "pls-da": "plsda"}.get(model, model)
    if model not in DEFAULTS or (params is not None and not isinstance(params, Mapping)):
        raise ValueError("unsupported model or parameter mapping")
    supplied = {} if params is None else dict(params)
    allowed = set(DEFAULTS[model]) | (
        {"random_state"} if model in {"logistic", "random_forest"} else set()
    )
    if set(supplied) - allowed:
        raise ValueError(
            f"unsupported {model} model parameters: {sorted(map(str, set(supplied) - allowed))}"
        )
    values = {**DEFAULTS[model], **supplied}
    if "random_state" in supplied:
        values["random_state"] = (
            None
            if supplied["random_state"] is None
            else integer("random_state", supplied["random_state"], 0, 2147483647)
        )
    if model == "logistic":
        for key in ("C", "tol"):
            values[key] = real(key, values[key])
        values["max_iter"] = integer("max_iter", values["max_iter"], 1, 100000)
        solver = _choice(
            "solver",
            values["solver"],
            {"lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"},
        )
        penalty = _choice("penalty", values["penalty"], {None, "l1", "l2", "elasticnet"})
        _choice("class_weight", values["class_weight"], {None, "balanced"})
        _boolean("fit_intercept", values["fit_intercept"])
        if penalty == "l1" and solver not in {"liblinear", "saga"}:
            raise ValueError("l1 requires liblinear or saga")
        if solver == "liblinear" and (
            penalty not in {"l1", "l2"} or (n_classes is not None and n_classes > 2)
        ):
            raise ValueError("liblinear supports only binary l1/l2 in this pipeline")
        ratio = values["l1_ratio"]
        if penalty == "elasticnet":
            if solver != "saga" or ratio is None:
                raise ValueError("elasticnet requires saga and an explicit l1_ratio")
            values["l1_ratio"] = real("l1_ratio", ratio, inclusive=True)
            if values["l1_ratio"] > 1:
                raise ValueError("l1_ratio must be within [0,1]")
        elif ratio is not None:
            raise ValueError("l1_ratio only applies to elasticnet")
        if penalty is None and values["C"] != 1.0:
            raise ValueError("C must remain 1 when penalty is disabled")
    elif model == "lda":
        _choice("solver", values["solver"], {"svd", "lsqr", "eigen"})
        shrinkage = values["shrinkage"]
        if shrinkage is not None:
            if values["solver"] == "svd":
                raise ValueError("LDA shrinkage requires lsqr or eigen")
            if not (isinstance(shrinkage, str) and shrinkage == "auto"):
                values["shrinkage"] = real("shrinkage", shrinkage, inclusive=True)
                if values["shrinkage"] > 1:
                    raise ValueError("shrinkage must be within [0,1]")
        if values["n_components"] is not None:
            upper = (
                min(n_features, n_classes - 1)
                if n_features is not None and n_classes is not None
                else None
            )
            values["n_components"] = integer("n_components", values["n_components"], 1, upper)
        values["tol"] = real("tol", values["tol"])
        _boolean("store_covariance", values["store_covariance"])
    elif model == "plsda":
        values["n_components"] = integer("n_components", values["n_components"], 1, 1000)
        values["max_iter"] = integer("max_iter", values["max_iter"], 1, 100000)
    else:
        values["n_estimators"] = integer("n_estimators", values["n_estimators"], 1, 10000)
        if values["max_depth"] is not None:
            values["max_depth"] = integer("max_depth", values["max_depth"], 1)
        for key, minimum in (("min_samples_split", 2), ("min_samples_leaf", 1)):
            values[key] = _count_or_fraction(key, values[key], minimum)
        features = values["max_features"]
        if features is not None and not (
            isinstance(features, str) and features in {"sqrt", "log2"}
        ):
            values["max_features"] = _count_or_fraction("max_features", features, 1)
            if (
                isinstance(values["max_features"], int)
                and n_features is not None
                and values["max_features"] > n_features
            ):
                raise ValueError("max_features exceeds the input feature count")
        _boolean("bootstrap", values["bootstrap"])
        _choice("class_weight", values["class_weight"], {None, "balanced", "balanced_subsample"})
        _choice("criterion", values["criterion"], {"gini", "entropy", "log_loss"})
        samples = values["max_samples"]
        if samples is not None:
            if not values["bootstrap"]:
                raise ValueError("max_samples requires bootstrap")
            values["max_samples"] = _count_or_fraction("max_samples", samples, 1)
            if min_fit_cells is not None and (
                (isinstance(values["max_samples"], int) and values["max_samples"] > min_fit_cells)
                or (
                    isinstance(values["max_samples"], float)
                    and values["max_samples"] * min_fit_cells < 1
                )
            ):
                raise ValueError("max_samples is incompatible with the smallest training fold")
        values["n_jobs"] = integer("n_jobs", values["n_jobs"], -1, 1024)
        if values["n_jobs"] == 0:
            raise ValueError("n_jobs must be -1 or positive")
    return values
