"""Read-only tables, metadata and plots for validated named time results."""

# ruff: noqa: RUF001
import json

import numpy as np
import pandas as pd

from scMM.util.time_results import binding, require_run

from .time_inputs import _dependency_fields, _numeric, expanded_inputs


def _velocity_tables(data, key, run):
    values = data.uns[key]
    windows = pd.DataFrame(
        {
            "window_index": np.arange(len(values["speeds"])),
            "window_start": values["window_starts"],
            "time_center": values["time_centers"],
            "valid_cells": values["counts"],
            "speed": values["speeds"],
        }
    )
    features = pd.DataFrame(
        {
            "window_index": np.repeat(windows.window_index.to_numpy(), data.n_vars),
            "feature_id": np.tile(data.var_names.astype(str), len(windows)),
            "state_center": np.asarray(values["state_centers"]).ravel(),
            "velocity": np.asarray(values["velocity_field"]).ravel(),
        }
    )
    cells = pd.DataFrame(
        {
            "cell_id": data.obs_names.astype(str),
            "time": data.obs[run["parameters"]["time_key"]].to_numpy(),
            "sorted_position": np.argsort(values["sorted_obs_order"]),
        }
    )
    return {"windows": windows, "features": features, "cells": cells}


def result_tables(data, key):
    run = require_run(data, key)
    if run["kind"] == "trend_clusters":
        from .time_trend_clusters import cluster_tables

        return cluster_tables(data, key, run)
    if run["kind"] == "trends":
        from .time_trends import trend_tables

        return trend_tables(data, key, run)
    if run["kind"] == "velocity":
        return _velocity_tables(data, key, run)
    if run["kind"] == "palantir":
        frame = pd.DataFrame(
            {
                "cell_id": data.obs_names.astype(str),
                "pseudotime": data.obs[f"{key}_pseudotime"].to_numpy(),
            }
        )
        if f"{key}_entropy" in data.obs:
            frame["entropy"] = data.obs[f"{key}_entropy"].to_numpy()
        probabilities = np.asarray(data.obsm[f"{key}_branch_probs"])
        for column in range(probabilities.shape[1]):
            frame[f"branch_{column}"] = probabilities[:, column]
        multiscale = pd.DataFrame(
            np.asarray(data.obsm[f"{key}_ms_data"]), index=data.obs_names.astype(str)
        )
        multiscale.index = multiscale.index.copy()
        multiscale.index.name = "cell_id"
        return {"cells": frame, "multiscale": multiscale.reset_index()}
    values = np.asarray(data.uns[key])
    meta = data.uns[f"{key}_metadata"]
    rows = []
    for branch in range(values.shape[0]):
        for window in range(values.shape[1]):
            row = {
                "branch_index": branch,
                "branch_name": run["parameters"]["branch_names"][branch],
                "window_index": window,
                "window_start": int(meta["window_starts"][window]),
                "time_center": meta["time"][branch, window],
                "valid_cells": meta["counts"][branch, window],
                "weight_sum": meta["weight_sum"][branch, window],
            }
            row.update({f"coordinate_{j}": value for j, value in enumerate(values[branch, window])})
            rows.append(row)
    cells = pd.DataFrame(
        {
            "cell_id": data.obs_names.astype(str),
            "time": data.obs[run["parameters"]["time_key"]].to_numpy(),
        }
    )
    coordinates = data.obsm[run["parameters"]["coordinate_key"]]
    coordinates = np.asarray(
        coordinates.toarray() if hasattr(coordinates, "toarray") else coordinates
    )
    for column in range(coordinates.shape[1]):
        cells[f"coordinate_{column}"] = coordinates[:, column]
    branch_key = run["parameters"]["branch_probability_key"]
    if branch_key:
        probabilities = data.obsm[branch_key]
        probabilities = (
            probabilities.toarray() if hasattr(probabilities, "toarray") else probabilities
        )
        for column, values in enumerate(np.asarray(probabilities).T):
            cells[f"branch_{column}"] = values
    cells["sorted_position"] = np.argsort(np.asarray(meta["sorted_obs_order"]))
    return {"windows": pd.DataFrame(rows), "cells": cells}


def result_metadata(data, key):
    from plotly.utils import PlotlyJSONEncoder

    from scMM.util.time_results import _plain

    run = require_run(data, key)
    metadata = {
        "key": key,
        **run,
        "output_metadata": {
            item["key"]: data.uns[item["key"]] for item in run["outputs"] if item["axis"] == "uns"
        },
    }
    # Undefined numeric outputs remain explicit nulls; CSV retains empty windows.
    return json.loads(json.dumps(_plain(metadata), cls=PlotlyJSONEncoder))


def time_figure(data, *, key, coordinate_key=None, plot_top_n=30, display_standardize=True):
    import plotly.graph_objects as go

    run = require_run(data, key)
    tables = result_tables(data, key)
    if run["kind"] == "palantir":
        if not coordinate_key:
            raise ValueError("请明确选择绘图坐标，计算输入与绘图坐标独立")
        coordinates = _numeric(data.obsm[coordinate_key], "绘图坐标")
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            raise ValueError("绘图坐标须至少二维")
        inputs = expanded_inputs(data, [binding(data, "obsm", coordinate_key)])
        cells = tables["cells"].copy()
        for column in range(coordinates.shape[1]):
            cells[f"plot_coordinate_{column}"] = coordinates[:, column]
        tables["cells"] = cells
        figure = go.Figure(
            go.Scatter(
                x=coordinates[:, 0],
                y=coordinates[:, 1],
                mode="markers",
                marker={
                    "color": cells["pseudotime"],
                    "colorscale": "Viridis",
                    "showscale": True,
                    "colorbar": {"title": "伪时间"},
                },
                customdata=np.column_stack([cells["cell_id"], cells["pseudotime"]]),
                hovertemplate="细胞 %{customdata[0]}<br>伪时间 %{customdata[1]}<extra></extra>",
                name="细胞",
            )
        )
        root = data.obs_names.get_loc(run["parameters"]["root_cell_id"])
        figure.add_trace(
            go.Scatter(
                x=[coordinates[root, 0]],
                y=[coordinates[root, 1]],
                mode="markers",
                marker={"symbol": "star", "size": 14, "color": "red"},
                name="所选根点",
                customdata=[[str(data.obs_names[root])]],
                hovertemplate="所选根点 %{customdata[0]}<extra></extra>",
            )
        )
        notes = [
            "伪时间是算法尺度，不是采集秒数或生物实验时间。起点须依据实验先验选择。",
            "分支概率与熵是模型输出，不代表已验证的细胞命运。",
        ]
        figure.update_layout(
            title=f"Palantir · {key}",
            xaxis_title=f"{coordinate_key} 1",
            yaxis_title=f"{coordinate_key} 2",
        )
    elif run["kind"] == "trend_clusters":
        from .time_trend_clusters import cluster_figure

        if coordinate_key is not None:
            raise ValueError("趋势聚类图使用时间窗口，不接受嵌入坐标")
        figure, notes = cluster_figure(data, key, run)
        inputs = []
    elif run["kind"] == "trends":
        from .time_trends import trend_figure

        if coordinate_key is not None:
            raise ValueError("趋势热图使用时间窗口，不接受嵌入坐标")
        figure, notes = trend_figure(data, key, run, plot_top_n, display_standardize)
        inputs = []
    elif run["kind"] == "velocity":
        if coordinate_key is not None:
            raise ValueError("速度图使用参数化时间，不接受嵌入坐标")
        inputs = []
        windows = tables["windows"]
        figure = go.Figure(
            go.Scatter(
                x=windows["time_center"],
                y=windows["speed"],
                mode="lines+markers",
                connectgaps=False,
                name="速度范数",
                customdata=windows[["window_index", "valid_cells"]].to_numpy(),
                hovertemplate="窗口 %{customdata[0]}<br>有效细胞 %{customdata[1]}<br>速度 %{y}<extra></extra>",
            )
        )
        notes = [
            "各特征强度对递增时间的局部回归斜率组成向量，图为其欧氏范数；符号方向见完整特征表。",
            "不是同位素示踪代谢通量；输入层、强度尺度和时间单位影响数值，不可跨尺度直接比较。",
            "相同时间或不足两个细胞的窗口无有效回归，保留为空；窗口和步长单位为细胞数。",
            f"时间含义：{run['parameters']['time_kind']}；单位：{run['parameters']['unit']}。伪时间和归一化时间不是物理时间。",
        ]
        figure.update_layout(
            title=f"窗口代谢速度 · {key}",
            xaxis_title=f"时间 ({run['parameters']['unit']})",
            yaxis_title=run["parameters"]["velocity_unit"],
        )
    else:
        if coordinate_key is not None and coordinate_key != run["parameters"]["coordinate_key"]:
            raise ValueError("窗口轨迹使用计算时的坐标；改变坐标须另算新结果")
        inputs = []
        windows = tables["windows"]
        figure = go.Figure()
        for branch in windows["branch_index"].unique():
            frame = windows[windows["branch_index"] == branch]
            figure.add_trace(
                go.Scatter(
                    x=frame["coordinate_0"],
                    y=frame["coordinate_1"],
                    mode="lines+markers",
                    connectgaps=False,
                    name=str(frame["branch_name"].iloc[0]),
                    customdata=frame[
                        ["window_index", "time_center", "valid_cells", "weight_sum"]
                    ].to_numpy(),
                    hovertemplate="窗口 %{customdata[0]}<br>时间中心 %{customdata[1]}<br>有效细胞 %{customdata[2]}<br>权重和 %{customdata[3]}<extra></extra>",
                )
            )
        valid = int(np.isfinite(windows["coordinate_0"]).sum())
        notes = [
            f"{valid}/{len(windows)} 个分支窗口有效；无效窗口保留为空，不跨空窗口连线。",
            f"时间含义：{run['parameters']['time_kind']}；单位：{run['parameters']['unit']}。窗口和步长单位是细胞数。",
            "轨迹为排序窗口的加权坐标中心，不是细胞命运或流形分支推断；坐标分离不证明独立生物分支。",
        ]
        figure.update_layout(
            title=f"滑动窗口轨迹 · {key}",
            xaxis_title=f"{run['parameters']['coordinate_key']} 1",
            yaxis_title=f"{run['parameters']['coordinate_key']} 2",
        )
    figure.update_layout(
        meta={
            **(figure.layout.meta or {}),
            "time_result_key": key,
            "time_result_identity": run["identity"],
            "time_plot_inputs": inputs,
            "observation_dependencies": sorted(
                set(run["observation_dependencies"]) | set(_dependency_fields(data, inputs))
            ),
            "point_kind": "cell" if run["kind"] == "palantir" else "window",
            "notes": notes,
            "time_parameters": run["parameters"],
            "export_tables": {name: frame.to_csv(index=False) for name, frame in tables.items()},
        }
    )
    return figure
