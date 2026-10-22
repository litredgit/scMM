"""Typed, non-executable time results and their explicit AnnData dependencies."""

import hashlib
import json
import re

import numpy as np
import pandas as pd

TIME_RESULTS = "scmm_time_results_json"


def _plain(value):
    if isinstance(value, pd.DataFrame):
        return {
            "index": value.index.astype(str).tolist(),
            "columns": value.columns.astype(str).tolist(),
            "values": value.to_numpy().tolist(),
        }
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def fingerprint(value):
    if hasattr(value, "toarray"):
        value = value.toarray()
    if isinstance(value, (pd.Series, np.ndarray)):
        values = np.asarray(value)
        if values.dtype.kind in "biuf":
            values = np.ascontiguousarray(values, dtype=np.float64)
            return hashlib.sha256(str(values.shape).encode() + values.tobytes()).hexdigest()
    return hashlib.sha256(
        json.dumps(_plain(value), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def registry(data):
    value = json.loads(data.uns.get(TIME_RESULTS, '{"schema_version":1,"runs":{}}'))
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("runs"), dict)
        or len(value["runs"]) > 64
    ):
        raise ValueError("Unsupported time result metadata")
    for key, run in value["runs"].items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", key)
            or key.startswith("scmm_")
            or not isinstance(run, dict)
            or run.get("kind") not in {"palantir", "trajectory"}
            or not isinstance(run.get("parameters"), dict)
            or not isinstance(run.get("identity"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", run["identity"])
            or not isinstance(run.get("cell_identity"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", run["cell_identity"])
            or not isinstance(run.get("stale"), bool)
            or run.get("implementation") != "scmm-time-v1"
        ):
            raise ValueError("Invalid time result metadata")
        if not isinstance(run.get("observation_dependencies"), list) or any(
            not isinstance(field, str) for field in run["observation_dependencies"]
        ):
            raise ValueError("Invalid time dependencies")
        for field in ("inputs", "outputs"):
            if not isinstance(run.get(field), list):
                raise ValueError("Invalid time bindings")
            for item in run[field]:
                if (
                    not isinstance(item, dict)
                    or item.get("axis") not in {"X", "layers", "obs", "obsm", "uns"}
                    or not isinstance(item.get("key"), str)
                    or not isinstance(item.get("digest"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["digest"])
                ):
                    raise ValueError("Invalid time binding")
                if field == "outputs" and (
                    item["axis"] not in {"obs", "obsm", "uns"}
                    or not (item["key"] == key or item["key"].startswith(f"{key}_"))
                ):
                    raise ValueError("Invalid time output namespace")
    return value


def write_registry(data, value):
    data.uns[TIME_RESULTS] = json.dumps(_plain(value), ensure_ascii=False, allow_nan=False)


def read_binding(data, axis, key):
    return data.X if axis == "X" else getattr(data, axis)[key]


def _uns_value(value):
    value = _plain(value)
    if isinstance(value, dict):
        # AnnData's H5AD writer omits None-valued uns entries. The canonical
        # registry JSON separately retains requested null/default parameters.
        return {key: _uns_value(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_uns_value(item) for item in value]
    return value


def binding(data, axis, key):
    value = read_binding(data, axis, key)
    digest = (
        hashlib.sha256(
            json.dumps(_uns_value(value), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if axis == "uns"
        else fingerprint(value)
    )
    return {"axis": axis, "key": key, "digest": digest}


def cell_identity(data):
    return fingerprint(data.obs_names.astype(str).tolist())


def valid_run(data, run, cache=None):
    cache = {} if cache is None else cache
    if ("cell_identity", "") not in cache:
        cache[("cell_identity", "")] = cell_identity(data)
    identity = cache[("cell_identity", "")]
    if run.get("stale") or run.get("cell_identity") != identity:
        return False
    try:
        for item in [*run["inputs"], *run["outputs"]]:
            key = (item["axis"], item["key"])
            if key not in cache:
                cache[key] = binding(data, *key)["digest"]
            if cache[key] != item["digest"]:
                return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


def require_run(data, key):
    run = registry(data)["runs"].get(key)
    if run is None or not valid_run(data, run):
        raise ValueError("Time result is missing or stale; recompute under a new output key")
    return run


def valid_time_figure(data, metadata):
    try:
        run = require_run(data, metadata["time_result_key"])
        return run["identity"] == metadata.get("time_result_identity") and all(
            binding(data, item["axis"], item["key"])["digest"] == item["digest"]
            for item in metadata.get("time_plot_inputs", [])
        )
    except (KeyError, ValueError, TypeError):
        return False


def invalidate_time_results(data, changed=(), *, clear=False):
    """Expire individual runs and descendants on a caller-owned candidate only."""
    if TIME_RESULTS not in data.uns:
        return set()
    value = registry(data)
    removed = set()
    while True:
        expired = [
            run
            for run in value["runs"].values()
            if not run.get("stale")
            and (
                clear
                or set(run["observation_dependencies"]) & set(changed)
                or not valid_run(data, run)
            )
        ]
        if not expired:
            break
        for run in expired:
            for output in run["outputs"]:
                axis, key = output["axis"], output["key"]
                mapping = getattr(data, axis)
                # An external writer's replacement is not owned by the old result.
                if key in mapping and binding(data, axis, key)["digest"] == output["digest"]:
                    del mapping[key]
                    if axis == "obs":
                        removed.add(key)
            run["stale"] = True
    if clear:
        data.uns.pop(TIME_RESULTS, None)
    else:
        write_registry(data, value)
    metadata = data.uns.get("scmm_workbench", {})
    if "derived_obs" in metadata:
        metadata["derived_obs"] = [key for key in metadata["derived_obs"] if key not in removed]
    return removed
