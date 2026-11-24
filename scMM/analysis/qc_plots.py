"""Distribution and sample-correlation plots for quantitative quality control."""
# ruff: noqa: RUF001

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import sparse

from scMM.plot.colors import PALETTES
from scMM.plot.presentation import style_figure

from .exploration import vector
from .plot_scope import group_display_names


def _labels(data, key):
    if key not in data.obs:
        raise ValueError("请选择当前矩阵中的分组列。")
    labels = data.obs[key].astype("string").str.strip().replace("", pd.NA)
    if labels.isna().all():
        raise ValueError("所选分组列没有可用标签。")
    return labels


def distribution_figure(
    data,
    *,
    metric,
    layer=None,
    group_key,
    bins=40,
    relative=True,
    palette="scMM",
):
    groups = _labels(data, group_key)
    if metric in {"detected_features", "total_intensity"}:
        selected = data.X if layer is None else data.layers[layer]
        if metric == "detected_features":
            values = np.asarray((selected > 0).sum(axis=1)).ravel()
            title = "Detected features per observation"
        else:
            values = np.asarray(selected.sum(axis=1)).ravel()
            title = "Total intensity per observation"
    else:
        values, _ = vector(data, metric, layer)
        title = f"Intensity · {metric[8:]}" if metric.startswith("feature:") else metric[4:]
    keep = np.isfinite(values) & groups.notna().to_numpy()
    if not keep.any():
        raise ValueError("所选指标与分组没有共同有效数据。")
    table = pd.DataFrame(
        {"observation_id": data.obs_names, "group_id": groups, "value": values},
        index=data.obs_names,
    ).loc[keep]
    order = table.group_id.unique().tolist()
    if len(order) > 100:
        raise ValueError("分组超过 100 项，请选择样本或批次等分类列。")
    names = group_display_names(data, group_key, order)
    table["group"] = table.group_id.map(names)
    edges = np.histogram_bin_edges(table.value.to_numpy(), bins=bins)
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.29, 0.71],
        vertical_spacing=0.04,
    )
    histograms = []
    colors = PALETTES[palette]
    for i, key in enumerate(order):
        v = table.loc[table.group_id.eq(key), "value"].to_numpy()
        label = f"{names[key]} (n={len(v)})"
        counts, _ = np.histogram(v, bins=edges)
        figure.add_trace(
            go.Box(
                x=v,
                name=label,
                legendgroup=key,
                marker_color=colors[i % len(colors)],
                boxpoints="outliers",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Bar(
                x=edges[:-1] + np.diff(edges) / 2,
                width=np.diff(edges),
                y=counts / len(v) if relative else counts,
                name=label,
                legendgroup=key,
                marker_color=colors[i % len(colors)],
                opacity=0.57,
                customdata=counts,
                hovertemplate="%{x:.5g}<br>Count: %{customdata}<extra>%{fullData.name}</extra>",
            ),
            row=2,
            col=1,
        )
        histograms.append(
            pd.DataFrame(
                {
                    "group_id": key,
                    "group": names[key],
                    "left": edges[:-1],
                    "right": edges[1:],
                    "count": counts,
                    "fraction": counts / len(v),
                }
            )
        )
    figure.update_xaxes(title_text=title, row=2, col=1)
    figure.update_yaxes(title_text="Fraction" if relative else "Count", row=2, col=1)
    figure.update_layout(
        title="QC distributions by sample or batch",
        barmode="overlay",
        meta={
            "export_tables": {
                "observations": table.to_csv(index=False),
                "histograms": pd.concat(histograms, ignore_index=True).to_csv(index=False),
            },
            "omitted": int((~keep).sum()),
        },
    )
    style_figure(figure)
    if relative:
        figure.update_yaxes(tickformat=".0%", row=2, col=1)
    return figure


def sample_correlation_figure(
    data,
    *,
    sample_key,
    layer=None,
    aggregate="mean",
    colorscale="RdBu",
    square=False,
):
    groups = _labels(data, sample_key)
    order = groups.dropna().unique().tolist()
    if len(order) < 2 or data.n_vars < 3:
        raise ValueError("样本相关性热图至少需要两个样本和三个特征。")
    if len(order) > 500:
        raise ValueError("样本相关性热图最多支持 500 个样本。")
    names = group_display_names(data, sample_key, order)
    matrix_values = data.X if layer is None else data.layers[layer]
    rows = []
    metadata = []
    for key in order:
        select = groups.eq(key).fillna(False).to_numpy(dtype=bool)
        block = matrix_values[select]
        if aggregate == "mean" and sparse.issparse(block) and np.isfinite(block.data).all():
            row = np.asarray(block.mean(axis=0)).ravel()
        else:
            block = block.toarray() if sparse.issparse(block) else np.asarray(block)
            frame = pd.DataFrame(np.where(np.isfinite(block), block, np.nan))
            row = (frame.mean() if aggregate == "mean" else frame.median()).to_numpy()
        rows.append(row)
        item = {"sample_id": key, "sample": names[key], "observations": int(select.sum())}
        for column in ("group", "batch"):
            if column in data.obs:
                labels = data.obs.loc[select, column].dropna().astype(str).str.strip()
                item[column] = ", ".join(dict.fromkeys(value for value in labels if value))
        metadata.append(item)
    means = pd.DataFrame(rows, index=order, columns=data.var_names)
    correlation = means.T.corr(method="pearson", min_periods=3)
    display = correlation**2 if square else correlation
    values = display.to_numpy()
    descriptions = [
        f"{item['sample']}<br>Batch: {item.get('batch') or '—'}<br>Group: {item.get('group') or '—'}"
        for item in metadata
    ]
    hover = [[f"{a}<br>{b}" for b in descriptions] for a in descriptions]
    # Categorical positions use IDs so identical display labels cannot merge samples.
    labels = [names[key] for key in order]
    figure = go.Figure(
        go.Heatmap(
            z=values,
            x=order,
            y=order,
            zmin=0 if square else -1,
            zmax=1,
            colorscale=colorscale,
            reversescale=colorscale in {"RdBu", "PuOr"},
            text=np.round(values, 3) if len(order) <= 20 else None,
            texttemplate="%{text}" if len(order) <= 20 else None,
            customdata=hover,
            colorbar={"title": "Pearson R²" if square else "Pearson r"},
            hovertemplate="%{customdata}<br>Correlation: %{z:.5g}<extra></extra>",
        )
    )
    figure.update_xaxes(tickvals=order, ticktext=labels, title_text="Sample")
    figure.update_yaxes(
        tickvals=order,
        ticktext=labels,
        title_text="Sample",
        autorange="reversed",
    )
    figure.update_layout(
        title="Sample correlation heatmap",
        meta={
            "export_tables": {
                "aggregated_intensities": means.to_csv(),
                "pearson_r": correlation.to_csv(),
                "displayed_correlations": display.to_csv(),
                "samples": pd.DataFrame(metadata).to_csv(index=False),
            },
            "omitted": int(groups.isna().sum()),
        },
    )
    return style_figure(figure)
