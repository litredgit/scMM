from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import softmax
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import calibration_curve
from sklearn.cross_decomposition import PLSRegression
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    auc,
    average_precision_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    roc_curve,
)
from sklearn.model_selection import (
    GroupShuffleSplit,
    StratifiedGroupKFold,
    StratifiedKFold,
    cross_validate,
    train_test_split,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler, label_binarize


class PLSDAClassifier(ClassifierMixin, BaseEstimator):
    """PLS regression exposed through the sklearn classifier interface."""

    def __init__(self, n_components=2, max_iter=500):
        self.n_components = n_components
        self.max_iter = max_iter

    def fit(self, X, y):
        self.label_encoder_ = LabelEncoder().fit(y)
        encoded = self.label_encoder_.transform(y)
        self.classes_ = self.label_encoder_.classes_
        target = np.eye(len(self.classes_), dtype=float)[encoded]
        components = min(int(self.n_components), X.shape[1], X.shape[0] - 1)
        self.model_ = PLSRegression(n_components=max(1, components), max_iter=self.max_iter).fit(
            X, target
        )
        return self

    def predict_proba(self, X):
        values = np.asarray(self.model_.predict(X), dtype=float)
        if values.ndim == 1:
            values = values[:, None]
        if values.shape[1] == 1 and len(self.classes_) == 2:
            values = np.column_stack([-values[:, 0], values[:, 0]])
        return softmax(values, axis=1)

    def predict(self, X):
        indices = np.argmax(self.predict_proba(X), axis=1)
        return self.classes_[indices]

    def transform(self, X):
        return self.model_.transform(X)


class SupervisedAnalyzer:
    """Leakage-aware classification, validation, ROC and SHAP analysis."""

    def __init__(self, data, label_key, *, layer=None, group_key=None, random_state=42):
        if label_key not in data.obs:
            raise KeyError(f"{label_key!r} not found in data.obs")
        matrix = data.layers[layer] if layer else data.X
        if hasattr(matrix, "toarray"):
            matrix = matrix.toarray()
        labels = data.obs[label_key]
        valid = labels.notna().to_numpy()
        self.X = np.asarray(matrix, dtype=float)[valid]
        self.y = labels.astype(str).to_numpy()[valid]
        self.obs_names = data.obs_names[valid]
        self.feature_names = data.var_names.astype(str).tolist()
        self.random_state = int(random_state)
        self.groups = None
        if group_key is not None:
            groups = data.obs[group_key][valid]
            if groups.isna().any():
                raise ValueError("group labels must not be missing")
            self.groups = groups.astype(str).to_numpy()
        if not np.isfinite(self.X).all() or self.X.shape[1] == 0:
            raise ValueError("analysis requires finite values and at least one feature")
        if len(np.unique(self.y)) < 2:
            raise ValueError("supervised analysis requires at least two classes")

    def _estimator(self, model, params):
        params = dict(params)
        if model == "lda":
            return LinearDiscriminantAnalysis(**params), True
        if model in {"logistic", "lr"}:
            params.setdefault("max_iter", 5000)
            params.setdefault("class_weight", "balanced")
            params.setdefault("random_state", self.random_state)
            return LogisticRegression(**params), True
        if model in {"plsda", "pls-da"}:
            return PLSDAClassifier(**params), True
        if model in {"random_forest", "rf"}:
            params.setdefault("n_estimators", 500)
            params.setdefault("class_weight", "balanced")
            params.setdefault("random_state", self.random_state)
            params.setdefault("n_jobs", -1)
            return RandomForestClassifier(**params), False
        raise ValueError("model must be lda, plsda, logistic or random_forest")

    def build_pipeline(self, model="logistic", *, smote=False, model_params=None):
        estimator, needs_scale = self._estimator(model, model_params or {})
        steps = []
        if needs_scale or smote:
            steps.append(("scale", StandardScaler()))
        if smote:
            try:
                from imblearn.over_sampling import SMOTE
                from imblearn.pipeline import Pipeline as ImbalancedPipeline
            except ImportError as exc:
                raise ImportError(
                    "SMOTE requires the optional imbalanced-learn dependency"
                ) from exc
            steps.append(("smote", SMOTE(random_state=self.random_state)))
            steps.append(("model", estimator))
            return ImbalancedPipeline(steps)
        steps.append(("model", estimator))
        return Pipeline(steps)

    def evaluate(
        self,
        model="logistic",
        *,
        test_size=0.2,
        cv=5,
        smote=False,
        model_params=None,
        calibration_bins=10,
    ):
        if (
            isinstance(calibration_bins, bool)
            or not isinstance(calibration_bins, (int, np.integer))
            or calibration_bins < 2
        ):
            raise ValueError("calibration_bins must be an integer of at least two")
        counts = pd.Series(self.y).value_counts()
        if counts.min() < 2:
            raise ValueError("every class needs at least two observations")
        indices = np.arange(len(self.y))
        if self.groups is None:
            train, test = train_test_split(
                indices, test_size=test_size, random_state=self.random_state, stratify=self.y
            )
        else:
            train, test = next(
                GroupShuffleSplit(
                    n_splits=1, test_size=test_size, random_state=self.random_state
                ).split(self.X, self.y, self.groups)
            )
        X_train, X_test = self.X[train], self.X[test]
        y_train, y_test = self.y[train], self.y[test]
        names_test = self.obs_names[test]
        expected_classes = set(self.y)
        if set(y_train) != expected_classes or set(y_test) != expected_classes:
            raise ValueError(
                "holdout must contain every class in train and test; adjust groups/test_size"
            )
        folds = min(int(cv), int(pd.Series(y_train).value_counts().min()))
        if folds < 2:
            raise ValueError("training data cannot support two CV folds")
        pipeline = self.build_pipeline(model, smote=smote, model_params=model_params)
        splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=self.random_state)
        groups_train = None if self.groups is None else self.groups[train]
        if groups_train is not None:
            folds = min(folds, len(np.unique(groups_train)))
            if folds < 2:
                raise ValueError("training data cannot support two grouped CV folds")
            splitter = StratifiedGroupKFold(
                n_splits=folds, shuffle=True, random_state=self.random_state
            )
        splits = list(splitter.split(X_train, y_train, groups_train))
        for fit_indices, validation_indices in splits:
            if (
                set(y_train[fit_indices]) != expected_classes
                or set(y_train[validation_indices]) != expected_classes
            ):
                raise ValueError(
                    "every CV fold must contain every class; reduce cv or revise groups"
                )
            if smote and pd.Series(y_train[fit_indices]).value_counts().min() < 6:
                raise ValueError(
                    "SMOTE needs at least six observations per class in each training fold"
                )
        scoring = {
            "accuracy": "accuracy",
            "balanced_accuracy": "balanced_accuracy",
            "f1_macro": "f1_macro",
            "roc_auc": "roc_auc_ovr_weighted",
        }
        cv_result = cross_validate(
            pipeline,
            X_train,
            y_train,
            cv=splits,
            scoring=scoring,
            return_train_score=False,
            error_score="raise",
        )
        pipeline.fit(X_train, y_train)
        prediction = pipeline.predict(X_test)
        probabilities = pipeline.predict_proba(X_test)
        classes = np.asarray(pipeline.classes_)
        metrics = {
            "accuracy": float(accuracy_score(y_test, prediction)),
            "balanced_accuracy": float(balanced_accuracy_score(y_test, prediction)),
            "f1_macro": float(f1_score(y_test, prediction, average="macro")),
        }
        self.model_ = pipeline
        self.model_name_ = model
        self.classes_ = classes
        self.X_train_ = X_train
        self.X_test_ = X_test
        self.y_train_ = y_train
        self.y_test_ = y_test
        self.test_obs_names_ = names_test
        self.train_obs_names_ = self.obs_names[train]
        self.train_groups_ = groups_train
        self.test_groups_ = None if self.groups is None else self.groups[test]
        self.prediction_ = prediction
        self.probabilities_ = probabilities
        self.calibration_bins_ = int(calibration_bins)
        binary = self._test_targets()
        average_precision = {
            str(name): float(average_precision_score(binary[:, i], probabilities[:, i]))
            for i, name in enumerate(classes)
        }
        brier = {
            str(name): float(np.mean((probabilities[:, i] - binary[:, i]) ** 2))
            for i, name in enumerate(classes)
        }
        self.result_ = {
            "model": model,
            "smote": bool(smote),
            "test_metrics": metrics,
            "probability_diagnostics": {
                "average_precision_by_class": average_precision,
                "average_precision_macro": float(np.mean(list(average_precision.values()))),
                "brier_by_class": brier,
                "brier_macro": float(np.mean(list(brier.values()))),
                "definition": "Held-out one-vs-rest AP and mean squared probability error; "
                "macro is the unweighted class mean (not summed multiclass Brier).",
            },
            "cv_metrics": {
                key.replace("test_", ""): {
                    "mean": float(np.nanmean(value)),
                    "std": float(np.nanstd(value)),
                }
                for key, value in cv_result.items()
                if key.startswith("test_")
            },
            "confusion_matrix": confusion_matrix(y_test, prediction, labels=classes),
            "classification_report": classification_report(
                y_test,
                prediction,
                labels=classes,
                output_dict=True,
                zero_division=0,
            ),
        }
        return self.result_

    def _test_targets(self):
        self._require_fitted()
        return (self.y_test_[:, None] == self.classes_[None, :]).astype(int)

    def precision_recall_curves(self):
        """Held-out one-vs-rest curves; AP is not trapezoidal PR AUC."""
        binary = self._test_targets()
        curves = {}
        for i, name in enumerate(self.classes_):
            precision, recall, thresholds = precision_recall_curve(
                binary[:, i], self.probabilities_[:, i]
            )
            curves[str(name)] = {
                "precision": precision,
                "recall": recall,
                "thresholds": thresholds,
                "average_precision": float(
                    average_precision_score(binary[:, i], self.probabilities_[:, i])
                ),
            }
        return curves

    @property
    def supports_latent_scores(self):
        self._require_fitted()
        estimator = self.model_.named_steps["model"]
        return isinstance(estimator, PLSDAClassifier) or (
            isinstance(estimator, LinearDiscriminantAnalysis) and estimator.solver != "lsqr"
        )

    def latent_scores(self):
        """Scores of labeled observations; scaling is fitted on training data only."""
        self._require_fitted()
        if not self.supports_latent_scores:
            raise ValueError("latent scores require PLS-DA or LDA with svd/eigen (not lsqr)")
        values = self.X.copy()
        for name, step in self.model_.named_steps.items():
            if name not in {"model", "smote"}:
                values = step.transform(values)
        scores = np.asarray(self.model_.named_steps["model"].transform(values))
        if scores.ndim == 1:
            scores = scores[:, None]
        return pd.DataFrame(
            scores,
            index=self.obs_names,
            columns=[f"component_{i + 1}" for i in range(scores.shape[1])],
        )

    def calibration_curves(self):
        """Quantile-bin reliability data, not a fitted probability calibrator.

        Empty/duplicate bins are omitted by sklearn. Held-out observations must
        not subsequently be used to tune the model on the basis of these curves.
        """
        binary = self._test_targets()
        curves = {}
        for i, name in enumerate(self.classes_):
            observed, predicted = calibration_curve(
                binary[:, i],
                self.probabilities_[:, i],
                n_bins=self.calibration_bins_,
                strategy="quantile",
            )
            curves[str(name)] = {
                "fraction_of_positives": observed,
                "mean_predicted_probability": predicted,
            }
        return curves

    def roc_curves(self):
        self._require_fitted()
        binary = label_binarize(self.y_test_, classes=self.classes_)
        if len(self.classes_) == 2:
            binary = np.column_stack([1 - binary[:, 0], binary[:, 0]])
        curves = {}
        for index, class_name in enumerate(self.classes_):
            fpr, tpr, thresholds = roc_curve(binary[:, index], self.probabilities_[:, index])
            curves[str(class_name)] = {
                "fpr": fpr,
                "tpr": tpr,
                "thresholds": thresholds,
                "auc": float(auc(fpr, tpr)),
            }
        return curves

    def plot_roc(self, output_file):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5, 5))
        for class_name, values in self.roc_curves().items():
            ax.plot(
                values["fpr"],
                values["tpr"],
                label=f"{class_name} (AUC={values['auc']:.3f})",
            )
        ax.plot([0, 1], [0, 1], linestyle="--", color="gray")
        ax.set_xlabel("False positive rate")
        ax.set_ylabel("True positive rate")
        ax.legend()
        fig.tight_layout()
        target = Path(output_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        plt.close(fig)
        return target

    def explain_shap(
        self,
        *,
        max_background=100,
        max_samples=100,
        seed=42,
    ):
        self._require_fitted()
        try:
            import shap
        except ImportError as exc:
            raise ImportError("SHAP requires the optional shap dependency") from exc
        rng = np.random.default_rng(seed)
        background_index = rng.choice(
            len(self.X_train_),
            size=min(max_background, len(self.X_train_)),
            replace=False,
        )
        sample_index = rng.choice(
            len(self.X_test_),
            size=min(max_samples, len(self.X_test_)),
            replace=False,
        )
        background = self.X_train_[background_index]
        samples = self.X_test_[sample_index]
        estimator = self.model_.named_steps["model"]
        transformed_background = background
        transformed_samples = samples
        for name, step in self.model_.named_steps.items():
            if name in {"model", "smote"}:
                continue
            transformed_background = step.transform(transformed_background)
            transformed_samples = step.transform(transformed_samples)

        if isinstance(estimator, RandomForestClassifier):
            explainer = shap.TreeExplainer(
                estimator,
                transformed_background,
                feature_names=self.feature_names,
            )
            explanation = explainer(transformed_samples)
        elif isinstance(estimator, LogisticRegression):
            explainer = shap.LinearExplainer(
                estimator,
                transformed_background,
                feature_names=self.feature_names,
            )
            explanation = explainer(transformed_samples)
        else:
            explainer = shap.Explainer(
                self.model_.predict_proba,
                background,
                feature_names=self.feature_names,
                output_names=self.classes_.astype(str).tolist(),
                seed=seed,
            )
            explanation = explainer(samples)
        self.shap_explanation_ = explanation
        self.shap_obs_names_ = self.test_obs_names_[sample_index]
        return explanation

    def plot_shap(self, output_file, *, class_index=None, max_display=20):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import shap

        explanation = getattr(self, "shap_explanation_", None)
        if explanation is None:
            explanation = self.explain_shap()
        if len(explanation.shape) == 3:
            if class_index is None:
                class_index = 1 if explanation.shape[2] == 2 else 0
            explanation = explanation[..., int(class_index)]
        shap.plots.beeswarm(explanation, max_display=max_display, show=False)
        target = Path(output_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        plt.gcf().savefig(target, bbox_inches="tight")
        plt.close(plt.gcf())
        return target

    def _require_fitted(self):
        if not hasattr(self, "model_"):
            raise RuntimeError("call evaluate before using fitted-model outputs")
