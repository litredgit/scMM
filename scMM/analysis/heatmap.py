"""Display-only heatmaps with explicit aggregation and complete replot matrices."""
# ruff: noqa: RUF001

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import sparse
from scipy.cluster.hierarchy import leaves_list, linkage


def heatmap_figure(
    data,
    *,
    features,
    layer=None,
    group_key=None,
    sample_key=None,
    equal_samples=False,
    zscore=True,
    cluster_rows=True,
    cluster_columns=True,
):
    if (
        not features
        or len(set(features)) != len(features)
        or any(v not in data.var_names for v in features)
    ):
        raise ValueError("请选择不重复的有效特征。")
    if len(features) > 1000:
        raise ValueError("热图最多选择 1000 个特征。")
    block = data[:, features]
    matrix = block.X if layer is None else block.layers[layer]
    matrix = matrix.toarray() if sparse.issparse(matrix) else np.asarray(matrix)
    if not np.isfinite(matrix).all():
        raise ValueError("热图需要有限数值。")
    source = pd.DataFrame(matrix.T, index=features, columns=data.obs_names)
    aggregate = source.copy()
    if group_key:
        if data.obs[group_key].isna().any():
            raise ValueError("热图分组不能含缺失值。")
        frame = source.T
        groups = data.obs[group_key]
        if equal_samples:
            if not sample_key or data.obs[sample_key].isna().any():
                raise ValueError("样本等权平均需要完整样本列。")
            aggregate = (
                frame.groupby([groups, data.obs[sample_key]], observed=True)
                .mean()
                .groupby(level=0)
                .mean()
                .T
                if sample_key != group_key
                else frame.groupby(groups, observed=True).mean().T
            )
        else:
            aggregate = frame.groupby(groups, observed=True).mean().T
    if aggregate.size > 2_000_000:
        raise ValueError("热图超过 200 万个色块，请选择分组均值或减少特征。")
    if (cluster_columns and aggregate.shape[1] > 5000) or (
        cluster_rows and aggregate.shape[0] > 5000
    ):
        raise ValueError("聚类轴超过 5000 项，请聚合分组或关闭该轴聚类。")
    display = aggregate.to_numpy(dtype=float)
    if zscore:
        deviation = display.std(axis=1, keepdims=True)
        display = (display - display.mean(axis=1, keepdims=True)) / np.where(
            deviation > 0, deviation, 1
        )

    def order(values, enabled):
        if not enabled or len(values) < 2 or not np.any(np.ptp(values, axis=0)):
            return np.arange(len(values))
        return leaves_list(
            linkage(values, method="average", metric="euclidean", optimal_ordering=True)
        )

    rows, columns = order(display, cluster_rows), order(display.T, cluster_columns)
    shown = pd.DataFrame(display, index=aggregate.index, columns=aggregate.columns).iloc[
        rows, columns
    ]
    figure = go.Figure(
        go.Heatmap(
            z=shown.to_numpy(),
            x=shown.columns.astype(str),
            y=shown.index.astype(str),
            colorscale="RdBu",
            reversescale=True,
            zmid=0 if zscore else None,
            hovertemplate="特征=%{y}<br>列=%{x}<br>值=%{z:.3g}<extra></extra>"
            if zscore
            else "特征=%{y}<br>列=%{x}<br>强度=%{z:.1e}<extra></extra>",
            colorbar={
                "title": "行标准分" if zscore else "强度",
                "tickformat": ".2g" if zscore else ".1e",
            },
        )
    )
    # Two categorical annotation strips above the matrix; export their exact mapping.
    annotation_rows = []
    palette = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]
    for field in [
        key
        for key in ("group", "sample")
        if key in data.obs and (not group_key or key == group_key)
    ][:2]:
        labels = (
            [str(column) for column in shown.columns]
            if group_key
            else data.obs.loc[shown.columns, field].astype(str).tolist()
        )
        categories = list(dict.fromkeys(labels))
        codes = [categories.index(label) for label in labels]
        figure.add_trace(
            go.Heatmap(
                z=[codes],
                x=shown.columns.astype(str),
                y=[field],
                text=[labels],
                hovertemplate="%{y}: %{text}<extra></extra>",
                colorscale=[
                    [i / max(1, len(categories) - 1), palette[i % len(palette)]]
                    for i in range(max(2, len(categories)))
                ],
                showscale=False,
                yaxis=f"y{len(annotation_rows) + 2}",
            )
        )
        axis = f"yaxis{len(annotation_rows) + 2}"
        bottom = 0.92 + len(annotation_rows) * 0.04
        figure.update_layout(
            **{
                axis: {
                    "domain": [bottom, bottom + 0.03],
                    "anchor": "x",
                    "showticklabels": True,
                    "showgrid": False,
                }
            }
        )
        annotation_rows.append(
            {
                "field": field,
                "categories": categories,
                "codes": codes,
                "column_order": shown.columns.astype(str).tolist(),
            }
        )
    if annotation_rows:
        figure.update_yaxes(domain=[0, 0.88], selector={"anchor": None})
    figure.update_layout(yaxis={"domain": [0, 0.88] if annotation_rows else [0, 1]})
    annotation = data.obs.copy()
    figure.update_layout(
        title="特征热图",
        xaxis_title="分组" if group_key else "细胞",
        yaxis_title="特征",
        meta={
            "parameters": {
                "features": features,
                "layer": layer,
                "group_key": group_key,
                "sample_key": sample_key,
                "equal_samples": equal_samples,
                "zscore": zscore,
                "cluster_rows": cluster_rows,
                "cluster_columns": cluster_columns,
            },
            "annotation_strips": annotation_rows,
            "row_order": shown.index.tolist(),
            "column_order": shown.columns.astype(str).tolist(),
            "export_tables": {
                "source.csv": source.to_csv(),
                "aggregate.csv": aggregate.to_csv(),
                "display.csv": shown.to_csv(),
                "annotations.csv": annotation.to_csv(),
            },
        },
    )
    return figure
