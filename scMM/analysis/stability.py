"""Acquisition-coordinate QC, retaining exact cell/source identities and empty bins."""

# ruff: noqa: RUF001
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .preprocessing import integer

KINDS = {
    "acquisition_seconds": "采集坐标（秒）",
    "normalized_time": "归一化时间（无量纲）",
    "pseudotime": "伪时间（算法尺度）",
    "stored_order": "当前存储顺序（非采集时间）",
}


def stability_tables(data, *, source_key, feature, time_kind, time_key=None, bins=10, layer=None):
    if source_key not in data.obs or feature not in data.var_names:
        raise ValueError("select an existing source column and exact feature ID")
    if time_kind not in KINDS:
        raise ValueError("select the coordinate meaning explicitly")
    if time_kind != "stored_order" and time_key not in data.obs:
        raise ValueError("select an existing numeric time column")
    if time_kind == "stored_order" and time_key is not None:
        raise ValueError("stored_order does not accept a time column")
    bins = integer("bins", bins, 2, 100)
    if layer is not None and layer not in data.layers:
        raise ValueError("selected intensity layer is missing")
    if data.n_obs * data.n_vars > 2_000_000:
        raise ValueError(
            "stability QC supports at most 2000000 matrix values; select an explicit subset first"
        )
    matrix = data.X if layer is None else data.layers[layer]
    values = np.asarray(matrix.toarray() if hasattr(matrix, "toarray") else matrix, dtype=float)
    time = (
        np.arange(data.n_obs, dtype=float)
        if time_kind == "stored_order"
        else pd.to_numeric(data.obs[time_key], errors="coerce").to_numpy(
            dtype=float, na_value=np.nan
        )
    )
    included = np.isfinite(time)
    if included.sum() < 2 or time[included].max() == time[included].min():
        raise ValueError("QC requires at least two finite, distinct time coordinates")
    if time_kind == "normalized_time" and np.any((time[included] < 0) | (time[included] > 1)):
        raise ValueError("normalized_time coordinates must be within [0, 1]")
    source = data.obs[source_key].astype("string")
    source = source.mask(source.str.strip().eq(""))
    missing = "(Missing source)"
    existing = set(source.dropna())
    while missing in existing:
        missing += "·"
    source = source.fillna(missing).to_numpy()
    sources = list(pd.unique(source))
    if len(sources) > 100:
        raise ValueError("stability QC supports at most 100 sources")
    try:
        with np.errstate(over="raise", invalid="raise"):
            edges = np.linspace(time[included].min(), time[included].max(), bins + 1)
    except FloatingPointError as exc:
        raise ValueError("time coordinate scale cannot be binned safely") from exc
    if not np.isfinite(edges).all() or np.any(np.diff(edges) <= 0):
        raise ValueError(
            "coordinate range cannot represent the requested bins; reduce bins or rescale coordinates"
        )
    labels = np.zeros(data.n_obs, dtype=int)
    labels[included] = (
        np.clip(np.searchsorted(edges, time[included], side="right") - 1, 0, bins - 1) + 1
    )
    finite_values = np.where(np.isfinite(values), values, np.nan)
    try:
        with np.errstate(over="raise", invalid="raise"):
            totals = np.where(
                np.isfinite(values).all(axis=1),
                np.sum(np.where(np.isfinite(values), values, 0), axis=1),
                np.nan,
            )
    except FloatingPointError as exc:
        raise ValueError("intensity scale cannot be summarized safely") from exc
    frame = pd.DataFrame(
        {
            "cell_id": data.obs_names.astype(str),
            "source": source,
            "coordinate": time,
            "included": included,
            "time_bin": labels,
            "reference_intensity": values[:, data.var_names.get_loc(feature)],
            "total_intensity": totals,
        }
    )
    rows, medians = [], []
    for sample in sources:
        selected = (source == sample) & included
        profile = (
            pd.DataFrame(finite_values[selected], columns=data.var_names).median(axis=0)
            if selected.any()
            else pd.Series(np.nan, index=data.var_names)
        )
        medians.append(profile.to_numpy())
        for index in range(1, bins + 1):
            group = frame.loc[selected & (labels == index)]
            rows.append(
                {
                    "source": sample,
                    "time_bin": index,
                    "left": edges[index - 1],
                    "right": edges[index],
                    "cell_count": len(group),
                    "finite_reference_count": int(np.isfinite(group.reference_intensity).sum()),
                    "median_reference": group.reference_intensity.where(
                        np.isfinite(group.reference_intensity)
                    ).median()
                    if np.isfinite(group.reference_intensity).any()
                    else np.nan,
                    "median_total": group.total_intensity.median()
                    if group.total_intensity.notna().any()
                    else np.nan,
                }
            )
    profiles = pd.DataFrame(medians, index=sources, columns=data.var_names)
    profiles.index.name = "source"
    correlation = profiles.T.corr(method="pearson", min_periods=2)
    summary = pd.DataFrame(rows)
    dependencies = [source_key] + ([] if time_kind == "stored_order" else [time_key])
    notes = [
        f"坐标含义：{KINDS[time_kind]}；来源按首次出现顺序保留，时间只用于分箱，不按显示行号修改数据。",
        "参考特征按稳定 ID 精确选择，不按最近 m/z 匹配；零值参与统计，缺失/非有限值保留在完整表。",
        "相关热图为每来源全特征中位强度谱的 Pearson 相关；常量或少于两个可比较特征显示未定义，不置零。",
        "这些细胞级采集稳定性描述不等于生物重复验证，不证明批次不存在或信号已鉴定。",
        f"{int((~included).sum())} 个非有限坐标细胞不参与分箱/来源谱；空窗口保留零计数，强度为缺失。",
    ]
    return {
        "cells": frame,
        "windows": summary,
        "profiles": profiles,
        "correlation": correlation,
        "notes": notes,
        "dependencies": dependencies,
    }


def stability_figure(data, **options):
    result = stability_tables(data, **options)
    figure = make_subplots(
        rows=3,
        cols=1,
        subplot_titles=(
            "Reference feature intensity distributions",
            "Cell counts per window",
            "Correlation of source median spectra",
        ),
        vertical_spacing=0.1,
    )
    frame, summary, corr = result["cells"], result["windows"], result["correlation"]
    for source in frame.source.unique():
        cells = frame.loc[(frame.source == source) & frame.included]
        figure.add_trace(
            go.Box(
                x=cells.time_bin,
                y=cells.reference_intensity.where(np.isfinite(cells.reference_intensity)),
                name=str(source),
                boxpoints=False,
                legendgroup=str(source),
            ),
            row=1,
            col=1,
        )
        windows = summary.loc[summary.source == source]
        figure.add_trace(
            go.Bar(
                x=windows.time_bin,
                y=windows.cell_count,
                name=str(source),
                legendgroup=str(source),
                showlegend=False,
            ),
            row=2,
            col=1,
        )
    figure.add_trace(
        go.Heatmap(
            x=list(corr.columns),
            y=list(corr.index),
            z=corr.to_numpy(),
            zmin=-1,
            zmax=1,
            colorscale="RdBu",
            colorbar={"len": 0.25, "y": 0.12},
        ),
        row=3,
        col=1,
    )
    figure.update_xaxes(title_text="Window index", row=1, col=1)
    figure.update_xaxes(title_text="Window index", row=2, col=1)
    figure.update_yaxes(title_text="Reference intensity", row=1, col=1)
    figure.update_yaxes(title_text="Cell count", row=2, col=1)
    figure.update_xaxes(title_text="Source", row=3, col=1)
    figure.update_yaxes(title_text="Source", row=3, col=1)
    figure.update_layout(
        height=1000,
        title="Acquisition stability QC",
        boxmode="group",
        barmode="group",
        meta={
            "notes": result["notes"],
            "observation_dependencies": result["dependencies"],
            "export_tables": {
                name + ".csv": result[name].to_csv(index=name in {"profiles", "correlation"})
                for name in ("cells", "windows", "profiles", "correlation")
            },
        },
    )
    return figure
