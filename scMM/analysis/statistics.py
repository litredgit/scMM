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
    data,
    group_key,
    group_a,
    group_b,
    *,
    method="mannwhitney",
    min_present=3,
    layer=None,
    effect_layer=None,
    test_layer=None,
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
    from scMM.ion.semantics import value_states

    if layer is not None and (effect_layer is not None or test_layer is not None):
        raise ValueError("layer cannot be combined with effect_layer/test_layer")
    effect_layer = layer if layer is not None else effect_layer
    test_layer = layer if layer is not None else test_layer
    effect_key, test_key = effect_layer or "X", test_layer or "X"
    state = value_states(data)[effect_key]
    strict = "scmm_analysis_input_json" in data.uns
    if state["space"] != "linear_abundance" and (strict or state["space"] != "unknown"):
        raise ValueError("fold change requires known linear_abundance effect input")
    X = data.X if effect_key == "X" else data.layers[effect_key]
    X = X.toarray() if hasattr(X, "toarray") else np.asarray(X)
    if not np.isfinite(X).all() or (X < 0).any():
        raise ValueError("differential features require finite nonnegative abundances")
    tests = data.X if test_key == "X" else data.layers[test_key]
    tests = tests.toarray() if hasattr(tests, "toarray") else np.asarray(tests)
    if not np.isfinite(tests).all():
        raise ValueError("differential test input must be finite")
    if data.n_vars == 0:
        raise ValueError("at least one feature is required")
    rows = []
    eps = np.finfo(float).eps
    for i, name in enumerate(data.var_names):
        abundance_a, abundance_b = X[a_mask, i], X[b_mask, i]
        a, b = tests[a_mask, i], tests[b_mask, i]
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
                "mean_a": float(abundance_a.mean()),
                "mean_b": float(abundance_b.mean()),
                "log2_fold_change": float(
                    np.log2((abundance_a.mean() + eps) / (abundance_b.mean() + eps))
                ),
                "statistic": float(statistic),
                "p_value": float(p_value),
            }
        )
    result = pd.DataFrame(rows)
    result["fdr"] = _bh_fdr(result["p_value"])
    result = result.sort_values(["fdr", "p_value"], ignore_index=True)
    result.attrs["input"] = {
        "effect_layer": effect_key,
        "test_layer": test_key,
        "statistical_unit": "cell",
        "effect_space": state["space"],
        "legacy_unverified_abundance": state["space"] == "unknown",
        "biological_replication": "not established by cell count",
    }
    return result


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


def feature_correlation_network(
    data, *, method="pearson", min_abs_correlation=0.7, top_features=None, layer=None
):
    """Variance-selected feature correlation graph; not a trajectory or causal graph."""
    if method not in {"pearson", "spearman", "kendall"}:
        raise ValueError("unknown correlation method")
    if not 0 <= min_abs_correlation <= 1:
        raise ValueError("min_abs_correlation must be between zero and one")
    try:
        import networkx as nx
    except ImportError as exc:
        raise ImportError("相关网络需要 cluster 或 web 可选依赖中的 networkx。") from exc
    matrix = data.layers[layer] if layer else data.X
    matrix = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    selected = np.arange(data.n_vars)
    if top_features is not None:
        if isinstance(top_features, bool) or int(top_features) != top_features or top_features < 1:
            raise ValueError("top_features must be a positive integer")
        selected = np.argsort(np.nanvar(matrix, axis=0))[-int(top_features) :]
    corr = pd.DataFrame(matrix[:, selected], columns=data.var_names[selected]).corr(method=method)
    graph = nx.Graph()
    graph.add_nodes_from(corr.columns)
    for i, left in enumerate(corr.columns):
        for j in range(i + 1, len(corr.columns)):
            value = float(corr.iloc[i, j])
            if np.isfinite(value) and abs(value) >= min_abs_correlation:
                graph.add_edge(left, corr.columns[j], correlation=value, weight=abs(value))
    return graph, corr
