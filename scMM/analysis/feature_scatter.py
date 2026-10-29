"""Two exact feature IDs, explicit intensity layer and complete per-cell export."""
# ruff: noqa: RUF001

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.stats import linregress

from scMM.plot.presentation import PLOT_COLORS, feature_label


def feature_scatter_figure(
    data, *, feature_a, feature_b, layer=None, color_key=None, regression=True
):
    if feature_a not in data.var_names or feature_b not in data.var_names:
        raise ValueError("请选择当前矩阵中的稳定特征 ID，不按最近 m/z 自动匹配。")
    if feature_a == feature_b:
        raise ValueError("请选择两个不同的特征 ID。")
    if color_key is not None and color_key not in data.obs:
        raise ValueError("着色列不存在，请重新选择。")
    if layer is not None and layer not in data.layers:
        raise ValueError("强度层不存在，请重新选择。")
    block = data[:, [feature_a, feature_b]]
    values = block.X if layer is None else block.layers[layer]
    values = values.toarray() if hasattr(values, "toarray") else np.asarray(values)
    values = np.asarray(values, dtype=float)
    included = np.isfinite(values).all(axis=1)
    if not included.any():
        raise ValueError("两个特征没有共同有限值，无法绘图。")
    frame = pd.DataFrame(
        {
            "cell_id": data.obs_names.astype(str),
            "x_value": values[:, 0],
            "y_value": values[:, 1],
            "included": included,
        }
    )
    dependencies = []
    for key in ("sample_id", "sample", "source_file"):
        if key in data.obs:
            frame[key] = data.obs[key].to_numpy()
            dependencies.append(key)
    if color_key is not None:
        frame["color_value"] = data.obs[color_key].to_numpy()
        dependencies.append(color_key)
    displayed = frame.loc[included].copy()
    notes = [
        "两轴按稳定特征 ID 精确选择；零值保留，未检出及处理含义取决于所选强度层。",
        "回归为全部有限细胞的 y 对 x 普通最小二乘描述，不按着色分组分别拟合；细胞数不等于生物重复，不作因果解释。",
    ]
    if not included.all():
        notes.append(
            f"排除 {int((~included).sum())} 个非有限数值细胞的绘图/回归，完整 CSV 仍保留这些行及 included 标记。"
        )
    if color_key is None:
        figure = px.scatter(
            displayed,
            color_discrete_sequence=PLOT_COLORS,
            x="x_value",
            y="y_value",
            custom_data=["cell_id"],
        )
    elif pd.api.types.is_numeric_dtype(data.obs[color_key]) and not pd.api.types.is_bool_dtype(
        data.obs[color_key]
    ):
        colors = pd.to_numeric(displayed["color_value"], errors="coerce").to_numpy(
            dtype=float, na_value=np.nan
        )
        valid_color = np.isfinite(colors)
        displayed["color_value"] = colors
        figure = px.scatter(
            displayed.loc[valid_color],
            color_discrete_sequence=PLOT_COLORS,
            x="x_value",
            y="y_value",
            color="color_value",
            custom_data=["cell_id"],
            labels={"color_value": color_key},
        )
        if not valid_color.all():
            missing = displayed.loc[~valid_color]
            figure.add_trace(
                go.Scattergl(
                    x=missing.x_value,
                    y=missing.y_value,
                    mode="markers",
                    marker_color="#9ca3af",
                    name="Missing/non-finite color",
                    customdata=missing[["cell_id"]].to_numpy(),
                )
            )
            notes.append("缺失/非有限着色值显示为灰色，不排除其有限两轴数值。")
    else:
        missing_label = "(Missing color)"
        existing = set(displayed["color_value"].dropna().astype(str))
        while missing_label in existing:
            missing_label += "·"
        missing = displayed["color_value"].isna()
        displayed["color_value"] = displayed["color_value"].astype(str)
        displayed.loc[missing, "color_value"] = missing_label
        figure = px.scatter(
            displayed,
            color_discrete_sequence=PLOT_COLORS,
            x="x_value",
            y="y_value",
            color="color_value",
            custom_data=["cell_id"],
            labels={"color_value": color_key},
        )
        if missing.any():
            notes.append("缺失着色单独显示，不排除其有限两轴数值。")
    figure.update_traces(
        hovertemplate="Cell: %{customdata[0]}<br>x: %{x:.2e}<br>y: %{y:.2e}<extra>%{fullData.name}</extra>"
    )
    fit = {
        "method": "OLS y_on_x",
        "requested": bool(regression),
        "n_cells": int(included.sum()),
        "status": "disabled",
        "slope": None,
        "intercept": None,
        "r_squared": None,
        "p_value": None,
        "stderr": None,
    }
    x, y = values[included, 0], values[included, 1]
    if regression:
        if len(x) < 2 or np.all(x == x[0]):
            fit["status"] = "insufficient_or_constant_x"
            notes.append("有限细胞少于 2 个或 x 为常量，未拟合回归线。")
        else:
            try:
                if np.all(y == y[0]):
                    fit.update(status="constant_y", slope=0.0, intercept=float(y[0]))
                    notes.append("y 为常量，仅绘制常量拟合线；R²、p 值及标准误不报告。")
                else:
                    with np.errstate(over="raise", invalid="raise", divide="raise"):
                        result = linregress(x, y)
                    if not np.isfinite([result.slope, result.intercept]).all():
                        raise FloatingPointError("non-finite fit")
                    fit.update(
                        status="fitted",
                        slope=float(result.slope),
                        intercept=float(result.intercept),
                    )
                    for key, value in (
                        ("r_squared", result.rvalue**2),
                        ("p_value", result.pvalue),
                        ("stderr", result.stderr),
                    ):
                        fit[key] = float(value) if np.isfinite(value) else None
                xx = np.array([x.min(), x.max()])
                with np.errstate(over="raise", invalid="raise"):
                    yy = fit["intercept"] + fit["slope"] * xx
                if not np.isfinite(yy).all():
                    raise FloatingPointError("non-finite regression line")
                figure.add_trace(
                    go.Scatter(
                        x=xx,
                        y=yy,
                        mode="lines",
                        line_color="#374151",
                        name="All-cell regression",
                        hoverinfo="skip",
                    )
                )
            except FloatingPointError:
                fit.update(
                    status="numerical_failure",
                    slope=None,
                    intercept=None,
                    r_squared=None,
                    p_value=None,
                    stderr=None,
                )
                notes.append("数值尺度无法稳定拟合，未绘制回归线；散点和完整源值保留。")
            if len(x) == 2:
                notes.append("仅有两个有限细胞，拟合及 p 值不支持稳定的统计推断。")

    def label(identity):
        mz = data.var.loc[identity].get("mz")
        return f"{feature_label(identity, mz)} · {identity}"

    figure.update_layout(
        title="Feature scatter",
        xaxis_title=label(feature_a),
        yaxis_title=label(feature_b),
        meta={
            "point_kind": "cell",
            "notes": notes,
            "regression": fit,
            "observation_dependencies": sorted(set(dependencies)),
            "export_tables": {
                "cells.csv": frame.to_csv(index=False),
                "regression.csv": pd.DataFrame([fit]).to_csv(index=False),
            },
        },
    )
    return figure
