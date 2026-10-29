"""Interactive views of stored analysis results; no statistical recomputation."""
# ruff: noqa: RUF001

import math

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from scMM.application.workbench import dense

from .presentation import PLOT_COLORS, feature_label, mass_label, probability_number, style_figure


def volcano_figure(table, *, fdr=0.05, fold_change=1.0, labels=10, order="fdr"):
    frame = table.copy()
    frame["minus_log10_fdr"] = -np.log10(np.clip(frame.fdr.to_numpy(), 1e-300, 1))
    frame["effect"] = frame.log2_fold_change.abs()
    frame["intensity"] = (frame.mean_a + frame.mean_b) / 2
    selected = frame[(frame.fdr <= fdr) & (frame.effect >= fold_change)]
    selected = selected.sort_values(
        [order, "effect"], ascending=[order in {"fdr", "p_value"}, False]
    ).head(labels)
    frame["display_mz"] = [
        feature_label(row.feature_id, row.get("mz")) for _, row in frame.iterrows()
    ]
    frame["label"] = frame["display_mz"].where(frame.index.isin(selected.index), "")
    frame["display_p_value"] = frame.p_value.map(probability_number)
    frame["display_fdr"] = frame.fdr.map(probability_number)
    figure = px.scatter(
        frame,
        color_discrete_sequence=PLOT_COLORS,
        x="log2_fold_change",
        y="minus_log10_fdr",
        text="label",
        custom_data=["feature_id"],
        hover_name="display_mz",
        hover_data={
            "mean_a": ":.1e",
            "mean_b": ":.1e",
            "display_p_value": True,
            "display_fdr": True,
        },
        labels={"display_p_value": "p_value", "display_fdr": "fdr"},
        title="Volcano plot: global BH-FDR across all features",
    )
    figure.update_traces(textposition="top center")
    figure.add_vline(x=fold_change, line_dash="dot")
    figure.add_vline(x=-fold_change, line_dash="dot")
    if fdr > 0:
        figure.add_hline(y=-np.log10(fdr), line_dash="dot")
    return style_figure(figure)


def violin_figure(data, result, features, *, hide_zero=False, columns=3):
    if not features:
        return go.Figure(layout={"title": "Select features to display a violin plot"})
    if len(features) > 12:
        raise ValueError("Select at most 12 features for the violin plot")
    table = result["table"].set_index("feature_id")
    groups = data.obs[result["group_key"]]
    values = dense(data.layers[result["layer"]] if result["layer"] else data.X)
    columns = min(columns, len(features))
    rows = math.ceil(len(features) / columns)
    figure = make_subplots(
        rows=rows,
        cols=columns,
        subplot_titles=[
            f"{feature_label(feature, table.loc[feature].get('mz'))}<br>Global FDR={probability_number(table.loc[feature, 'fdr'])}"
            for feature in features
        ],
    )
    for column, feature in enumerate(features, 1):
        index = data.var_names.get_loc(feature)
        for name, color in [(result["group_a"], "#0F766E"), (result["group_b"], "#C2410C")]:
            mask = groups.notna() & (groups.astype(str) == name)
            selected = values[mask.to_numpy(), index]
            cells = np.asarray(data.obs_names)[mask.to_numpy()]
            if hide_zero:
                cells = cells[selected != 0]
                selected = selected[selected != 0]
            figure.add_trace(
                go.Violin(
                    y=selected,
                    customdata=cells[:, None],
                    points="all",
                    jitter=0.25,
                    pointpos=0,
                    hovertemplate="Cell=%{customdata[0]}<br>Intensity=%{y:.1e}<extra>%{fullData.name}</extra>",
                    name=name,
                    legendgroup=name,
                    showlegend=column == 1,
                    box_visible=True,
                    meanline_visible=True,
                    line_color=color,
                ),
                row=(column - 1) // columns + 1,
                col=(column - 1) % columns + 1,
            )
    figure.update_yaxes(tickformat=".1e", title_text="Intensity")
    figure.update_layout(
        meta={"point_kind": "cell"},
        height=340 * rows,
        title="Violin plot (zeros hidden for display; tests and global FDR unchanged)"
        if hide_zero
        else "Violin plot (zeros included; same global FDR)",
    )
    return style_figure(figure)


def embedding_figure(data, key, color=None, dimensions=None):
    if key not in data.obsm:
        raise ValueError("所选坐标不存在，请先运行降维。")
    coordinates = np.asarray(data.obsm[key])
    dimensions = dimensions or ([1, 2] if coordinates.shape[1] > 1 else [1, 0])
    if dimensions[0] == 0:
        raise ValueError("横轴需要有效坐标维度。")
    if len(dimensions) not in {2, 3} or len(set(dimensions)) != len(dimensions):
        raise ValueError("请选择两个或三个不同的坐标维度。")
    if any(
        d < 1 or d > coordinates.shape[1]
        for d in dimensions
        if not (d == 0 and coordinates.shape[1] == 1)
    ):
        raise ValueError("所选维度超出已计算的坐标范围。")
    frame = pd.DataFrame(
        {
            "x": coordinates[:, dimensions[0] - 1],
            "y": coordinates[:, dimensions[1] - 1] if dimensions[1] else 0.0,
            "cell": data.obs_names,
        }
    )
    if len(dimensions) == 3:
        frame["z"] = coordinates[:, dimensions[2] - 1]
    color_key = None
    if color and color.startswith("obs:"):
        frame["color"] = data.obs[color[4:]].to_numpy()
        color_key = "color"
    elif color and color.startswith("feature:"):
        frame["color"] = dense(data[:, [color[8:]]].X)[:, 0]
        color_key = "color"
    variance = list(data.uns.get(f"{key}_params", {}).get("explained_variance_ratio", []))
    labels = {}
    for axis, dimension in zip(("x", "y", "z"), dimensions, strict=False):
        labels[axis] = (
            "Constant axis"
            if dimension == 0
            else f"PC{dimension} ({variance[dimension - 1]:.2%})"
            if variance
            else f"Dimension {dimension}"
        )
    kwargs = {
        "color_discrete_sequence": PLOT_COLORS,
        "x": "x",
        "y": "y",
        "color": color_key,
        "hover_name": "cell",
        "custom_data": ["cell"],
        "title": key,
        "labels": labels,
    }
    figure = (
        px.scatter_3d(frame, z="z", **kwargs)
        if len(dimensions) == 3
        else px.scatter(frame, render_mode="webgl", **kwargs)
    )
    table = pd.DataFrame(
        coordinates,
        index=data.obs_names,
        columns=[f"component_{i + 1}" for i in range(coordinates.shape[1])],
    )
    table.index.name = "cell_id"
    table = table.join(data.obs, rsuffix="_metadata")
    figure.update_layout(
        meta={
            "point_kind": "cell",
            "embedding": key,
            "dimensions": dimensions,
            "explained_variance_ratio": variance,
            "export_tables": {"coordinates": table.to_csv()},
        }
    )
    if color and color.startswith("feature:"):
        figure.update_coloraxes(colorbar_tickformat=".1e", colorbar_title="Intensity")
        figure.update_traces(
            hovertemplate="Cell %{hovertext}<br>x=%{x}<br>y=%{y}<br>Intensity %{marker.color:.1e}<extra></extra>"
        )
    elif color:
        scientific = any(word in color.lower() for word in ("intensity", "abundance", "强度"))
        figure.update_coloraxes(colorbar_tickformat=".1e" if scientific else ".3~f")
    return style_figure(figure)


def supervised_figures(analyzer):
    roc, pr, calibration = go.Figure(), go.Figure(), go.Figure()
    for name, curve in analyzer.roc_curves().items():
        roc.add_scatter(
            x=curve["fpr"], y=curve["tpr"], mode="lines", name=f"{name} AUC={curve['auc']:.3g}"
        )
    for name, curve in analyzer.precision_recall_curves().items():
        pr.add_scatter(
            x=curve["recall"],
            y=curve["precision"],
            mode="lines",
            name=f"{name} AP={curve['average_precision']:.3g}",
        )
    for name, curve in analyzer.calibration_curves().items():
        calibration.add_scatter(
            x=curve["mean_predicted_probability"],
            y=curve["fraction_of_positives"],
            mode="lines+markers",
            name=name,
        )
    roc.update_layout(
        title="Held-out ROC",
        xaxis_title="False positive rate (FPR)",
        yaxis_title="True positive rate (TPR)",
    )
    pr.update_layout(
        title="Held-out precision-recall", xaxis_title="Recall", yaxis_title="Precision"
    )
    calibration.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="Ideal calibration")
    calibration.update_layout(
        title="Held-out calibration (without refitting)",
        xaxis_title="Predicted probability",
        yaxis_title="Observed positive fraction",
    )
    return roc, pr, calibration


def network_figure(graph):
    """Deterministic layout with signed edges and isolated nodes retained."""
    import networkx as nx

    positions = nx.spring_layout(graph, seed=42)
    figure = go.Figure()
    for positive, color, label in (
        (True, "#d95f02", "Positive correlation"),
        (False, "#1b9e77", "Negative correlation"),
    ):
        x, y = [], []
        for a, b, attrs in graph.edges(data=True):
            if (attrs["correlation"] >= 0) == positive:
                x.extend([positions[a][0], positions[b][0], None])
                y.extend([positions[a][1], positions[b][1], None])
        figure.add_trace(go.Scatter(x=x, y=y, mode="lines", line={"color": color}, name=label))
    figure.add_trace(
        go.Scatter(
            x=[positions[n][0] for n in graph],
            y=[positions[n][1] for n in graph],
            text=[mass_label(node) for node in graph],
            mode="markers",
            name="Features",
            hovertemplate="%{text}<extra></extra>",
        )
    )
    figure.update_layout(
        title="Feature correlation network (not causality or trajectory)",
        showlegend=True,
        meta={
            "layout_seed": 42,
            "export_tables": {
                "nodes": pd.DataFrame(
                    [{"feature_id": n, "x": p[0], "y": p[1]} for n, p in positions.items()]
                ).to_csv(index=False),
                "edges": pd.DataFrame(
                    [{"source": a, "target": b, **attrs} for a, b, attrs in graph.edges(data=True)]
                ).to_csv(index=False),
            },
        },
    )
    return figure
