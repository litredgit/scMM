"""Explicit ordered m/z matching with lossless row/layer and reset-state assembly."""
# ruff: noqa: RUF001

import json
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import numpy as np
import pandas as pd
from anndata import AnnData

from scMM.file._dataset_processing import _match_feature_columns
from scMM.util.intensity import intensity_states, write_intensity_states

from .merge_metadata import annotation, mapping_rows, sample_values, values64
from .merge_sources import MAX_VALUES, check_size, extra_values


def masses(data, key):
    source = data.var_names if key is None else data.var[key]
    result = values64(np.asarray(source, dtype=float), finite=True)
    if (result <= 0).any() or len(np.unique(result)) != len(result):
        raise ValueError("m/z 必须为唯一、有限正数；重复质量不能按稳定 ID 静默混合")
    return result


def axis_plan(inputs, options, role):
    order = [options["reference"], *[i for i in range(len(inputs)) if i != options["reference"]]]
    features = []
    maps = [None] * len(inputs)
    rows = []
    ambiguous = 0
    for sequence, number in enumerate(order):
        entry = inputs[number]
        data = entry[role]
        values = masses(data, entry["spec"]["mass_key"])
        if not sequence:
            mapping = np.arange(data.n_vars, dtype=int)
            features = [
                {
                    "id": f"{entry['id']}:{identifier}",
                    "mz": float(mz),
                    "origin": entry["id"],
                    "original_id": str(identifier),
                }
                for identifier, mz in zip(data.var_names, values, strict=True)
            ]
            candidates = [[] for _ in values]
        else:
            targets = np.asarray([row["mz"] for row in features])
            sorted_right = np.sort(values)
            lower = targets * (1 - options["ppm_tol"] * 1e-6)
            upper = targets * (1 + options["ppm_tol"] * 1e-6)
            pairs = np.searchsorted(sorted_right, upper, side="right") - np.searchsorted(
                sorted_right, lower, side="left"
            )
            if pairs.sum() > 200000:
                raise ValueError("候选匹配超过 20 万对工程门限，请明确较小范围或整理输入")
            rename, _ = _match_feature_columns(
                pd.Index(targets), pd.Index(values), options["ppm_tol"]
            )
            target_positions = {value: i for i, value in enumerate(targets)}
            mapping = np.full(len(values), -1, dtype=int)
            candidates = []
            for column, value in enumerate(values):
                choices = np.flatnonzero((value >= lower) & (value <= upper))
                conflict = len(choices) > 1 or any(pairs[c] > 1 for c in choices)
                ambiguous += bool(conflict)
                candidates.append((choices.tolist(), bool(conflict)))
                if value in rename:
                    mapping[column] = target_positions[rename[value]]
                elif options["mode"] == "union":
                    mapping[column] = len(features)
                    features.append(
                        {
                            "id": f"{entry['id']}:{data.var_names[column]}",
                            "mz": float(value),
                            "origin": entry["id"],
                            "original_id": str(data.var_names[column]),
                        }
                    )
        maps[number] = mapping
        for column, value in enumerate(values):
            target = mapping[column]
            choices, conflict = ([], False) if not sequence else candidates[column]
            matched = target >= 0 and (sequence == 0 or features[target]["origin"] != entry["id"])
            rows.append(
                {
                    "input_id": entry["id"],
                    "feature_id": str(data.var_names[column]),
                    "mz": float(value),
                    "target_id": features[target]["id"] if target >= 0 else "",
                    "target_mz": features[target]["mz"] if target >= 0 else None,
                    "ppm_error": float(
                        (value - features[target]["mz"]) / features[target]["mz"] * 1e6
                    )
                    if target >= 0
                    else None,
                    "status": "reference"
                    if not sequence
                    else "matched"
                    if matched
                    else "added"
                    if target >= 0
                    else "excluded",
                    "ambiguous": conflict,
                    "candidate_count": len(choices),
                    "candidate_targets": "; ".join(features[c]["id"] for c in choices[:10]),
                }
            )
    if len(features) > 10000 or len({v["mz"] for v in features}) != len(features):
        raise ValueError("输出特征超过 1 万或发生质量冲突，未应用合并")
    cells = sum(entry[role].n_obs for entry in inputs)
    if cells > 20000 or cells * len(features) > 5_000_000:
        raise ValueError("输出超过 2 万细胞/500 万矩阵值工程上限")
    layers = sum(len(entry[role].layers) for entry in inputs)
    raw_features = sum(entry[role].raw.n_vars for entry in inputs if entry[role].raw is not None)
    expected = cells * len(features) * (2 + layers) + cells * raw_features
    expected += sum(
        extra_values(dict(entry[role].uns)) + entry[role].obs.size + entry[role].var.size
        for entry in inputs
    )
    return {
        "features": features,
        "maps": maps,
        "rows": rows,
        "order": order,
        "cells": cells,
        "ambiguous": ambiguous,
        "values": expected,
    }


def prepare(inputs, options):
    if not 0 <= options["reference"] < len(inputs):
        raise ValueError("请选择实际输入中的参考集")
    expected = {(row["input_id"], row["source_sample"]) for row in mapping_rows(inputs)}
    found = [(row["input_id"], row["source_sample"]) for row in options["mapping"]]
    if len(found) != len(set(found)) or set(found) != expected:
        raise ValueError("样本映射必须逐项完整覆盖当前数据及起点，不能按显示行号猜测")
    if any(
        not row["name"].strip() or row["name"] != row["name"].strip() for row in options["mapping"]
    ):
        raise ValueError("请明确填写每项映射的目标样本名，且不要首尾空白")
    common = options["common_observations"]
    reserved = {
        "sample_id",
        "sample",
        "group",
        "subject",
        "batch",
        "merge_input",
        "merge_original_cell_id",
        "merge_original_sample",
    }
    if (
        len(set(common)) != len(common)
        or set(common) & reserved
        or any(key.startswith(tuple(f"m{i}__" for i in range(8))) for key in common)
    ):
        raise ValueError("共同元数据字段重复或与样本/来源保留字段冲突")
    seen = set()
    for entry in inputs:
        for role in ("data", "baseline"):
            data = entry[role]
            if id(data) in seen:
                continue
            seen.add(id(data))
            values64(data.X, finite=True)
            for value in data.layers.values():
                values64(value)
            if data.raw is not None:
                values64(data.raw.X)
    roles = {
        "data": axis_plan(inputs, options, "data"),
        "baseline": axis_plan(inputs, {**options, "mode": "union"}, "baseline"),
    }
    if sum(plan["values"] for plan in roles.values()) > MAX_VALUES:
        raise ValueError("当前及完整起点的矩阵/分来源层/raw 超过 2000 万数值工程门限，不静默丢层")
    # Check metadata conversion before granting a preview token, without constructing matrices.
    for role, plan in roles.items():
        observations, _ = observations_for(inputs, options, plan, role, "preview")
        variable_frame(inputs, plan, role)
        for key in common:
            if not any(key in entry[role].obs for entry in inputs):
                raise ValueError(f"共同元数据字段不存在：{key}")
        del observations
    return roles


def observations_for(inputs, options, plan, role, namespace):
    frames = []
    source_rows = {}
    lookup = {(row["input_id"], row["source_sample"]): row for row in options["mapping"]}
    for number in plan["order"]:
        entry = inputs[number]
        data = entry[role]
        ids = [f"{entry['id']}:{value}" for value in data.obs_names]
        original = sample_values(data, entry["spec"]["sample_key"])
        mappings = [lookup[(entry["id"], value)] for value in original]
        frame = pd.DataFrame(
            {
                "merge_input": entry["id"],
                "merge_original_cell_id": data.obs_names.astype(str),
                "merge_original_sample": original.to_numpy(),
                "sample": [row["name"].strip() for row in mappings],
            },
            index=ids,
        )
        frame["sample_id"] = [
            uuid5(NAMESPACE_URL, f"scmm-merge:{namespace}:sample:{name}").hex
            for name in frame["sample"]
        ]
        for field in ("group", "subject", "batch"):
            values = (
                data.obs[field].astype(object).tolist() if field in data.obs else [""] * data.n_obs
            )
            frame[field] = [
                str(row[field]) if row[field] is not None else "" if pd.isna(value) else str(value)
                for row, value in zip(mappings, values, strict=True)
            ]
        frames.append(frame)
        source_rows[number] = pd.Index(ids)
    result = pd.concat(frames)
    for key in result:
        result[key] = pd.Categorical(result[key])
    annotations = {}
    for number in plan["order"]:
        entry = inputs[number]
        data = entry[role]
        for key in data.obs:
            value = data.obs[key].copy()
            value.index = source_rows[number]
            annotations[f"{entry['id']}__{key}"] = annotation([value], result.index)
    for key in options["common_observations"]:
        parts = []
        for number in plan["order"]:
            data = inputs[number][role]
            if key in data.obs:
                value = data.obs[key].copy()
                value.index = source_rows[number]
                parts.append(value)
        annotations[key] = annotation(parts, result.index)
    return pd.concat([result, pd.DataFrame(annotations, index=result.index)], axis=1), source_rows


def variable_frame(inputs, plan, role):
    result = pd.DataFrame(
        {
            "mz": [row["mz"] for row in plan["features"]],
            "merge_origin": [row["origin"] for row in plan["features"]],
            "merge_original_feature_id": [row["original_id"] for row in plan["features"]],
        },
        index=[row["id"] for row in plan["features"]],
    )
    columns = {}
    for number, entry in enumerate(inputs):
        mapping = plan["maps"][number]
        positions = np.flatnonzero(mapping >= 0)
        for key in entry[role].var:
            series = entry[role].var[key].iloc[positions].copy()
            series.index = result.index[mapping[positions]]
            columns[f"{entry['id']}__{key}"] = annotation([series], result.index)
    return pd.concat([result, pd.DataFrame(columns, index=result.index)], axis=1)


def merged_state(states):
    if "transformed" in states:
        return "transformed"
    return states[0] if len(set(states)) == 1 else "unknown"


def assemble(inputs, options, plan, role, namespace):
    obs, _source_rows = observations_for(inputs, options, plan, role, namespace)
    var = variable_frame(inputs, plan, role)
    matrix = np.zeros((len(obs), len(var)), dtype=np.float64)
    layers = {}
    layer_sources = {}
    raw_sources = []
    snapshots = {}
    states = []
    offset = 0
    for number in plan["order"]:
        entry = inputs[number]
        data = entry[role]
        rows = np.arange(offset, offset + data.n_obs)
        offset += data.n_obs
        mapping = plan["maps"][number]
        keep = np.flatnonzero(mapping >= 0)
        matrix[np.ix_(rows, mapping[keep])] = values64(data.X, finite=True)[:, keep]
        lineage = intensity_states(data)
        states.append(lineage["X"])
        for ordinal, (key, value) in enumerate(data.layers.items()):
            output = f"merge_{entry['id']}_layer_{ordinal}"
            values = np.full(matrix.shape, np.nan, dtype=np.float64)
            values[np.ix_(rows, np.arange(len(var)))] = 0
            values[np.ix_(rows, mapping[keep])] = values64(value)[:, keep]
            layers[output] = values
            layer_sources[output] = {
                "input_id": entry["id"],
                "source_layer": key,
                "intensity_state": lineage[key],
            }
        if data.raw is not None:
            raw_sources.append((entry, rows, data.raw))
        snapshots[entry["id"]] = {
            "obs": data.obs.copy(),
            "var": data.var.copy(),
            "uns": deepcopy(dict(data.uns)),
            "raw_var": data.raw.var.copy() if data.raw is not None else pd.DataFrame(),
            "excluded_analysis_slots": json.dumps(
                {slot: list(getattr(data, slot)) for slot in ("obsm", "obsp", "varm", "varp")}
            ),
        }
    result = AnnData(matrix, obs=obs, var=var)
    for key, value in layers.items():
        result.layers[key] = value
    if raw_sources:
        raw_vars = []
        raw_count = sum(raw.n_vars for _, _, raw in raw_sources)
        raw_matrix = np.full((len(obs), raw_count), np.nan, dtype=np.float64)
        column = 0
        for entry, rows, raw in raw_sources:
            raw_matrix[np.ix_(rows, np.arange(column, column + raw.n_vars))] = values64(raw.X)
            frame = raw.var.copy()
            frame["merge_original_feature_id"] = raw.var_names.astype(str)
            frame["merge_input"] = entry["id"]
            frame.index = [f"{entry['id']}:{value}" for value in raw.var_names]
            raw_vars.append(frame)
            column += raw.n_vars
        raw_index = pd.Index([name for frame in raw_vars for name in frame.index])
        fields = list(dict.fromkeys(field for frame in raw_vars for field in frame.columns))
        raw_var = pd.DataFrame(
            {
                field: annotation([frame[field] for frame in raw_vars if field in frame], raw_index)
                for field in fields
            },
            index=raw_index,
        )
        result.raw = AnnData(raw_matrix, obs=pd.DataFrame(index=obs.index), var=raw_var)
    result.uns["scmm_merge_sources"] = snapshots
    result.uns["scmm_merge_json"] = json.dumps(
        {
            "schema_version": 1,
            "merge_id": namespace,
            "output_shape": list(result.shape),
            "role": role,
            "mode": "union" if role == "baseline" else options["mode"],
            "requested_current_mode": options["mode"],
            "reference": options["reference"],
            "ppm_tol": options["ppm_tol"],
            "ambiguity": options["ambiguity"],
            "matching": "existing_reference_sorted_greedy_closest_unused; reference_ppm_denominator; absent_feature=0",
            "inputs": [
                {key: entry[key] for key in ("id", "spec", "identity", "scope", "label")}
                for entry in inputs
            ],
            "feature_mapping": plan["rows"],
            "sample_mapping": options["mapping"],
            "common_observations": options["common_observations"],
            "layer_sources": layer_sources,
            "raw_policy": "source_namespaced_axes; absent_source=NaN; no_mass_alignment",
            "new_baseline": "full_current_workspace_baseline; standalone_file_as_imported",
        },
        ensure_ascii=False,
        allow_nan=False,
    )
    write_intensity_states(
        result,
        {
            "X": merged_state(states),
            **{key: value["intensity_state"] for key, value in layer_sources.items()},
        },
    )
    check_size(result)
    return result
