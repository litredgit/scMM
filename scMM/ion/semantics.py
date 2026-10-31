"""Numerical space and imputation lineage, independent of instrument provenance."""

import json
from copy import deepcopy

from .contracts import VALUE_SEMANTICS, validate_schema

KEY = "scmm_value_semantics_json"


def unknown_state():
    return {"space": "unknown", "imputed": False, "normalization": [], "history": []}


def value_states(data):
    states = {key: unknown_state() for key in ["X", *data.layers]}
    if KEY not in data.uns:
        return states
    try:
        payload = json.loads(data.uns[KEY])
        validate_schema(payload)
        declared = payload["states"]
        if not isinstance(declared, dict) or "X" not in declared:
            raise ValueError
        for key, state in declared.items():
            if (
                not isinstance(key, str)
                or not isinstance(state, dict)
                or state.get("space") not in VALUE_SEMANTICS
                or type(state.get("imputed")) is not bool
                or not isinstance(state.get("normalization"), list)
                or not isinstance(state.get("history"), list)
            ):
                raise ValueError
        states.update({key: deepcopy(state) for key, state in declared.items() if key in states})
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError("invalid value semantics") from exc
    return states


def write_value_states(data, states):
    payload = {"schema_version": 1, "states": states}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
    candidate = data.copy()
    candidate.uns[KEY] = encoded
    value_states(candidate)
    data.uns[KEY] = encoded


def transform_value_state(state, operation, parameters):
    result = deepcopy(state)
    if operation == "normalize":
        method = parameters["method"]
        if method == "log":
            result["space"] = "log_abundance" if result["space"] == "linear_abundance" else "other"
        elif method == "zscore":
            result["space"] = "standard_score"
        elif method not in {"total", "max", "pqn"} or result["space"] not in {
            "linear_abundance",
            "unknown",
        }:
            result["space"] = "other"
        result["normalization"].append(deepcopy(parameters))
    elif operation == "impute":
        result["imputed"] = True
    result["history"].append({"operation": operation, "parameters": deepcopy(parameters)})
    return result
