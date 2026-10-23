"""Time input identities, dependency validation and candidate result registration."""

# ruff: noqa: RUF001
import json
import re
from uuid import uuid4

import numpy as np

from scMM.util.time_results import binding, cell_identity, registry, valid_run, write_registry


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
    total += sum(
        sum(np.asarray(item).size for item in data.uns[name].values())
        for name, run in value["runs"].items()
        if run["kind"] in {"velocity", "trends", "trend_clusters"} and not run.get("stale")
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


def _validated_time(data, time_key, time_kind, unit):
    time = _numeric(data.obs[time_key], "参数化时间")
    if time_kind == "normalized_time" and ((time < 0).any() or (time > 1).any()):
        raise ValueError("归一化采集时间须在 0–1 内")
    if time_kind in {"normalized_time", "pseudotime"} and unit != "unitless":
        raise ValueError("归一化/伪时间单位须为 unitless")
    if time_kind == "acquisition_seconds" and unit != "s":
        raise ValueError("采集秒数的单位须为 s")
    if not unit.strip():
        raise ValueError("须显式声明时间单位")
    for parent_key, parent in registry(data)["runs"].items():
        if (
            parent["kind"] == "palantir"
            and time_key == f"{parent_key}_pseudotime"
            and time_kind != "pseudotime"
        ):
            raise ValueError("该列由 Palantir 产生，须声明为伪时间")
    if time_kind not in {
        "acquisition_seconds",
        "normalized_time",
        "experimental_time",
        "pseudotime",
    }:
        raise ValueError("须明确声明时间含义")
    return time
