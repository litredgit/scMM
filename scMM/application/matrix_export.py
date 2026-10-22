"""Cell rows and a single class column for MetaboAnalyst matrix downloads."""
# ruff: noqa: RUF001

import pandas as pd


def matrix_csv(data, *, features=None, group_key="group"):
    if group_key not in data.obs or data.obs[group_key].isna().any():
        raise ValueError("矩阵导出需要完整的 group 分组，请先补齐样本关联和分组。")
    labels = data.obs[group_key].astype(str)
    if labels.str.strip().eq("").any():
        raise ValueError("矩阵导出不允许空分组，请先补齐 group。")
    block = data if features is None else data[:, features]
    if not block.obs_names.is_unique or not block.var_names.is_unique:
        raise ValueError("细胞和特征标识必须唯一。")
    if any(str(name) in {"Sample", "Label"} for name in block.var_names):
        raise ValueError("特征标识不能与 Sample 或 Label 表头重名。")
    frame = block.to_df()
    frame.insert(0, "Label", labels.to_numpy())
    frame.index = pd.Index(block.obs_names, name="Sample")
    return frame.to_csv().encode("utf-8")
