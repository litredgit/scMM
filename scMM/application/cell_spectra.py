"""Stable-cell linked spectra. Matrix bars and measured profile sources stay explicit."""

# ruff: noqa: RUF001
import json
from copy import deepcopy

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import sparse

from scMM.plot.raw import _peak_preserving_downsample

from .preview_cache import file_identity
from .raw_preview import RawPreviewService
from .web_support import figure_view


def cell_spectra(
    manager,
    identity,
    revision,
    *,
    cells,
    source="matrix",
    normalization="raw",
    mirror=False,
    average=False,
):
    with manager.access(identity) as workspace:
        workspace.check(revision)
        project = workspace.require_project()
        data = project.workspace.require_data()
        token = project.workspace.token
        snapshots = []
        for cell in cells:
            if cell not in data.obs_names:
                raise ValueError("所选细胞已失效，请重新选择。")
            row = data.obs.loc[cell]
            if source == "matrix":
                view = data[cell, :]
                values = (
                    view.X.toarray().ravel()
                    if sparse.issparse(view.X)
                    else np.asarray(view.X).ravel()
                )
                mz = pd.to_numeric(data.var.get("mz", data.var_names), errors="coerce").to_numpy(
                    dtype=float
                )
                if not np.isfinite(mz).all():
                    raise ValueError("当前矩阵缺少有效 m/z，无法绘制质谱。")
                snapshots.append(
                    (
                        cell,
                        pd.DataFrame({"mz": mz, "intensity": values}),
                        {"source": "matrix", "dataset_token": list(token)},
                    )
                )
            else:
                keys = [
                    "source_identity_json",
                    "cell_apex_scan",
                    "cell_start_scan",
                    "cell_stop_scan",
                ]
                if any(key not in row or pd.isna(row[key]) for key in keys):
                    raise ValueError("该细胞没有可追溯的原始扫描窗口，可选择当前矩阵特征谱。")
                sample = deepcopy(manager.sample(project, str(row["sample_id"])))
                snapshots.append((cell, {key: row[key] for key in keys}, sample))
    # Never retain the workspace lock while opening/reading an entire raw file.
    figure, tables, provenance = go.Figure(), {}, []
    for index, (cell, record, sample) in enumerate(snapshots):
        if source == "matrix":
            frame, detail = record, sample
        else:
            preview = RawPreviewService(manager.storage).open(sample["storage"], sample["path"])
            expected = json.loads(record["source_identity_json"])
            if preview.open_identity != expected:
                raise ValueError("原始文件身份已改变，请重新提取后查看原始谱。")
            if source == "apex":
                frame, detail = preview.single_spectrum(int(record["cell_apex_scan"]))
            else:
                first, last = int(record["cell_start_scan"]), int(record["cell_stop_scan"])
                # Use the source's measured mass extent instead of an experimental default.
                mz_range = (preview.summary.mz_min, preview.summary.mz_max)
                frame = preview.summed_spectrum(
                    mz_range=mz_range, scan_range=(first, last), normalize=average
                )
                detail = {
                    "scan_start": first,
                    "scan_stop": last,
                    "average": average,
                    "mz_range": mz_range,
                }
            if file_identity(preview.path) != expected:
                raise ValueError("原始文件在读取时发生改变。")
            detail.update(source=source, identity=expected)
        original = frame.copy()
        values = frame.intensity.to_numpy(dtype=float)
        denominator = (
            float(np.max(np.abs(values)))
            if normalization == "max"
            else float(np.sum(np.abs(values)))
            if normalization == "tic"
            else 1.0
        )
        display = values / denominator if denominator > 0 else values.copy()
        if mirror and index == 1:
            display = -display
        shown = frame.assign(intensity=display)
        shown = _peak_preserving_downsample(shown, 30000, "intensity")
        if source == "matrix":
            x = np.column_stack([shown.mz, shown.mz, np.full(len(shown), np.nan)]).ravel()
            y = np.column_stack(
                [np.zeros(len(shown)), shown.intensity, np.full(len(shown), np.nan)]
            ).ravel()
            figure.add_scatter(x=x, y=y, mode="lines", name=cell)
        else:
            figure.add_scatter(x=shown.mz, y=shown.intensity, mode="lines", name=cell)
        tables[f"{index + 1}_source.csv"] = original.to_csv(index=False)
        tables[f"{index + 1}_display.csv"] = frame.assign(intensity=display).to_csv(index=False)
        provenance.append({"cell": cell, **detail})
    figure.update_traces(
        hovertemplate="m/z=%{x:.5f}<br>强度=%{y:.1e}<extra>%{fullData.name}</extra>"
    )
    figure.update_layout(
        title="细胞质谱对比",
        xaxis_title="m/z",
        yaxis={
            "title": "强度" if normalization == "raw" else "归一化强度",
            "tickformat": ".1e",
            "hoverformat": ".1e",
        },
        meta={
            "provenance": provenance,
            "parameters": {
                "cells": cells,
                "source": source,
                "normalization": normalization,
                "mirror": mirror,
                "average": average,
            },
            "export_tables": tables,
        },
    )
    with manager.access(identity) as workspace:
        workspace.check(revision)
        if workspace.require_project().workspace.token != token:
            raise ValueError("数据已改变，请重新选择细胞。")
    return {"workspace": manager.view(workspace), "value": figure_view(figure)}
