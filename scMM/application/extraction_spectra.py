"""Frozen profile evidence for extraction batches."""
# ruff: noqa: RUF001

from pathlib import Path
from uuid import uuid4

import numpy as np

from scMM.file.io import sum_spec

from . import mz_lists
from .preview_cache import digest_file
from .projects import child_path


def summed_profile(exp, params, selection):
    spectrum = sum_spec(
        exp,
        resolution_200=params.resolution,
        points_per_fwhm=params.resample_points_per_fwhm,
        mz_range=(params.mz_min, params.mz_max),
        rt_range=selection.get("rt_range"),
        frame_range=selection.get("frame_range"),
    )
    return spectrum.get_peaks()


def save_profile(path, mz, intensity, targets, contributors):
    path = Path(path)
    temporary = path.with_name(f".{uuid4().hex}.npz")
    try:
        np.savez_compressed(
            temporary,
            mz=mz,
            intensity=intensity,
            targets=targets,
            contributors=np.asarray(contributors, dtype=str),
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return digest_file(path)


def load_profile(path, checksum):
    if not checksum:
        raise ValueError("此批次没有叠加谱记录。请通过新批次生成。")
    if not path.is_file() or digest_file(path) != checksum:
        raise ValueError("叠加谱产物缺失或摘要不一致。")
    with np.load(path, allow_pickle=False) as values:
        return values["mz"], values["intensity"], values["targets"], values["contributors"].tolist()


def batch_profile(path, state, sample_id, *, verify=None):
    if state["status"] in {"queued", "running"}:
        raise ValueError("请等待批次结束后查看叠加谱。")
    if sample_id is None:
        name = "spectrum.npz"
        checksum = state.get("spectrum_sha256")
    else:
        row = next((row for row in state["samples"] if row["id"] == sample_id), None)
        if row is None:
            raise ValueError("样本不属于所选批次。")
        name = f"{row['id']}-spectrum.npz"
        checksum = row.get("spectrum_sha256")
    profile = child_path(path.parent, name)
    if verify is not None:
        if verify != checksum or digest_file(profile) != checksum:
            raise ValueError("批次谱图已改变，请重新读取。")
        return None
    return (*load_profile(profile, checksum), checksum)


def describe_profile(path, state, request, sample_id):
    import pandas as pd
    import plotly.graph_objects as go
    from anndata import read_h5ad

    from scMM.plot.presentation import style_figure
    from scMM.plot.raw import _peak_preserving_downsample

    from .web_support import figure_view

    mz, intensity, targets, contributors, checksum = batch_profile(path, state, sample_id)
    retained = {}
    detected = {}
    for row in state["samples"]:
        if row["status"] != "succeeded" or (sample_id is not None and row["id"] != sample_id):
            continue
        output = child_path(path.parent, row["output"])
        if digest_file(output) != row.get("sha256"):
            raise ValueError("样本产物已改变，请检查批次。")
        data = read_h5ad(output, backed="r")
        try:
            counts = data.var.get("extraction_detected_cells")
            if counts is None:
                counts = np.zeros(data.n_vars, dtype=np.int64)
                for values, _, _ in data.chunked_X(512):
                    counts += np.asarray((values > 0).sum(axis=0)).ravel().astype(np.int64)
            for value, count in zip(data.var["mz"], counts, strict=True):
                value = float(value)
                retained[value] = retained.get(value, 0) + 1
                detected[value] = detected.get(value, 0) + int(count)
        finally:
            data.file.close()

    record = request.get("mz_list")
    masses = np.unique([*targets, *retained, *(record["mz"] if record else [])])
    in_range = np.isin(masses, targets)
    markers = np.interp(masses, mz, intensity, left=np.nan, right=np.nan)
    retained_counts = [retained.get(mass, 0) for mass in masses]
    features = pd.DataFrame(
        {
            "mz": masses,
            "status": np.select(
                [np.asarray(retained_counts) > 0, in_range],
                ["retained", "unretained" if record else "candidate"],
                default="outside",
            ),
            "retained_samples": retained_counts,
            "detected_cells": [detected.get(mass, 0) for mass in masses],
            "summed_intensity": markers,
        }
    )
    frame = pd.DataFrame({"mz": mz, "intensity": intensity})
    display = _peak_preserving_downsample(frame, 30_000, "intensity")
    figure = go.Figure()
    figure.add_scattergl(
        x=display.mz, y=display.intensity, mode="lines", name="Summed MS1 spectrum"
    )
    for status, label, color, symbol in (
        ("candidate", "Candidate peaks", "#bd7611", "circle-open"),
        ("unretained", "Targets not retained", "#bd7611", "circle-open"),
        ("retained", "Retained features", "#b63b42", "x"),
    ):
        items = features[features.status.eq(status) & features.summed_intensity.notna()]
        if not items.empty:
            figure.add_scattergl(
                x=items.mz,
                y=items.summed_intensity,
                mode="markers+text",
                name=label,
                text=[f"{mass:.4f}" for mass in items.mz],
                meta={"label_kind": "mz"},
                marker={"color": color, "symbol": symbol, "size": 7},
                hovertemplate="m/z: %{x:.8g}<br>Summed intensity: %{y:.2e}<extra>%{fullData.name}</extra>",
            )
    figure.update_layout(
        xaxis_title="m/z",
        yaxis_title="Summed intensity",
        meta={
            "batch_spectrum": {"path": str(path), "sample": sample_id, "sha256": checksum},
            "export_tables": {"features": features.to_csv(index=False)},
            "parameters": {"strategy": request["feature_strategy"], "contributors": contributors},
            "scmm_spectrum": True,
        },
    )
    names = {sample["id"]: sample["name"] for sample in request["samples"]}
    return {
        "figure": figure_view(style_figure(figure)),
        "features": [
            {
                "mz": float(mass),
                "status": status,
                "retained_samples": int(count),
                "detected_cells": int(detections),
                "summed_intensity": float(value) if np.isfinite(value) else None,
            }
            for mass, status, count, detections, value in features.itertuples(
                index=False, name=None
            )
        ],
        "contributors": [names[key] for key in contributors],
        "source": mz_lists.summary(record) if record else None,
    }
