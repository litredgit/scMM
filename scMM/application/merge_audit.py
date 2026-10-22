"""Immutable historical merge provenance, distinct from current analysis results."""

import hashlib
import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd


def merge_info(data):
    raw = data.uns.get("scmm_merge_json") if data is not None else None
    if not raw:
        return {"available": False}
    value = json.loads(raw)
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported merge audit version")
    return {
        "available": True,
        "key": hashlib.sha256(raw.encode()).hexdigest(),
        "scope": "historical_merge_not_current_analysis",
        "role": value["role"],
        "shape": value["output_shape"],
        "mode": value["mode"],
    }


def bundle(metadata, tables):
    result = BytesIO()
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, allow_nan=False))
        for name, frame in tables.items():
            archive.writestr(name + ".csv", frame.to_csv(index=False))
    return result.getvalue()


def audit_bundle(state, key):
    if merge_info(state.data).get("key") != key:
        raise ValueError("Merge audit is missing or changed")
    records = {
        role: json.loads(data.uns["scmm_merge_json"])
        for role, data in (("current", state.data), ("baseline", state._original))
        if "scmm_merge_json" in data.uns
    }
    tables = {
        role + "_feature_mapping": pd.DataFrame(value["feature_mapping"])
        for role, value in records.items()
    }
    tables["sample_mapping"] = pd.DataFrame(records["current"]["sample_mapping"])
    return bundle({"scope": "historical_merge_not_current_analysis", "records": records}, tables)
