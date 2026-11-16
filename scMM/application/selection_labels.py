# ruff: noqa: RUF001
"""Reversible selection pools, independent of the immutable preprocessing origin."""

import json
import re
from copy import deepcopy

import numpy as np
import pandas as pd
from matplotlib.path import Path
from sklearn.ensemble import IsolationForest

from scMM.analysis.exploration import matrix, vector


def source(state):
    return state._selection_source if state._selection_source is not None else state.require_data()


def update(
    state,
    *,
    name,
    axis="cell",
    mode="ids",
    ids=None,
    threshold=0.1,
    source_file=None,
    x=None,
    y=None,
    polygon=None,
    invert=False,
    enabled=True,
    contamination=0.05,
    seed=42,
):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
        raise ValueError("标签名须以英文字母开头，仅含字母、数字和下划线，最长 64 字符。")
    if state._selection_source is None and state.require_data().uns.get(
        "scmm_selection_pool_required", False
    ):
        raise ValueError("此独立矩阵不含完整标签恢复池；请打开完整目录项目恢复筛选。")
    data = source(state).copy()
    registry = json.loads(data.uns.get("scmm_selection_json", "{}"))
    key = f"{axis}_keep_{name}"
    if mode == "toggle":
        if key not in registry:
            raise ValueError("标签不存在。")
    else:
        table = data.obs if axis == "cell" else data.var
        if mode == "ids":
            ids = ids or []
            if set(ids) - set(table.index):
                raise ValueError("标签含未知稳定编号。")
            keep = table.index.isin(ids)
        elif mode == "detection" and axis == "feature":
            cells = np.ones(data.n_obs, dtype=bool)
            if source_file:
                if "source_file" not in data.obs:
                    raise ValueError("缺少来源文件信息。")
                cells = data.obs.source_file.astype(str).eq(source_file).to_numpy()
            if not cells.any():
                raise ValueError("所选来源没有细胞。")
            keep = np.mean(matrix(data)[cells] > 0, axis=0) >= threshold
        elif mode == "outliers" and axis == "cell":
            keep = (
                IsolationForest(contamination=contamination, random_state=seed).fit_predict(
                    matrix(data)
                )
                == 1
            )
        elif mode == "polygon" and axis == "cell":
            if polygon is None or len(polygon) < 3 or not np.isfinite(polygon).all():
                raise ValueError("圈门至少需要三个有限二维顶点。")
            a, _ = vector(data, x)
            b, _ = vector(data, y)
            vertices = np.asarray(polygon, float)
            if vertices.ndim != 2 or vertices.shape[1] != 2:
                raise ValueError("圈门顶点须为二维坐标。")
            # Explicitly close without discarding the final user vertex.
            keep = Path(np.vstack([vertices, vertices[0]])).contains_points(
                np.c_[a, b], radius=1e-12
            )
            keep &= np.isfinite(a) & np.isfinite(b)
        else:
            raise ValueError("标签方法与轴不匹配。")
        if invert:
            keep = ~keep
        table[key] = keep.astype(np.uint8)
        registry[key] = {
            "axis": axis,
            "enabled": enabled,
            "mode": mode,
            "threshold": threshold,
            "source_file": source_file,
            "x": x,
            "y": y,
            "polygon": polygon,
            "invert": invert,
            "seed": seed,
            "contamination": contamination,
        }
    registry[key]["enabled"] = enabled
    data.uns["scmm_selection_json"] = json.dumps(registry, ensure_ascii=False)
    rows = np.ones(data.n_obs, dtype=bool)
    columns = np.ones(data.n_vars, dtype=bool)
    for label, record in registry.items():
        if record["enabled"]:
            if record["axis"] == "cell":
                rows &= data.obs[label].to_numpy() == 1
            else:
                columns &= data.var[label].to_numpy() == 1
    if not rows.any() or not columns.any():
        raise ValueError("标签组合会移除全部细胞或特征，未应用。")
    candidate = data[rows, columns].copy()
    candidate.uns["scmm_selection_pool_required"] = any(v["enabled"] for v in registry.values())
    state._commit(
        candidate,
        "selection_labels",
        {"name": name, "axis": axis, "enabled": enabled},
        save_layer=False,
    )
    state._selection_source = data if any(v["enabled"] for v in registry.values()) else None
    # Keep disabled tags after restoring the full matrix.
    return deepcopy(registry)


def validate_pool(state):
    pool = state._selection_source
    if pool is None:
        return
    state._validate(pool)
    data = state.require_data()
    if (
        not data.obs_names.isin(pool.obs_names).all()
        or not data.var_names.isin(pool.var_names).all()
    ):
        raise ValueError("筛选恢复矩阵与当前轴不一致。")
    registry = json.loads(pool.uns.get("scmm_selection_json", "{}"))
    if not registry or not any(record.get("enabled") for record in registry.values()):
        raise ValueError("筛选恢复矩阵缺少启用标签。")
    rows = np.ones(pool.n_obs, bool)
    columns = np.ones(pool.n_vars, bool)
    for key, record in registry.items():
        if record.get("axis") not in {"cell", "feature"}:
            raise ValueError("筛选标签轴无效。")
        table = pool.obs if record["axis"] == "cell" else pool.var
        if key not in table or not table[key].isin([0, 1]).all():
            raise ValueError("筛选标签值无效。")
        if record.get("enabled"):
            if record["axis"] == "cell":
                rows &= table[key].to_numpy() == 1
            else:
                columns &= table[key].to_numpy() == 1
    if list(pool.obs_names[rows]) != list(data.obs_names) or list(pool.var_names[columns]) != list(
        data.var_names
    ):
        raise ValueError("筛选标签与当前轴不一致。")
    if not np.array_equal(matrix(pool[rows, columns]), matrix(data)):
        raise ValueError("筛选恢复矩阵与当前数值不一致。")


def axis_choices(state, query=""):
    data = source(state)
    term = query.casefold().strip()
    options = [
        {"value": f"obs:{key}", "label": f"细胞指标 · {key}"}
        for key in data.obs
        if pd.api.types.is_numeric_dtype(data.obs[key])
    ]
    for key, values in data.obsm.items():
        if getattr(values, "ndim", 0) == 2:
            for component in range(values.shape[1]):
                options.append(
                    {
                        "value": f"embedding:{key}:{component}",
                        "label": f"降维坐标 · {key} 第 {component + 1} 维",
                    }
                )
    options = [
        row for row in options if term in row["label"].casefold() or term in row["value"].casefold()
    ]
    count = 0
    for key in data.var_names:
        if term and term not in str(key).casefold():
            continue
        options.append({"value": f"feature:{key}", "label": f"特征 · {key}"})
        count += 1
        if count >= 100:
            break
    return {"options": options}
