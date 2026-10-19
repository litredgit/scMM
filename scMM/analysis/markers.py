"""One-versus-rest classifier weights, with scaling fitted inside each training fold."""

# ruff: noqa: RUF001
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def classifier_markers(data, group_key, *, layer=None, cv=5, seed=42, regularization=1.0):
    labels = data.obs[group_key]
    if labels.isna().any():
        raise ValueError("分组存在缺失值，请先补齐。")
    labels = labels.astype(str).to_numpy()
    values = data.X if layer is None else data.layers[layer]
    values = values.toarray() if sparse.issparse(values) else np.asarray(values)
    if not np.isfinite(values).all():
        raise ValueError("分类 Marker 需要有限数值。")
    groups = np.unique(labels)
    if len(groups) < 2:
        raise ValueError("至少需要两个组别。")
    rows = []
    for group in groups:
        y = (labels == group).astype(int)
        folds = min(cv, int(np.bincount(y).min()))
        if folds < 2:
            raise ValueError("每组与其余组均至少需要两个细胞。")

        def estimator():
            return make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=regularization, max_iter=3000, random_state=seed, class_weight="balanced"
                ),
            )

        weights = []
        for train, _ in StratifiedKFold(folds, shuffle=True, random_state=seed).split(values, y):
            fitted = estimator().fit(values[train], y[train])
            weights.append(fitted[-1].coef_[0])
        weights = np.asarray(weights)
        final = estimator().fit(values, y)[-1].coef_[0]
        order = np.argsort(-final, kind="stable")
        for rank, index in enumerate(order, 1):
            rows.append(
                {
                    "group": group,
                    "feature_id": str(data.var_names[index]),
                    "rank": rank,
                    "weight": float(final[index]),
                    "positive": bool(final[index] > 0),
                    "cv_mean": float(weights[:, index].mean()),
                    "cv_std": float(weights[:, index].std()),
                    "sign_stability": float(
                        np.mean(np.sign(weights[:, index]) == np.sign(final[index]))
                    ),
                    "cv": folds,
                }
            )
    return pd.DataFrame(rows)
