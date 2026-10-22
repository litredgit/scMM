"""Named adapters and read-only displays for the existing window trend algorithm."""
# ruff: noqa: RUF001

import numpy as np
import pandas as pd
from anndata import AnnData

from scMM.util.time_results import binding, registry

from .time_analysis import (
    _dependency_fields,
    _new_key,
    _publish,
    _validated_time,
    check_size,
    expanded_inputs,
)


def trends(
    data,
    *,
    key,
    time_key,
    time_kind,
    unit,
    features=None,
    feature_name_key=None,
    layer=None,
    window_size=100,
    step_size=50,
    kernel_stat="median",
):
    from scMM.plot._trajectory import _window_starts, metabolite_trends

    check_size(data)
    _new_key(data, key, [key, f"{key}_params"])
    time = _validated_time(data, time_key, time_kind, unit)
    axis = data.var_names.astype(str)
    selected = list(features) if features else axis.tolist()
    if (
        not selected
        or len(set(selected)) != len(selected)
        or any(name not in axis for name in selected)
    ):
        raise ValueError("趋势特征须为当前唯一稳定 ID，不能重复或使用最近质量替代")
    positions = axis.get_indexer(selected)
    starts = _window_starts(data.n_obs, window_size, step_size)
    expected = len(starts) * (2 * len(selected) + 3) + data.n_obs + 7 * len(selected) + 10
    existing = sum(
        sum(np.asarray(item).size for item in data.uns[name].values())
        for name, run in registry(data)["runs"].items()
        if run["kind"] in {"velocity", "trends", "trend_clusters"} and not run.get("stale")
    )
    if expected + existing > 5_000_000:
        raise ValueError("趋势窗口结果超过同步工程上限 500 万数值")
    source = data.layers[layer] if layer is not None else data.X
    source = source[:, positions]
    matrix = np.asarray(source.toarray() if hasattr(source, "toarray") else source, dtype=float)
    if np.isinf(matrix).any():
        raise ValueError("趋势强度不可含无穷值；NaN 沿原算法按窗口忽略，不修改源矩阵")
    inputs = [
        binding(data, "layers", layer) if layer is not None else binding(data, "X", "X"),
        binding(data, "obs", time_key),
    ]
    names = selected.copy()
    if feature_name_key is not None:
        if feature_name_key not in data.var:
            raise ValueError("所选特征名称列不存在，不静默切换名称来源")
        inputs.append(binding(data, "var", feature_name_key))
        labels = data.var.iloc[positions][feature_name_key].astype("string")
        names = [
            str(value) if pd.notna(value) and str(value).strip() else feature
            for value, feature in zip(labels, selected, strict=True)
        ]
    inputs = expanded_inputs(data, inputs)
    _dependency_fields(data, inputs)
    work = AnnData(
        matrix.copy(),
        obs=pd.DataFrame({time_key: time}, index=data.obs_names.copy()),
        var=pd.DataFrame({"display_name": names}, index=selected),
    )
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            metabolite_trends(
                work,
                parameterization_key=time_key,
                window_size=window_size,
                step_size=step_size,
                kernel_stat=kernel_stat,
                feature_name_key="display_name",
            )
    except FloatingPointError as exc:
        raise ValueError("趋势统计数值溢出，未应用结果；请检查强度和时间尺度") from exc
    values = work.uns["metabolite_trends"]
    if np.isinf(values["pooled"]).any():
        raise ValueError("趋势统计产生无穷值，未应用结果")
    ordered = matrix[np.asarray(values["sorted_obs_order"])]
    width = min(window_size, data.n_obs)
    values["finite_counts"] = np.asarray(
        [np.isfinite(ordered[start : start + width]).sum(axis=0) for start in starts], dtype=int
    )
    values["window_starts"] = np.asarray(starts, dtype=int)
    parameters = {
        "time_key": time_key,
        "time_kind": time_kind,
        "unit": unit,
        "layer": layer,
        "input_representation": "X" if layer is None else f"layers:{layer}",
        "feature_ids": selected,
        "feature_axis": axis.tolist(),
        "feature_name_key": feature_name_key,
        "kernel_stat": kernel_stat,
        "requested_window_size": window_size,
        "window_size": width,
        "step_size": step_size,
        "seed": None,
        "direction": "increasing_time",
        "missing_values": "existing_nan_reducers; all-NaN sum=0; mean/median=NaN",
        "significance": "existing_window_spearman_and_BH_over_selected_features",
    }
    data.uns[key] = values
    data.uns[f"{key}_params"] = parameters.copy()
    return _publish(
        data,
        key,
        "trends",
        parameters,
        inputs,
        [binding(data, "uns", name) for name in (key, f"{key}_params")],
    )


def trend_tables(data, key, run):
    values = data.uns[key]
    ids = run["parameters"]["feature_ids"]
    pooled = np.asarray(values["pooled"])
    windows = pd.DataFrame(
        {
            "window_index": np.arange(pooled.shape[0]),
            "window_start": values["window_starts"],
            "time_center": values["time_centers"],
            "cells": values["counts"],
        }
    )
    statistics = pd.DataFrame(
        {
            "feature_id": ids,
            "feature_name": values["feature_names"],
            "rho": values["rho"],
            "p_value": values["pval"],
            "q_value": values["qval"],
            "rank": np.argsort(values["rank_idx"]) + 1,
        }
    )
    table = pd.DataFrame(
        {
            "window_index": np.repeat(windows.window_index.to_numpy(), len(ids)),
            "feature_id": np.tile(ids, len(windows)),
            "pooled": pooled.ravel(),
            "finite_cells": np.asarray(values["finite_counts"]).ravel(),
        }
    )
    cells = pd.DataFrame(
        {
            "cell_id": data.obs_names.astype(str),
            "time": data.obs[run["parameters"]["time_key"]].to_numpy(),
            "sorted_position": np.argsort(values["sorted_obs_order"]),
        }
    )
    return {"windows": windows, "statistics": statistics, "trends": table, "cells": cells}


def trend_figure(data, key, run, plot_top_n, display_standardize):
    import plotly.graph_objects as go

    values = data.uns[key]
    order = np.asarray(values["rank_idx"], dtype=int)[:plot_top_n]
    if len(order) * len(values["counts"]) > 200_000:
        raise ValueError("趋势热图超过 20 万显示值，请减少显示特征数；完整结果仍可下载")
    display = np.asarray(values["pooled"])[:, order].T.copy()
    if display_standardize:
        for row in display:
            finite = np.isfinite(row)
            if not finite.any():
                continue
            # Scale before centering to avoid an avoidable visualization overflow.
            scale = np.max(np.abs(row[finite]))
            scaled = row[finite] / scale if scale else row[finite].copy()
            deviation = scaled.std()
            row[finite] = (scaled - scaled.mean()) / deviation if deviation else 0
    ids = np.asarray(run["parameters"]["feature_ids"])[order]
    names = np.asarray(values["feature_names"])[order]
    labels = [
        str(name) if name == feature else f"{name} · {feature}"
        for name, feature in zip(names, ids, strict=True)
    ]
    custom = np.empty((*display.shape, 3), dtype=object)
    custom[:, :, 0] = np.asarray(values["time_centers"])[None, :]
    custom[:, :, 1] = np.asarray(values["finite_counts"])[:, order].T
    custom[:, :, 2] = names[:, None]
    figure = go.Figure(
        go.Heatmap(
            z=display,
            x=np.arange(display.shape[1]),
            y=ids.tolist(),
            customdata=custom,
            colorscale="Viridis",
            hoverongaps=False,
            colorbar={"title": "行标准分" if display_standardize else "窗口强度"},
            hovertemplate="%{customdata[2]} · %{y}<br>窗口 %{x}<br>时间 %{customdata[0]}<br>有限细胞 %{customdata[1]}<br>显示值 %{z}<extra></extra>",
        )
    )
    figure.update_layout(
        title=f"代谢趋势 · {key}",
        xaxis_title="窗口（时间递增排序）",
        yaxis={"title": "特征", "tickmode": "array", "tickvals": ids.tolist(), "ticktext": labels},
        meta={
            "trend_display_standardize": display_standardize,
            "trend_display_feature_ids": ids.tolist(),
            "trend_plot_top_n": plot_top_n,
        },
    )
    notes = [
        f"显示前 {len(order)} 个已计算排名特征；全部 {len(values['rank_idx'])} 个特征的原始窗口统计和检验量在完整表中。",
        "行标准分仅用于显示，使用各特征窗口的有限值及总体标准差；常量行显示为零，源矩阵和趋势值不变。"
        if display_standardize
        else "显示未标准化的窗口强度统计值，源矩阵不变。",
        "NaN 按原窗口统计忽略；全空窗口/特征的均值、中位数为未定义，总和沿原算法为 0，须结合有限细胞数解释。",
        "Spearman/BH 沿既有窗口算法；重叠窗口不独立，细胞数不是生物重复，p/q 仅作探索排序，不证明时间因果或代谢通量。",
        f"时间含义：{run['parameters']['time_kind']}；单位：{run['parameters']['unit']}。伪时间及归一化进程不是物理时间。",
    ]
    return figure, notes
