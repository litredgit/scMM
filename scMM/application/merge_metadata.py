"""Lossless typed annotations and explicit sample names for processed merges."""
# ruff: noqa: RUF001

import numpy as np
import pandas as pd


def values64(value, *, finite=False):
    original = value.toarray() if hasattr(value, "toarray") else np.asarray(value)
    if original.dtype.kind not in "biuf":
        raise ValueError("合并只支持实数数值矩阵")
    result = np.asarray(original, dtype=np.float64)
    if np.isinf(result).any() or (finite and not np.isfinite(result).all()):
        raise ValueError("合并的 X 必须有限；层/raw 保留 NaN，但不接受无穷值")
    if original.dtype.kind in "iu" or original.dtype.itemsize > 8:
        valid = ~np.isnan(result)
        if not np.equal(original[valid].astype(object), result[valid].astype(object)).all():
            raise ValueError("输入不能无损表示为 float64，未降低精度或应用合并")
    return result


def annotation(parts, index):
    """Combine disjoint row assignments without int64-to-float missing-value loss."""
    available = [series for series in parts if len(series)]
    if not available:
        return pd.Series(np.nan, index=index)
    if all(isinstance(part.dtype, pd.CategoricalDtype) for part in available):
        if all(part.dtype == available[0].dtype for part in available):
            return pd.concat(available).reindex(index)
        if any(part.cat.ordered for part in available):
            raise ValueError("有序类别定义不兼容，请保留分来源字段，不静默改变顺序")
    elif any(
        isinstance(part.dtype, pd.CategoricalDtype) and part.cat.ordered for part in available
    ):
        raise ValueError("有序类别与其他类型不兼容，请取消共同字段")
    series = pd.concat([part.astype(object) for part in available]).reindex(index)
    observed = series.dropna().tolist()
    if not observed:
        return pd.Series(np.nan, index=index)
    if all(isinstance(v, str) for v in observed) or all(isinstance(v, bytes) for v in observed):
        return pd.Series(pd.Categorical(series), index=index)
    if all(isinstance(v, (bool, np.bool_)) for v in observed):
        return series.astype("boolean")
    if all(
        isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_)) for v in observed
    ):
        dtype = (
            "UInt64" if max(observed) > np.iinfo(np.int64).max and min(observed) >= 0 else "Int64"
        )
        return series.astype(dtype)
    if all(
        isinstance(v, (int, float, np.number)) and not isinstance(v, (bool, np.bool_))
        for v in observed
    ):
        values64(np.asarray(observed))
        for value in observed:
            if isinstance(value, (int, np.integer)) and int(float(value)) != int(value):
                raise ValueError(
                    "共同元数据整数不能无损转为浮点；请取消该共同字段，分来源字段继续保留"
                )
        return series.astype(float)
    raise ValueError("元数据类型不兼容；请取消共同字段或离线整理原字段，不能静默改类型")


def sample_values(data, key):
    if key is None:
        return pd.Series([None] * data.n_obs, index=data.obs_names, dtype=object)
    if key not in data.obs:
        raise ValueError(f"样本来源列不存在：{key}")
    result = pd.Series(
        [None if pd.isna(v) else str(v) for v in data.obs[key]], index=data.obs_names, dtype=object
    )
    raw = data.obs[key].dropna()
    for value in result.dropna().unique():
        types = {type(item).__name__ for item in raw[raw.astype(str) == value]}
        if len(types) > 1:
            raise ValueError("样本来源列存在不同类型的同名值，请明确整理或选择稳定样本 ID 列")
    return result


def mapping_rows(inputs):
    rows = []
    for source in inputs:
        key = source["spec"]["sample_key"]
        current = sample_values(source["data"], key)
        baseline = sample_values(source["baseline"], key)
        names = list(dict.fromkeys([*current.tolist(), *baseline.tolist()]))
        for name in names:
            rows.append(
                {
                    "input_id": source["id"],
                    "source_sample": name,
                    "cells": int(current.isna().sum() if name is None else current.eq(name).sum()),
                    "baseline_cells": int(
                        baseline.isna().sum() if name is None else baseline.eq(name).sum()
                    ),
                }
            )
    return rows
