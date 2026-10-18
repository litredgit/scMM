"""Shared, conservative intensity lineage for AnnData and dataset facades."""

import json

PROVENANCE_KEY = "scmm_intensity_provenance_json"
STATES = {"raw", "normalized", "transformed", "unknown"}


def transformed_state(state, operation, parameters=None):
    """Classify an operation without inferring an unknown input's origin."""
    if operation == "impute":
        return "transformed"
    if operation == "normalize":
        if (parameters or {}).get("method") not in {"total", "max", "pqn"}:
            return "transformed"
        return "normalized" if state in {"raw", "normalized"} else state
    if operation in {"filter", "outliers", "reduce", "cluster", "latent"}:
        return state
    return "unknown"


def intensity_states(data):
    """Return states for X and existing layers; old names/history cannot prove raw."""
    states = {"X": "unknown", **{name: "unknown" for name in data.layers}}
    if PROVENANCE_KEY in data.uns:
        try:
            payload = json.loads(data.uns[PROVENANCE_KEY])
            declared = payload["states"]
            if (
                payload["schema_version"] != 1
                or not isinstance(declared, dict)
                or "X" not in declared
                or any(not isinstance(k, str) or v not in STATES for k, v in declared.items())
            ):
                raise ValueError
        except (TypeError, KeyError, ValueError) as exc:
            raise ValueError("invalid intensity provenance") from exc
        states.update({k: v for k, v in declared.items() if k in states})
    else:
        # Legacy history can demonstrate transformation, never an unrecorded origin.
        history = json.loads(data.uns.get("scmm_workbench", {}).get("history_json", "[]"))
        if not isinstance(history, list) or any(not isinstance(step, dict) for step in history):
            raise ValueError("invalid preprocessing history")
        current = "unknown"
        for step in history:
            operation = step.get("operation")
            if operation == "restore":
                current = states.get(step.get("parameters", {}).get("layer"), "unknown")
            elif operation == "reset":
                current = "unknown"
            else:
                current = transformed_state(current, operation, step.get("parameters"))
            if step.get("layer") in states:
                states[step["layer"]] = current
        states["X"] = current
    if "feature_snr" in states:
        states["feature_snr"] = "transformed"
    return states


def write_intensity_states(data, states):
    """Persist an explicit versioned snapshot independent of session history."""
    data.uns[PROVENANCE_KEY] = json.dumps({"schema_version": 1, "states": states}, sort_keys=True)


def dataset_intensity_state(dataset):
    """Native extraction records origin; legacy directories remain unknown."""
    state = dataset.file_meta.get("intensity_state", "unknown")
    if state not in STATES:
        raise ValueError("invalid dataset intensity state")
    return state


def merged_intensity_state(*datasets):
    states = {dataset_intensity_state(dataset) for dataset in datasets}
    if "transformed" in states:
        return "transformed"
    if "unknown" in states:
        return "unknown"
    return "normalized" if "normalized" in states else "raw"
