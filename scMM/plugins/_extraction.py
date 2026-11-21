"""Resolve the two aligned-scan extension points for a frozen extraction request."""
# ruff: noqa: RUF001

from numbers import Integral

import numpy as np
import pandas as pd

from . import AlignedScans, CellEvent, ExtractionInput
from ._registry import MethodRegistry

KINDS = ("cell_detection", "cell_extraction")


def validate_selection(values):
    if not isinstance(values, dict) or values.keys() - set(KINDS):
        raise ValueError("提取插件选择包含未知阶段。")
    for selected in values.values():
        if (
            not isinstance(selected, dict)
            or set(selected) != {"id", "version", "options"}
            or any(type(selected[key]) is not str or not selected[key] for key in ("id", "version"))
            or not isinstance(selected["options"], dict)
        ):
            raise ValueError("提取插件必须包含方法 ID、版本和参数。")


def normalize_selection(values, registry):
    validate_selection(values)
    if values and registry is None:
        raise ValueError("提取插件需要通过已配置的网页入口选择。")
    resolved = {}
    for kind, row in values.items():
        method = registry.get(row["id"], kind=kind, version=row["version"])
        resolved[kind] = method.provenance(method.options(row["options"]))
    return resolved


def extraction_registry(enabled):
    return MethodRegistry(enabled) if enabled else None


def selected_packages(values):
    return sorted({row["id"].partition(":")[0] for row in values.values()})


def _detect(method, options, signal, metadata):
    result = method.run(AlignedScans(signal.copy(), metadata.copy()), options.copy())
    events = []
    previous = -1
    for event in result:
        if (
            not isinstance(event, CellEvent)
            or any(
                not isinstance(value, Integral) or isinstance(value, bool)
                for value in (event.start, event.apex, event.stop)
            )
            or not previous < event.start <= event.apex <= event.stop < len(signal)
        ):
            raise ValueError("细胞窗口须按扫描顺序排列，峰顶位于窗口内，且窗口互不重叠。")
        events.append((int(event.start), int(event.apex), int(event.stop)))
        previous = event.stop
    return events


def _quantify(method, options, signal, metadata, windows, apex):
    aligned = AlignedScans(signal.copy(), metadata.copy())
    events = tuple(
        CellEvent(start, int(peak), stop) for (start, stop), peak in zip(windows, apex, strict=True)
    )
    result = method.run(ExtractionInput(aligned, events), options.copy())
    if (
        not isinstance(result, pd.DataFrame)
        or not result.index.equals(pd.RangeIndex(len(events)))
        or not result.columns.is_unique
        or not result.columns.isin(signal.columns).all()
        or result.to_numpy().dtype.kind not in "fiu"
        or not np.isfinite(result.to_numpy()).all()
        or (result.to_numpy() < 0).any()
    ):
        raise ValueError("定量结果须按事件顺序返回对齐特征的有限非负矩阵。")
    return result.copy()


def extraction_kwargs(values, registry):
    """Bound callbacks only exist within the worker that executes the method."""
    normalized = normalize_selection(values, registry)
    callbacks = {}
    for kind, row in normalized.items():
        method = registry.get(row["id"], kind=kind, version=row["version"]).method
        options = row["options"]
        if kind == "cell_detection":

            def detect(signal, metadata, method=method, options=options):
                return _detect(method, options, signal, metadata)

            callbacks["cell_detector"] = detect
        else:

            def quantify(signal, metadata, windows, apex, method=method, options=options):
                return _quantify(method, options, signal, metadata, windows, apex)

            callbacks["cell_quantifier"] = quantify
            callbacks["plugin_intensity_definition"] = method.intensity_definition
    if normalized:
        callbacks["method_plugins"] = normalized
    return callbacks
