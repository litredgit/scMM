"""Interactive views of stored analysis results; no statistical recomputation."""
# ruff: noqa: RUF001

import math

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from scMM.application.workbench import dense

from .presentation import feature_label, mass_label, probability_number, style_figure


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
        x="log2_fold_change",
        y="minus_log10_fdr",
        text="label",
        custom_data=["feature_id"],
        hover_name="display_mz",
        hover_data={
            "mean_a": ":.3e",
            "mean_b": ":.3e",
            "display_p_value": True,
            "display_fdr": True,
        },
        labels={"display_p_value": "p_value", "display_fdr": "fdr"},
        title="火山图：全部特征的全局 BH-FDR",
    )
    figure.update_traces(textposition="top center")
    figure.add_vline(x=fold_change, line_dash="dot")
    figure.add_vline(x=-fold_change, line_dash="dot")
    if fdr > 0:
        figure.add_hline(y=-np.log10(fdr), line_dash="dot")
    return style_figure(figure)


def violin_figure(data, result, features, *, hide_zero=False, columns=3):
    if not features:
        return go.Figure(layout={"title": "选择特征后显示小提琴图"})
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
            f"{feature_label(feature, table.loc[feature].get('mz'))}<br>全局 FDR={probability_number(table.loc[feature, 'fdr'])}"
            for feature in features
        ],
    )
    for column, feature in enumerate(features, 1):
        index = data.var_names.get_loc(feature)
        for name, color in [(result["group_a"], "#0F766E"), (result["group_b"], "#C2410C")]:
            mask = groups.notna() & (groups.astype(str) == name)
            selected = values[mask.to_numpy(), index]
            if hide_zero:
                selected = selected[selected != 0]
            figure.add_trace(
                go.Violin(
                    y=selected,
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
    figure.update_yaxes(tickformat=".3e", title_text="Intensity")
    figure.update_layout(
        height=340 * rows,
        title="小提琴图（零值仅从显示中隐藏；检验与全局 FDR 不变）"
        if hide_zero
        else "小提琴图（包含零值；使用同一份全局 FDR）",
    )
    return style_figure(figure)


def embedding_figure(data, key, color=None):
    coordinates = np.asarray(data.obsm[key])
    frame = pd.DataFrame(
        {
            "x": coordinates[:, 0],
            "y": coordinates[:, 1] if coordinates.shape[1] > 1 else 0.0,
            "cell": data.obs_names,
        }
    )
    color_key = None
    if color and color.startswith("obs:"):
        frame["color"] = data.obs[color[4:]].to_numpy()
        color_key = "color"
    elif color and color.startswith("feature:"):
        frame["color"] = dense(data[:, [color[8:]]].X)[:, 0]
        color_key = "color"
    figure = px.scatter(
        frame, x="x", y="y", color=color_key, hover_name="cell", title=key, render_mode="webgl"
    )
    if color and color.startswith("feature:"):
        figure.update_coloraxes(colorbar_tickformat=".3e", colorbar_title="Intensity")
        figure.update_traces(
            hovertemplate="Cell %{hovertext}<br>x=%{x}<br>y=%{y}<br>Intensity %{marker.color:.3e}<extra></extra>"
        )
    elif color:
        scientific = any(word in color.lower() for word in ("intensity", "abundance", "强度"))
        figure.update_coloraxes(colorbar_tickformat=".3e" if scientific else ".3~f")
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
    roc.update_layout(title="Holdout ROC", xaxis_title="FPR", yaxis_title="TPR")
    pr.update_layout(
        title="Holdout Precision–Recall", xaxis_title="Recall", yaxis_title="Precision"
    )
    calibration.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="理想校准")
    calibration.update_layout(
        title="Holdout 校准诊断（不重新拟合）", xaxis_title="预测概率", yaxis_title="实际阳性比例"
    )
    return roc, pr, calibration


def network_figure(graph):
    """Deterministic layout with signed edges and isolated nodes retained."""
    import networkx as nx

    positions = nx.spring_layout(graph, seed=42)
    figure = go.Figure()
    for positive, color, label in ((True, "#d95f02", "正相关"), (False, "#1b9e77", "负相关")):
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
            name="特征",
            hovertemplate="%{text}<extra></extra>",
        )
    )
    figure.update_layout(title="特征相关网络（不代表因果或轨迹）", showlegend=True)
    return figure
