"""Local mass-spectrum evidence using exactly the cells used for each isotope ratio."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from scMM.util.lipid_annotation import dataset_inputs


def isotope_spectrum(data, version, relation_id):
    relation = next((r for r in version["relations"] if r["relation_id"] == relation_id), None)
    if relation is None:
        raise ValueError("同位素关系不存在。")
    ids, mz, values, samples, layer, _ = dataset_inputs(data, version["intensity_layer"])
    indices = {str(name): i for i, name in enumerate(ids)}
    parent, child = indices[relation["parent_feature_id"]], indices[relation["isotope_feature_id"]]
    valid = (
        (samples == relation["sample"])
        & np.isfinite(values[:, parent])
        & np.isfinite(values[:, child])
        & (values[:, parent] > 0)
        & (values[:, child] >= 0)
    )
    if not valid.any():
        raise ValueError("此样本没有该关系的有效细胞。")
    lower = min(relation["parent_mz"], relation["isotope_mz"]) - 0.15
    upper = max(relation["parent_mz"], relation["isotope_mz"]) + 0.15
    selected = (mz >= lower) & (mz <= upper)
    intensity = values[valid].mean(axis=0)[selected]
    frame = pd.DataFrame(
        {"feature_id": np.asarray(ids)[selected], "mz": mz[selected], "intensity": intensity}
    ).sort_values("mz")
    x = np.column_stack([frame.mz, frame.mz, np.full(len(frame), np.nan)]).ravel()
    y = np.column_stack(
        [np.zeros(len(frame)), frame.intensity, np.full(len(frame), np.nan)]
    ).ravel()
    figure = go.Figure(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name="Mean feature spectrum of valid cells",
            line={"color": "#333333"},
        )
    )
    predicted = float(relation["predicted_mz"])
    theoretical = float(values[valid, parent].mean()) * float(relation["theoretical_ratio"])
    figure.add_scatter(
        x=[predicted, predicted],
        y=[0, theoretical],
        mode="lines",
        name="Theoretical isotope peaks (scaled to parent)",
        line={"color": "#CC79A7", "dash": "dash"},
    )
    colors = {
        "accepted": ("#0072B2", "Manually accepted", "solid"),
        "rejected": ("#777777", "Manually rejected", "dot"),
        "matched": ("#009E73", "Automatically matched", "solid"),
        "pending": ("#E69F00", "Pending review", "dash"),
    }
    status = (
        relation["review"]
        if relation["review"] in {"accepted", "rejected"}
        else "matched"
        if relation["matched"]
        else "pending"
    )
    color, label, dash = colors[status]
    top = max(float(np.max(intensity)), theoretical) * 1.08
    for mass in (relation["parent_mz"], relation["isotope_mz"]):
        width = max(mass * version["parameters"]["isotope_ppm"] * 1e-6, 0.003)
        figure.add_shape(
            type="rect",
            x0=mass - width,
            x1=mass + width,
            y0=0,
            y1=top,
            line={"color": color, "width": 2, "dash": dash},
            fillcolor="rgba(0,0,0,0)",
        )
    for c, status_label, d in colors.values():
        figure.add_scatter(
            x=[None], y=[None], mode="lines", line={"color": c, "dash": d}, name=status_label
        )
    figure.update_traces(
        hovertemplate="m/z=%{x:.5f}<br>Intensity=%{y:.1e}<extra>%{fullData.name}</extra>"
    )
    figure.update_layout(
        title=f"Natural isotope spectrum · {label}",
        xaxis_title="m/z",
        yaxis={"title": "Mean intensity", "tickformat": ".1e"},
        meta={
            "source": "matrix_feature_stems_not_raw_profile",
            "layer": layer,
            "valid_cells": data.obs_names[valid].tolist(),
            "relation": relation,
            "export_tables": {
                "local_spectrum": frame.to_csv(index=False),
                "theoretical_peak": pd.DataFrame(
                    {"mz": [predicted], "intensity": [theoretical]}
                ).to_csv(index=False),
            },
            "parameters": version["parameters"],
        },
    )
    return figure
