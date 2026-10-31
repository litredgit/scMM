"""Canonical identities independent of storage layout and application state."""

import hashlib
import json

import numpy as np
import pandas as pd
from scipy import sparse


def json_identity(value):
    """Hash strict JSON; reject unrecordable or nonfinite parameters."""
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def matrix_identity(values, *, allow_missing=False):
    """Canonical real rows; preserve integers and normalize layout, endian and NaN payload."""
    if len(values.shape) != 2:
        raise ValueError("matrix must have two dimensions")
    kind = values.dtype.kind
    if kind not in "biuf":
        raise ValueError("matrix must contain real numeric values")
    canonical_dtype = {"b": "?", "i": "<i8", "u": "<u8", "f": "<f8"}[kind]
    digest = hashlib.sha256(json.dumps([list(values.shape), kind]).encode("ascii"))
    for start in range(0, values.shape[0], 128):
        block = values[start : start + 128]
        block = block.toarray() if sparse.issparse(block) else np.asarray(block)
        block = np.array(block, dtype=canonical_dtype, order="C", copy=True)
        if np.isinf(block).any() or (not allow_missing and np.isnan(block).any()):
            raise ValueError("matrix contains unsupported nonfinite values")
        block[block == 0] = 0  # signed zero has the same quantitative meaning
        if kind == "f":
            block[np.isnan(block)] = np.nan
        digest.update(block.tobytes())
    return digest.hexdigest()


def axis_identity(identifiers):
    values = list(identifiers)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("axis IDs must be nonempty strings")
    if len(values) != len(set(values)):
        raise ValueError("axis IDs must be unique")
    return json_identity(values)


def table_identity(frame):
    """Encode scalar metadata without display rounding of floating point masses."""

    def scalar(value):
        if value is None or value is pd.NA or pd.isna(value):
            return None
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, (int, np.integer)):
            return {"integer": str(value)}
        if isinstance(value, (float, np.floating)):
            return {"float": float(value).hex()}
        if isinstance(value, str):
            return value
        if isinstance(value, pd.Timestamp):
            return {"timestamp": value.isoformat()}
        raise ValueError("unsupported metadata scalar")

    return json_identity(
        {
            "index": list(frame.index),
            "columns": list(frame.columns),
            "dtypes": ["string" if dtype.kind in "OUS" else str(dtype) for dtype in frame.dtypes],
            "values": [
                [scalar(value) for value in row] for row in frame.itertuples(index=False, name=None)
            ],
        }
    )


def dataset_identity(data, *, allow_missing=False):
    """Bind measured values to exact cell/variable IDs and measurement layers."""
    return json_identity(
        {
            "schema_version": 1,
            "measurement_root_id": data.uns.get("scmm_measurement_root_id"),
            "cells": axis_identity(data.obs_names),
            "variables": axis_identity(data.var_names),
            "X": matrix_identity(data.X, allow_missing=allow_missing),
            "layers": {
                str(key): matrix_identity(value, allow_missing=allow_missing)
                for key, value in data.layers.items()
            },
            "obs": table_identity(data.obs),
            "var": table_identity(data.var),
        }
    )
