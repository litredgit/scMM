"""Explicit adapters for existing Palantir and window-trajectory definitions."""
# ruff: noqa: RUF001

import json
import re
from importlib.metadata import version
from uuid import uuid4

import numpy as np
import pandas as pd
from anndata import AnnData
from threadpoolctl import threadpool_limits

from scMM.util.time_results import (
    binding,
    cell_identity,
    registry,
    require_run,
    valid_run,
    write_registry,
)


def check_size(data):
    if data.n_obs > 5000 or data.n_obs * data.n_vars > 5_000_000:
        raise ValueError("时间分析同步工程上限：5000 细胞、500 万矩阵值；更大输入等待后台任务接入")
    if not data.obs_names.astype(str).is_unique or not data.var_names.astype(str).is_unique:
        raise ValueError("时间分析需要唯一稳定细胞/特征 ID")


def _new_key(data, key, names):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", key) or key.startswith("scmm_"):
        raise ValueError("输出键须为字母开头、至多 48 位的字母/数字/下划线，不得使用 scmm_ 前缀")
    previous = registry(data)
    if len(previous["runs"]) >= 64:
        raise ValueError("本数据时间分析记录已达同步工程上限 64 项")
    if key in previous["runs"] or any(
        name in mapping for name in [key, *names] for mapping in (data.obs, data.obsm, data.uns)
    ):
        raise ValueError("输出键已存在或曾使用，请指定新键；不会覆盖旧结果")


def _numeric(values, name):
    if hasattr(values, "toarray"):
        values = values.toarray()
    try:
        result = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值") from exc
    if not np.isfinite(result).all():
        raise ValueError(f"{name} 含非有限值")
    return result


def _dependency_fields(data, inputs):
    fields = {item["key"] for item in inputs if item["axis"] == "obs"}
    rules = json.loads(data.uns.get("scmm_workbench", {}).get("latent_dependencies_json", "{}"))
    for item in inputs:
        if item["axis"] == "obsm":
            fields.update(rules.get(item["key"]) or [])
            for entry in reversed(
                json.loads(data.uns.get("scmm_workbench", {}).get("history_json", "[]"))
            ):
                if (
                    entry.get("operation") in {"latent", "reduce"}
                    and entry.get("parameters", {}).get("store_key") == item["key"]
                ):
                    if entry["operation"] == "latent":
                        fields.update(
                            entry["parameters"].get("observation_dependencies")
                            or list(data.obs.columns)
                        )
                    break
    for run in registry(data)["runs"].values():
        if any(
            (item["axis"], item["key"]) == (output["axis"], output["key"])
            for item in inputs
            for output in run["outputs"]
        ):
            if not valid_run(data, run):
                raise ValueError("输入依赖已过期的时间结果，请重新计算")
            fields.update(run["observation_dependencies"])
    return sorted(fields)


def expanded_inputs(data, inputs):
    selected = {(item["axis"], item["key"]): item for item in [binding(data, "X", "X"), *inputs]}
    pending = [item["key"] for item in inputs if item["axis"] == "obsm"]
    visited = set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        params = f"{key}_params"
        if params in data.uns:
            selected[("uns", params)] = binding(data, "uns", params)
            source = data.uns[params].get("source", "")
            if isinstance(source, str) and source.startswith("obsm:"):
                parent = source.removeprefix("obsm:")
                selected[("obsm", parent)] = binding(data, "obsm", parent)
                pending.append(parent)
    return list(selected.values())


def _publish(data, key, kind, parameters, inputs, outputs):
    value = registry(data)
    record = {
        "kind": kind,
        "identity": uuid4().hex,
        "parameters": parameters,
        "inputs": inputs,
        "outputs": outputs,
        "cell_identity": cell_identity(data),
        "observation_dependencies": _dependency_fields(data, inputs),
        "implementation": "scmm-time-v1",
        "stale": False,
    }
    value["runs"][key] = record
    total = sum(
        np.asarray(getattr(data, out["axis"])[out["key"]]).size
        for run in value["runs"].values()
        if not run.get("stale")
        for out in run["outputs"]
        if out["axis"] in {"obs", "obsm"}
    )
    total += sum(
        np.asarray(data.uns[name]).size
        + sum(np.asarray(item).size for item in data.uns[f"{name}_metadata"].values())
        for name, run in value["runs"].items()
        if run["kind"] == "trajectory" and not run.get("stale")
    )
    if total > 5_000_000:
        raise ValueError("时间结果数值超过同步工程上限 500 万，未应用候选")
    write_registry(data, value)
    metadata = data.uns.setdefault("scmm_workbench", {})
    metadata["derived_obs"] = list(
        dict.fromkeys(
            [
                *metadata.get("derived_obs", []),
                *(out["key"] for out in outputs if out["axis"] == "obs"),
            ]
        )
    )
    return record


def palantir(
    data,
    *,
    key,
    root_cell_id,
    input_representation,
    terminal_cell_ids=None,
    layer=None,
    n_diff_components=10,
    knn=30,
    num_waypoints=500,
    scale_components=True,
    max_iterations=25,
    seed=42,
    use_early_cell_as_start=True,
):
    from scMM.plot._trajectory import run_palantir

    check_size(data)
    fields = {
        "obs": [f"{key}_pseudotime", f"{key}_entropy"],
        "obsm": [f"{key}_branch_probs", f"{key}_ms_data"],
        "uns": [
            f"{key}_{suffix}"
            for suffix in (
                "branch_names",
                "ms_columns",
                "cell_index_map",
                "terminal_states_internal",
                "waypoints_internal",
                "params",
            )
        ],
    }
    _new_key(data, key, [name for names in fields.values() for name in names])
    ids = data.obs_names.astype(str)
    if root_cell_id not in ids or any(cell not in ids for cell in terminal_cell_ids or []):
        raise ValueError("根点或终末细胞不在当前稳定细胞 ID 中")
    if terminal_cell_ids is not None and (
        not terminal_cell_ids or len(set(terminal_cell_ids)) != len(terminal_cell_ids)
    ):
        raise ValueError("终末细胞 ID 必须非空且不重复，或留空由算法推断")
    if (
        not 3 <= knn < data.n_obs
        or not 2 <= n_diff_components <= 100
        or n_diff_components >= data.n_obs - 1
    ):
        raise ValueError("近邻须至少 3 且小于细胞数，扩散成分须至少 2 且小于细胞数减 1")
    if not max(3, n_diff_components) <= num_waypoints <= data.n_obs:
        raise ValueError("路标数量须不小于扩散成分数且不大于细胞数")
    if input_representation == "X":
        axis, source_key = ("layers", layer) if layer else ("X", "X")
        source = data.layers[layer] if layer else data.X
    else:
        if layer is not None:
            raise ValueError("输入嵌入时不可同时指定强度层")
        axis, source_key = "obsm", input_representation
        source = data.obsm[input_representation]
    if np.prod(source.shape) > 5_000_000:
        raise ValueError("输入表示超过同步工程上限 500 万数值")
    inputs = expanded_inputs(data, [binding(data, axis, source_key)])
    _dependency_fields(data, inputs)
    matrix = _numeric(source, "Palantir 输入表示")
    if matrix.ndim != 2 or not matrix.shape[1]:
        raise ValueError("Palantir 输入须为非空二维表示")
    work = AnnData(matrix.copy(), obs=pd.DataFrame(index=ids.copy()))
    with threadpool_limits(limits=1):
        run_palantir(
            work,
            start_idx=int(ids.get_loc(root_cell_id)),
            terminal_states=terminal_cell_ids,
            n_diff_components=n_diff_components,
            knn=knn,
            num_waypoints=num_waypoints,
            scale_components=scale_components,
            max_iterations=max_iterations,
            seed=seed,
            use_early_cell_as_start=use_early_cell_as_start,
            store_prefix=key,
            check_connected=True,
            n_jobs=1,
        )
    pseudotime = _numeric(work.obs[f"{key}_pseudotime"], "Palantir 伪时间")
    probs = _numeric(work.obsm[f"{key}_branch_probs"], "Palantir 分支概率")
    tolerance = _probabilities(probs, data.n_obs)
    _numeric(work.obsm[f"{key}_ms_data"], "Palantir 多尺度坐标")
    if (pseudotime < 0).any() or (pseudotime > 1).any():
        raise ValueError("Palantir 输出伪时间超出 0–1，未应用")
    if f"{key}_entropy" in work.obs:
        _numeric(work.obs[f"{key}_entropy"], "Palantir 熵")
    parameters = {
        "root_cell_id": root_cell_id,
        "terminal_cell_ids": terminal_cell_ids,
        "input_representation": input_representation,
        "layer": layer,
        "seed": seed,
        "n_diff_components": n_diff_components,
        "knn": knn,
        "num_waypoints": num_waypoints,
        "scale_components": scale_components,
        "max_iterations": max_iterations,
        "use_early_cell_as_start": use_early_cell_as_start,
        "n_jobs": 1,
        "palantir_version": version("palantir"),
        "connected_components": 1,
        "time_kind": "pseudotime",
        "unit": "unitless",
        "actual_earliest_cell_id": str(ids[int(np.argmin(pseudotime))]),
        "probability_validation_tolerance": tolerance,
    }
    work.uns[f"{key}_params"] = parameters.copy()
    outputs = []
    for name, keys in fields.items():
        for output in keys:
            if output in getattr(work, name):
                getattr(data, name)[output] = (
                    getattr(work, name)[output].copy()
                    if hasattr(getattr(work, name)[output], "copy")
                    else getattr(work, name)[output]
                )
                outputs.append(binding(data, name, output))
    return _publish(data, key, "palantir", parameters, inputs, outputs)


def _probabilities(values, count):
    tolerance = (
        64 * np.finfo(np.float64).eps * max(1, count, values.shape[1] if values.ndim == 2 else 1)
    )
    if (
        values.ndim != 2
        or values.shape[0] != count
        or not values.shape[1]
        or (values < 0).any()
        or (values > 1 + tolerance).any()
        or not np.allclose(values.sum(axis=1), 1, rtol=0, atol=tolerance)
    ):
        raise ValueError("分支概率须每细胞一行、有限、在 0–1 内且每行和为 1；不会自动归一化")
    return float(tolerance)


def trajectory(
    data,
    *,
    key,
    coordinate_key,
    time_key,
    time_kind,
    unit,
    branch_probability_key=None,
    window_size=100,
    step_size=50,
    min_cells_per_window=5,
):
    from scMM.plot._trajectory import _window_starts, resample_trajectory

    check_size(data)
    _new_key(data, key, [key, f"{key}_metadata", f"{key}_params"])
    source_coordinates = data.obsm[coordinate_key]
    if np.prod(source_coordinates.shape) > 5_000_000:
        raise ValueError("轨迹坐标超过同步工程上限 500 万数值")
    coordinates = np.asarray(
        source_coordinates.toarray()
        if hasattr(source_coordinates, "toarray")
        else source_coordinates,
        dtype=float,
    )
    if coordinates.ndim != 2 or coordinates.shape[1] < 2:
        raise ValueError("轨迹坐标须至少二维")
    time = _numeric(data.obs[time_key], "参数化时间")
    if time_kind == "normalized_time" and ((time < 0).any() or (time > 1).any()):
        raise ValueError("归一化采集时间须在 0–1 内")
    if time_kind in {"normalized_time", "pseudotime"} and unit != "unitless":
        raise ValueError("归一化/伪时间单位须为 unitless")
    if time_kind == "acquisition_seconds" and unit != "s":
        raise ValueError("采集秒数的单位须为 s")
    if not unit.strip():
        raise ValueError("须显式声明时间单位")
    inputs = [binding(data, "obsm", coordinate_key), binding(data, "obs", time_key)]
    for parent_key, parent in registry(data)["runs"].items():
        if (
            parent["kind"] == "palantir"
            and time_key == f"{parent_key}_pseudotime"
            and time_kind != "pseudotime"
        ):
            raise ValueError("该列由 Palantir 产生，须声明为伪时间")
    names = ["branch_0"]
    tolerance = None
    if branch_probability_key:
        source = data.obsm[branch_probability_key]
        if np.prod(source.shape) > 5_000_000:
            raise ValueError("分支概率超过同步工程上限 500 万数值")
        probabilities = _numeric(source, "分支概率")
        tolerance = _probabilities(probabilities, data.n_obs)
        inputs.append(binding(data, "obsm", branch_probability_key))
        names = (
            list(source.columns.astype(str))
            if isinstance(source, pd.DataFrame)
            else [f"branch_{index}" for index in range(probabilities.shape[1])]
        )
        for parent_key, parent in registry(data)["runs"].items():
            if (
                parent["kind"] == "palantir"
                and branch_probability_key == f"{parent_key}_branch_probs"
            ):
                names = [str(name) for name in data.uns[f"{parent_key}_branch_names"]]
    inputs = expanded_inputs(data, inputs)
    _dependency_fields(data, inputs)
    if (
        len(names)
        * len(_window_starts(data.n_obs, window_size, step_size))
        * (coordinates.shape[1] + 3)
        > 5_000_000
    ):
        raise ValueError("预计窗口结果超过同步工程上限 500 万数值，未分配结果数组")
    work = AnnData(
        np.empty((data.n_obs, 0)), obs=pd.DataFrame({time_key: time}, index=data.obs_names.copy())
    )
    work.obsm[coordinate_key] = coordinates
    if branch_probability_key:
        work.obsm[branch_probability_key] = probabilities
    resample_trajectory(
        work,
        window_size=window_size,
        step_size=step_size,
        cell_dist_key=coordinate_key,
        parameterization_key=time_key,
        branch_prob_key=branch_probability_key,
        store_key=key,
        min_cells_per_window=min_cells_per_window,
    )
    data.uns[key] = work.uns[key]
    data.uns[f"{key}_metadata"] = work.uns[f"{key}_metadata"]
    data.uns[f"{key}_metadata"]["sorted_obs_order"] = np.argsort(time)
    parameters = {
        "coordinate_key": coordinate_key,
        "time_key": time_key,
        "time_kind": time_kind,
        "unit": unit,
        "branch_probability_key": branch_probability_key,
        "branch_names": names,
        "requested_window_size": window_size,
        "window_size": min(window_size, data.n_obs),
        "step_size": step_size,
        "min_cells_per_window": min_cells_per_window,
        "seed": None,
        "probability_validation_tolerance": tolerance,
    }
    data.uns[f"{key}_params"] = parameters.copy()
    outputs = [binding(data, "uns", name) for name in (key, f"{key}_metadata", f"{key}_params")]
    return _publish(data, key, "trajectory", parameters, inputs, outputs)


def info(data):
    cache = {}
    return [
        {
            "key": key,
            "kind": run["kind"],
            "valid": valid_run(data, run, cache),
            "parameters": run["parameters"],
            "identity": run["identity"],
        }
        for key, run in registry(data)["runs"].items()
    ]


def result_tables(data, key):
    run = require_run(data, key)
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


def time_figure(data, *, key, coordinate_key=None):
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
