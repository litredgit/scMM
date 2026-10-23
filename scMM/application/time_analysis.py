"""Explicit adapters for existing Palantir and window-trajectory definitions."""
# ruff: noqa: RUF001

from importlib.metadata import version

import numpy as np
import pandas as pd
from anndata import AnnData
from threadpoolctl import threadpool_limits

from scMM.util.time_results import binding, registry, valid_run

from .time_inputs import (
    _dependency_fields as _dependency_fields,
)
from .time_inputs import (
    _new_key as _new_key,
)
from .time_inputs import (
    _numeric as _numeric,
)
from .time_inputs import (
    _probabilities as _probabilities,
)
from .time_inputs import (
    _publish as _publish,
)
from .time_inputs import (
    _validated_time as _validated_time,
)
from .time_inputs import (
    check_size as check_size,
)
from .time_inputs import (
    expanded_inputs as expanded_inputs,
)
from .time_outputs import (
    result_metadata as result_metadata,
)
from .time_outputs import (
    result_tables as result_tables,
)
from .time_outputs import (
    time_figure as time_figure,
)


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
    time = _validated_time(data, time_key, time_kind, unit)
    inputs = [binding(data, "obsm", coordinate_key), binding(data, "obs", time_key)]
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


def velocity(data, *, key, time_key, time_kind, unit, layer=None, window_size=100, step_size=50):
    from scMM.plot._trajectory import _window_starts, metabolic_velocity_field

    check_size(data)
    _new_key(data, key, [key, f"{key}_params"])
    time = _validated_time(data, time_key, time_kind, unit)
    matrix = _numeric(data.layers[layer] if layer else data.X, "速度输入强度")
    starts = _window_starts(data.n_obs, window_size, step_size)
    expected = len(starts) * (2 * data.n_vars + 5)
    existing = sum(
        sum(np.asarray(value).size for value in data.uns[name].values())
        for name, run in registry(data)["runs"].items()
        if run["kind"] in {"velocity", "trends", "trend_clusters"} and not run.get("stale")
    )
    if expected + existing > 5_000_000:
        raise ValueError("速度窗口结果超过同步工程上限 500 万数值")
    inputs = expanded_inputs(
        data,
        [
            binding(data, "layers", layer) if layer else binding(data, "X", "X"),
            binding(data, "obs", time_key),
        ],
    )
    _dependency_fields(data, inputs)
    work = AnnData(matrix.copy(), obs=pd.DataFrame({time_key: time}, index=data.obs_names.copy()))
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            metabolic_velocity_field(
                work, parameterization_key=time_key, window_size=window_size, step_size=step_size
            )
    except FloatingPointError as exc:
        raise ValueError("速度回归出现数值溢出，未应用结果；请检查强度和时间尺度") from exc
    values = work.uns["metabolic_velocity"]
    valid = values["counts"] > 0
    if any(
        not np.isfinite(values[name][valid]).all()
        for name in ("state_centers", "velocity_field", "speeds", "time_centers")
    ):
        raise ValueError("速度回归产生非有限值，未应用结果")
    values["sorted_obs_order"] = np.argsort(time)
    parameters = {
        "time_key": time_key,
        "time_kind": time_kind,
        "unit": unit,
        "layer": layer,
        "input_representation": "X" if layer is None else f"layers:{layer}",
        "feature_ids": data.var_names.astype(str).tolist(),
        "requested_window_size": window_size,
        "window_size": min(window_size, data.n_obs),
        "step_size": step_size,
        "seed": None,
        "direction": "increasing_time",
        "velocity_unit": f"input_intensity / {unit}",
    }
    data.uns[key] = values
    data.uns[f"{key}_params"] = parameters.copy()
    return _publish(
        data,
        key,
        "velocity",
        parameters,
        inputs,
        [binding(data, "uns", name) for name in (key, f"{key}_params")],
    )


def trends(data, **options):
    from .time_trends import trends as compute

    return compute(data, **options)


def trend_clusters(data, **options):
    from .time_trend_clusters import trend_clusters as compute

    return compute(data, **options)


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
