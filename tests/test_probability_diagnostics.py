import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from sklearn.metrics import average_precision_score

from scMM.analysis import SupervisedAnalyzer


@pytest.mark.parametrize("n_classes", [2, 3])
def test_holdout_diagnostics_preserve_group_splits(n_classes, monkeypatch):
    rng = np.random.default_rng(14)
    labels = np.tile([str(i) for i in range(n_classes)], 40)
    data = AnnData(
        rng.normal(size=(len(labels), 5)),
        obs=pd.DataFrame(
            {"label": labels, "sample": np.repeat(np.arange(20), n_classes * 2)},
            index=[f"c{i}" for i in range(len(labels))],
        ),
    )
    from sklearn.linear_model import LogisticRegression

    original_fit = LogisticRegression.fit
    fits = []

    def fit(self, X, y, *args, **kwargs):
        fits.append(len(y))
        return original_fit(self, X, y, *args, **kwargs)

    monkeypatch.setattr(LogisticRegression, "fit", fit)
    analyzer = SupervisedAnalyzer(data, "label", group_key="sample")
    result = analyzer.evaluate(cv=3, calibration_bins=4)
    assert len(fits) == 4  # one CV round plus one holdout model
    assert set(analyzer.train_groups_).isdisjoint(analyzer.test_groups_)
    diagnostics = result["probability_diagnostics"]
    curves = analyzer.precision_recall_curves()
    calibration = analyzer.calibration_curves()
    for i, name in enumerate(analyzer.classes_):
        target = (analyzer.y_test_ == name).astype(int)
        probability = analyzer.probabilities_[:, i]
        expected_ap = average_precision_score(target, probability)
        assert diagnostics["average_precision_by_class"][name] == pytest.approx(expected_ap)
        assert curves[name]["average_precision"] == pytest.approx(expected_ap)
        assert len(curves[name]["thresholds"]) + 1 == len(curves[name]["recall"])
        assert diagnostics["brier_by_class"][name] == pytest.approx(
            np.mean((target - probability) ** 2)
        )
        assert 1 <= len(calibration[name]["fraction_of_positives"]) <= 4
    assert diagnostics["brier_macro"] == pytest.approx(
        np.mean(list(diagnostics["brier_by_class"].values()))
    )


def test_diagnostics_validation_missing_labels_and_constant_probabilities():
    data = AnnData(
        np.tile(np.arange(4), (61, 1)).astype(float),
        obs=pd.DataFrame({"label": ["a", "b"] * 30 + [None]}, index=list(map(str, range(61)))),
    )
    analyzer = SupervisedAnalyzer(data, "label")
    for method in (analyzer.precision_recall_curves, analyzer.calibration_curves):
        with pytest.raises(RuntimeError, match="evaluate"):
            method()
    for value in [True, 0, 1, 2.5, "4"]:
        with pytest.raises(ValueError, match="calibration_bins"):
            analyzer.evaluate(calibration_bins=value)
    analyzer.evaluate(cv=3)
    assert "60" not in analyzer.test_obs_names_
    assert "60" not in analyzer.train_obs_names_
    for values in analyzer.calibration_curves().values():
        assert len(values["fraction_of_positives"]) == 1
