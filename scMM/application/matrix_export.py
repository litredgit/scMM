"""Cell rows and a single class column for MetaboAnalyst matrix downloads."""
# ruff: noqa: RUF001

import pandas as pd


def matrix_csv(data, *, features=None, group_key="group", labels=None):
    if labels is None:
        if group_key not in data.obs or data.obs[group_key].isna().any():
            raise ValueError("矩阵导出需要完整的 group 分组，请先补齐样本关联和分组。")
        labels = data.obs[group_key]
    labels = pd.Series(list(labels), index=data.obs_names)
    if labels.isna().any() or labels.astype(str).str.strip().eq("").any():
        raise ValueError("矩阵导出不允许空 group 分组或标签。")
    labels = labels.astype(str)
    block = data if features is None else data[:, features]
    if not block.obs_names.is_unique or not block.var_names.is_unique:
        raise ValueError("细胞和特征标识必须唯一。")
    if any(str(name) in {"Sample", "Label"} for name in block.var_names):
        raise ValueError("特征标识不能与 Sample 或 Label 表头重名。")
    frame = block.to_df()
    frame.insert(0, "Label", labels.to_numpy())
    frame.index = pd.Index(block.obs_names, name="Sample")
    return frame.to_csv().encode("utf-8")


def export_matrix(project, source):
    """Select the complete measured root or the active processed matrix."""
    if source == "current":
        return project.workspace.require_data()
    if source != "extracted":
        raise ValueError("未知矩阵来源。")
    state = project.ion_state
    if state is not None:
        branch = state["branches"][state["active_branch_id"]]
        view = state["views"][branch["view_id"]]
        root = state["roots"].get(view["root_id"])
        data = None if root is None else root["data"]
    else:
        data = project.workspace._original
    if data is None or "project_batch" not in data.uns:
        raise ValueError("没有可用的审核后提取原始矩阵，请先完成提取审核并建立当前数据集。")
    return data


def export_samples(project, data):
    """Resolve labels by stable sample identity without changing scientific metadata."""
    if "sample" not in data.obs or data.obs["sample"].isna().any():
        raise ValueError("缺少样本名，请先完成样本关联。")
    names = {s["id"]: s["name"] for s in project.samples}
    keys = data.obs["sample_id"] if "sample_id" in data.obs else data.obs["sample"]
    if keys.isna().any() or keys.astype(str).str.strip().eq("").any():
        raise ValueError("缺少样本关联，请先完成样本关联。")
    keys = keys.astype(str)
    samples = []
    for key in keys.unique():
        selected = keys.eq(key)
        values = data.obs.loc[selected, "sample"].astype(str).unique()
        if len(values) != 1 or not values[0].strip():
            raise ValueError("样本关联有歧义，请先完成样本关联。")
        name = names.get(key, values[0])
        samples.append({"id": key, "name": name, "label": name, "cells": int(selected.sum())})
    return keys, samples


def labeled_matrix(project, data, overrides):
    keys, samples = export_samples(project, data)
    labels = {s["id"]: s["label"] for s in samples}
    if set(overrides) - labels.keys():
        raise ValueError("标签包含当前矩阵以外的样本。")
    if any(not value.strip() for value in overrides.values()):
        raise ValueError("CSV 标签不能为空。")
    labels.update(overrides)
    return matrix_csv(data, labels=keys.map(labels))
