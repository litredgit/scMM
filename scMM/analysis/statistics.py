"""Feature comparisons on nonnegative, unscaled abundance matrices."""

import numpy as np
import pandas as pd
from scipy import stats


def _bh_fdr(p_values):
    p = np.asarray(p_values, dtype=float)
    result = np.full_like(p, np.nan)
    valid = np.isfinite(p)
    values = p[valid]
    order = np.argsort(values)
    adjusted = values[order] * len(values) / np.arange(1, len(values) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    restored = np.empty_like(adjusted)
    restored[order] = np.minimum(adjusted, 1.0)
    result[valid] = restored
    return result


def differential_features(
    data, group_key, group_a, group_b, *, method="mannwhitney", min_present=3, layer=None
):
    """Compare cells in two groups; cells are the statistical unit.

    For biological replicate inference, aggregate by replicate upstream.
    Input must be finite and nonnegative so fold changes remain meaningful.
    """
    if method not in {"mannwhitney", "welch", "ttest"}:
        raise ValueError("method must be mannwhitney or welch")
    if min_present < 2 or str(group_a) == str(group_b):
        raise ValueError("distinct groups with at least two cells are required")
    labels = data.obs[group_key]
    a_mask = (labels.notna() & (labels.astype(str) == str(group_a))).to_numpy()
    b_mask = (labels.notna() & (labels.astype(str) == str(group_b))).to_numpy()
    if min(a_mask.sum(), b_mask.sum()) < min_present:
        raise ValueError("each group must contain at least min_present cells")
    X = data.layers[layer] if layer else data.X
    X = X.toarray() if hasattr(X, "toarray") else np.asarray(X)
    if not np.isfinite(X).all() or (X < 0).any():
        raise ValueError("differential features require finite nonnegative abundances")
    if data.n_vars == 0:
        raise ValueError("at least one feature is required")
    rows = []
    eps = np.finfo(float).eps
    for i, name in enumerate(data.var_names):
        a, b = X[a_mask, i], X[b_mask, i]
        if np.ptp(np.concatenate([a, b])) == 0:
            statistic, p_value = 0.0, 1.0
        elif method == "mannwhitney":
            statistic, p_value = stats.mannwhitneyu(a, b, alternative="two-sided")
        elif np.var(a) == 0 and np.var(b) == 0:
            statistic, p_value = np.sign(a[0] - b[0]) * np.inf, 0.0
        else:
            statistic, p_value = stats.ttest_ind(a, b, equal_var=False)
        rows.append(
            {
                "feature_id": name,
                "mz": data.var.iloc[i].get("mz", np.nan),
                "mean_a": float(a.mean()),
                "mean_b": float(b.mean()),
                "log2_fold_change": float(np.log2((a.mean() + eps) / (b.mean() + eps))),
                "statistic": float(statistic),
                "p_value": float(p_value),
            }
        )
    result = pd.DataFrame(rows)
    result["fdr"] = _bh_fdr(result["p_value"])
    return result.sort_values(["fdr", "p_value"], ignore_index=True)


def marker_features(data, cluster_key="cluster", **kwargs):
    """Compare each cluster against other labeled cells without mutating data."""
    labels = data.obs[cluster_key]
    subset = data[labels.notna()].copy()
    labels = subset.obs[cluster_key].astype(str)
    if labels.nunique() < 2:
        raise ValueError("at least two clusters are required")
    tables = []
    for cluster in sorted(labels.unique()):
        subset.obs["__scmm_marker_group"] = np.where(labels == cluster, "target", "rest")
        table = differential_features(subset, "__scmm_marker_group", "target", "rest", **kwargs)
        table.insert(0, "cluster", cluster)
        tables.append(table)
    return pd.concat(tables, ignore_index=True)
