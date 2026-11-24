"""Validate display subsets without replacing a workspace dataset or its results."""
# ruff: noqa: RUF001

import numpy as np
import pandas as pd


def group_display_names(data, key, groups):
    """Use sample labels when unique while retaining stable sample identities."""
    names = {group: group for group in groups}
    if key != "sample_id" or key not in data.obs or "sample" not in data.obs:
        return names
    identifiers = data.obs[key].astype(str)
    for group in groups:
        labels = data.obs.loc[identifiers.eq(group), "sample"].dropna().astype(str).unique()
        if len(labels) == 1 and labels[0].strip():
            names[group] = labels[0]
    counts = pd.Series(list(names.values())).value_counts()
    return {
        group: label if counts[label] == 1 else f"{label} ({group})"
        for group, label in names.items()
    }


def plot_subset(data, scope=None, *, chronological=False):
    scope = scope or {}
    mask = np.ones(data.n_obs, dtype=bool)
    for field, key in (("groups", "group_key"), ("samples", "sample_key")):
        selected = scope.get(field)
        if selected is None:
            continue
        column = scope.get(key)
        if column not in data.obs:
            raise ValueError("请选择有效的作图分组或样本列。")
        values = data.obs[column]
        if not selected or len(set(selected)) != len(selected):
            raise ValueError("作图范围不能为空或包含重复项。")
        if set(selected) - set(values.dropna().astype(str)):
            raise ValueError("作图范围包含不存在的组别或样本，请重新选择。")
        mask &= values.notna().to_numpy() & values.astype(str).isin(selected).to_numpy()
    positions = np.flatnonzero(mask)
    if not len(positions):
        raise ValueError("所选组别与样本没有共同细胞。")
    block = data[positions]
    sample_key = scope.get("sample_key")
    if chronological and sample_key in block.obs:
        samples = scope.get("samples") or sorted(
            block.obs[sample_key].dropna().astype(str).unique().tolist()
        )
        rank = block.obs[sample_key].astype(str).map({name: i for i, name in enumerate(samples)})
        order = pd.DataFrame({"sample": rank.to_numpy(), "position": np.arange(block.n_obs)})
        # rt is the event apex acquisition time; normalized/experimental time is not substituted.
        if "rt" in block.obs:
            order["rt"] = pd.to_numeric(block.obs["rt"], errors="coerce").to_numpy()
        keys = ["sample", *(["rt"] if "rt" in order else []), "position"]
        block = block[order.sort_values(keys, kind="stable", na_position="last").index.to_numpy()]
    return block
