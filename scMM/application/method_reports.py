"""Plain, source-bound reports that can be read with the method uninstalled."""

import json
import re
from uuid import uuid4

import pandas as pd

from scMM.ion.identity import axis_identity, json_identity, matrix_identity, table_identity
from scMM.ion.semantics import value_states

KEY = "scmm_method_reports_json"
REPORT_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}:[a-z][a-z0-9_-]{0,63}")


def _input_identity(data, layer, fields):
    return json_identity(
        {
            "cells": axis_identity(data.obs_names),
            "features": axis_identity(data.var_names),
            "measurement_root": data.uns.get("scmm_measurement_root_id"),
            "space": value_states(data)[layer or "X"]["space"],
            "matrix": matrix_identity(data.layers[layer] if layer else data.X),
            "observations": table_identity(data.obs[list(fields)]),
        }
    )


def current_reports(data):
    try:
        registry = json.loads(data.uns.get(KEY, '{"schema_version":1,"reports":{}}'))
    except (TypeError, ValueError):
        return {}
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        return {}
    reports = registry.get("reports")
    if not isinstance(reports, dict):
        return {}
    cache = {}
    valid = {}
    for key, report in reports.items():
        if (
            REPORT_ID.fullmatch(key) is None
            or not isinstance(report, dict)
            or not isinstance(report.get("label"), str)
            or not isinstance(report.get("identity"), str)
            or re.fullmatch(r"[0-9a-f]{32}", report["identity"]) is None
            or not isinstance(report.get("method"), dict)
            or not isinstance(report.get("analysis_input"), dict)
            or not isinstance(report.get("columns"), list)
            or not isinstance(report.get("rows"), list)
            or not isinstance(report.get("fields"), list)
            or any(type(name) is not str for name in report["fields"])
            or (report.get("layer") is not None and not isinstance(report["layer"], str))
        ):
            continue
        inputs = (report.get("layer"), tuple(report["fields"]))
        if inputs not in cache:
            try:
                cache[inputs] = _input_identity(data, *inputs)
            except (KeyError, ValueError):
                cache[inputs] = None
        if cache[inputs] is not None and report.get("input_identity") == cache[inputs]:
            valid[key] = report
    return valid


def report_summaries(data):
    return [
        {"id": key, "label": report["label"], "identity": report["identity"]}
        for key, report in current_reports(data).items()
    ]


def report_frame(report):
    return pd.DataFrame(
        {
            column: pd.Series([row.get(column) for row in report["rows"]], dtype=object)
            for column in report["columns"]
        }
    )


def store_report(data, method, options, *, layer, fields, table, figure, context):
    from .web_support import json_view

    if (
        not isinstance(table, pd.DataFrame)
        or not len(table.columns)
        or not table.columns.is_unique
        or any(type(key) is not str or not key.strip() for key in table.columns)
    ):
        raise ValueError("统计方法必须返回列名唯一且非空的表格。")
    # to_dict preserves doubles, and the shared JSON conversion handles missing values.
    try:
        rows = json_view(table.astype(object).where(table.notna(), None).to_dict(orient="records"))
    except (TypeError, AttributeError) as exc:
        raise ValueError("统计表包含协议不支持的数值类型。") from exc
    if any(
        value is not None and type(value) not in {int, str, bool, float}
        for row in rows
        for value in row.values()
    ):
        raise ValueError("统计表单元格须为数值、文本、布尔或缺失值。")
    # Store one latest result per method. Distinct runs still have distinct identities.
    reports = current_reports(data)
    report = {
        "identity": uuid4().hex,
        "label": method.method.label,
        "method": method.provenance(options),
        "analysis_input": context,
        "layer": layer,
        "fields": fields,
        "input_identity": _input_identity(data, layer, fields),
        "columns": list(table.columns),
        "rows": rows,
        "figure": figure,
    }
    if figure is not None:
        figure["layout"]["meta"].update(
            method_result=method.id,
            method_result_identity=report["identity"],
        )
    reports[method.id] = report
    data.uns[KEY] = json.dumps(
        {"schema_version": 1, "reports": reports},
        ensure_ascii=False,
        allow_nan=False,
    )
    return report
