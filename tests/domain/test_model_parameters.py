"""Model contracts cover ignored combinations and smallest-fold feasibility."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.analysis.model_parameters import model_parameters
from scMM.analysis.supervised import SupervisedAnalyzer


def example():
    return AnnData(
        X=np.random.default_rng(12).uniform(1, 4, (80, 5)),
        obs=pd.DataFrame(
            {"label": ["a", "b"] * 40, "sample": np.repeat(np.arange(20).astype(str), 4)},
            index=[f"cell{i}" for i in range(80)],
        ),
    )


@pytest.mark.parametrize(
    "model,params",
    [
        ("logistic", {"C": 0}),
        ("logistic", {"solver": "lbfgs", "penalty": "l1"}),
        ("logistic", {"penalty": "elasticnet", "solver": "saga"}),
        ("logistic", {"l1_ratio": 0.5}),
        ("logistic", {"class_weight": {}}),
        ("lda", {"shrinkage": "auto"}),
        ("lda", {"solver": "eigen", "shrinkage": 2}),
        ("lda", {"store_covariance": 1}),
        ("plsda", {"n_components": True}),
        ("random_forest", {"max_depth": 1.5}),
        ("random_forest", {"min_samples_leaf": 1.0}),
        ("random_forest", {"bootstrap": False, "max_samples": 2}),
        ("random_forest", {"max_features": []}),
        ("random_forest", {"n_jobs": 0}),
        ("random_forest", {"min_samples_split": "1e-2"}),
        ("logistic", {"unknown": 1}),
    ],
)
def test_invalid_model_contracts(model, params):
    with pytest.raises(ValueError):
        model_parameters(model, params)


def test_counts_fractions_and_fold_bounds():
    counts = model_parameters(
        "rf", {"max_features": "1", "max_samples": "2", "min_samples_leaf": "1"}
    )
    fractions = model_parameters(
        "rf", {"max_features": "1.0", "max_samples": "0.5", "min_samples_leaf": "0.1"}
    )
    assert type(counts["max_features"]) is int
    assert type(fractions["max_features"]) is float
    for params, bounds in [
        ({"max_features": 6}, {"n_features": 5}),
        ({"max_samples": 11}, {"min_fit_cells": 10}),
        ({"max_samples": 0.01}, {"min_fit_cells": 10}),
    ]:
        with pytest.raises(ValueError):
            model_parameters("rf", params, **bounds)
    with pytest.raises(ValueError):
        model_parameters("lda", {"n_components": 2}, n_features=5, n_classes=2)
    with pytest.raises(ValueError):
        model_parameters("logistic", {"solver": "liblinear"}, n_classes=3)


@pytest.mark.parametrize(
    "model,params,key,value",
    [
        ("logistic", {"C": 0.2, "fit_intercept": False}, "C", 0.2),
        ("lda", {"solver": "lsqr", "shrinkage": "auto"}, "shrinkage", "auto"),
        ("plsda", {"n_components": 1, "max_iter": 200}, "n_components", 1),
        (
            "random_forest",
            {"n_estimators": 7, "n_jobs": 1, "max_depth": 2, "max_samples": "0.7"},
            "max_depth",
            2,
        ),
    ],
)
def test_parameters_are_fitted_and_reported(model, params, key, value):
    analyzer = SupervisedAnalyzer(example(), "label", group_key="sample", random_state=72)
    result = analyzer.evaluate(model, cv=3, model_params=params)
    effective = result["training_parameters"]["effective_model_params"]
    assert effective[key] == value
    assert result["training_parameters"]["model_params"] == params
    if model in {"logistic", "random_forest"}:
        assert effective["random_state"] == 72
    if model == "plsda":
        assert result["training_parameters"]["pls_components_effective"]["final"] == 1
    assert np.isfinite(result["test_metrics"]["accuracy"])


def test_pls_effective_components_follow_feature_limit():
    analyzer = SupervisedAnalyzer(example()[:, :1].copy(), "label", group_key="sample")
    report = analyzer.evaluate("plsda", cv=3, model_params={"n_components": 3})
    effective = report["training_parameters"]["pls_components_effective"]
    assert effective["final"] == 1 and effective["cv"] == [1, 1, 1]
