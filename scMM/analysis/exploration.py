# ruff: noqa: RUF001
"""Explicit target correlations, replicate associations and feature intersections."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import sparse, stats

from .plot_scope import group_display_names


def matrix(data, layer=None):
    if layer is not None and layer not in data.layers:
        raise ValueError("所选数据层已失效，请重新选择。")
    value = data.X if layer is None else data.layers[layer]
    return value.toarray() if sparse.issparse(value) else np.asarray(value)


def vector(data, target, layer=None):
    if target.startswith("embedding:"):
        key, component = target[10:].rsplit(":", 1)
        component = int(component)
        if key not in data.obsm or not 0 <= component < data.obsm[key].shape[1]:
            raise ValueError("嵌入分量不存在。")
        return np.asarray(data.obsm[key])[:, component], []
    if target.startswith("obs:"):
        key = target[4:]
        if key not in data.obs or not pd.api.types.is_numeric_dtype(data.obs[key]):
            raise ValueError("请选择数值型细胞注释。")
        return pd.to_numeric(data.obs[key]).to_numpy(dtype=float, na_value=np.nan), [key]
    if not target.startswith("feature:") or target[8:] not in data.var_names:
        raise ValueError("请选择有效的稳定特征编号或数值型细胞注释。")
    return matrix(data[:, [target[8:]]], layer).ravel(), []


def correlated_features(
    data, *, target, layer=None, method="pearson", include_zeros=True, label_count=10
):
    if method not in {"pearson", "spearman", "kendall"}:
        raise ValueError("无效的相关方法。")
    if data.n_obs * data.n_vars > 50_000_000:
        raise ValueError("目标相关性输入超过 5000 万个矩阵值，请先选择细胞或特征子集。")
    x, dependencies = vector(data, target, layer)
    results = []
    for feature in data.var_names:
        if target == f"feature:{feature}":
            continue
        y = matrix(data[:, [feature]], layer).ravel()
        keep = np.isfinite(x) & np.isfinite(y)
        if not include_zeros:
            keep &= (x != 0) & (y != 0)
        a, b = x[keep], y[keep]
        coefficient = np.nan
        if len(a) >= 3 and np.ptp(a) > 0 and np.ptp(b) > 0:
            coefficient = pd.Series(a).corr(pd.Series(b), method=method)
        results.append((str(feature), coefficient, int(keep.sum())))
    table = pd.DataFrame(results, columns=["feature_id", "correlation", "n"]).sort_values(
        "correlation", kind="stable", na_position="last"
    )
    valid = table[np.isfinite(table.correlation)].copy()
    annotated = set(
        valid.assign(rank=valid.correlation.abs()).nlargest(label_count, "rank").feature_id
    )
    figure = go.Figure(
        go.Scattergl(
            x=valid.feature_id,
            y=valid.correlation,
            mode="markers+text",
            text=[f if f in annotated else "" for f in valid.feature_id],
            customdata=valid[["n"]].to_numpy(),
            hovertemplate="Feature: %{x}<br>Correlation: %{y:.5g}<br>Cells: %{customdata[0]}<extra></extra>",
        )
    )
    figure.update_layout(
        title="Target feature correlations",
        xaxis_title="Feature ID",
        yaxis_title=f"{method.capitalize()} correlation",
    )
    figure.update_layout(
        meta={
            "observation_dependencies": dependencies,
            "notes": [
                "相关性为细胞级描述；零值处理与有效细胞数逐特征记录，不代表因果或独立生物重复。"
            ],
            "export_tables": {"correlations": table.to_csv(index=False)},
        }
    )
    return figure


def association(
    data,
    *,
    x,
    y,
    layer=None,
    replicate_key=None,
    permutations=0,
    confidence=0.95,
    seed=42,
    include_zeros=True,
    method="pearson",
):
    if x == y:
        raise ValueError("请选择两个不同的变量。")
    a, dx = vector(data, x, layer)
    b, dy = vector(data, y, layer)
    keep = np.isfinite(a) & np.isfinite(b)
    if not include_zeros:
        keep &= (a != 0) & (b != 0)
    points = pd.DataFrame({"cell_id": data.obs_names[keep], "x": a[keep], "y": b[keep]})
    dependencies = dx + dy
    if replicate_key:
        if replicate_key not in data.obs or data.obs[replicate_key].isna().any():
            raise ValueError("重复单位列须存在且完整。")
        points["replicate"] = data.obs[replicate_key].astype(str).to_numpy()[keep]
        fit_points = points.groupby("replicate", sort=False)[["x", "y"]].mean()
        dependencies.append(replicate_key)
    else:
        if permutations:
            raise ValueError("置换检验须显式选择独立重复单位；先按重复平均再置换。")
        fit_points = points[["x", "y"]]
    a, b = fit_points.x.to_numpy(), fit_points.y.to_numpy()
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        raise ValueError("至少需要三个有限且非恒定的分析单位。")
    fit = stats.linregress(a, b)
    coefficient = (
        float(fit.rvalue) if method == "pearson" else pd.Series(a).corr(pd.Series(b), method=method)
    )
    grid = np.linspace(a.min(), a.max(), 200)
    predicted = fit.intercept + fit.slope * grid
    se = np.sqrt(np.sum((b - fit.intercept - fit.slope * a) ** 2) / (len(a) - 2))
    margin = (
        stats.t.ppf((1 + confidence) / 2, len(a) - 2)
        * se
        * np.sqrt(1 / len(a) + (grid - a.mean()) ** 2 / np.sum((a - a.mean()) ** 2))
    )
    p = None
    if permutations:
        budget = 500_000 if method == "kendall" else 20_000_000
        if len(a) * permutations > budget:
            raise ValueError("置换计算超过上限，请减少置换次数。")
        rng = np.random.default_rng(seed)
        if method == "kendall":
            observed = abs(coefficient)
            exceed = sum(
                abs(stats.kendalltau(a, rng.permutation(b), method="asymptotic").statistic)
                >= observed - 1e-12
                for _ in range(permutations)
            )
        else:
            av, bv = (stats.rankdata(a), stats.rankdata(b)) if method == "spearman" else (a, b)
            ac, bc = av - av.mean(), bv - bv.mean()
            denominator = np.linalg.norm(ac) * np.linalg.norm(bc)
            observed = abs(ac @ bc / denominator)
            exceed = sum(
                abs(ac @ rng.permutation(bc) / denominator) >= observed - 1e-12
                for _ in range(permutations)
            )
        p = (exceed + 1) / (permutations + 1)
    figure = go.Figure(
        go.Scatter(x=a, y=b, mode="markers", name="Replicate means" if replicate_key else "Cells")
    )
    figure.add_trace(go.Scatter(x=grid, y=predicted, mode="lines", name="OLS mean"))
    figure.add_trace(
        go.Scatter(
            x=np.r_[grid, grid[::-1]],
            y=np.r_[predicted + margin, (predicted - margin)[::-1]],
            fill="toself",
            line_width=0,
            opacity=0.2,
            name="OLS mean-response interval",
        )
    )
    lines = pd.DataFrame(
        {"x": grid, "fit": predicted, "lower": predicted - margin, "upper": predicted + margin}
    )
    summary = {
        "n": len(a),
        "method": method,
        "correlation": coefficient,
        "slope": float(fit.slope),
        "intercept": float(fit.intercept),
        "r2": float(fit.rvalue**2),
        "confidence": confidence,
        "permutation_p": p,
        "unit": replicate_key or "cell",
        "seed": seed,
    }
    figure.update_layout(
        title="Numeric association",
        xaxis_title=x,
        yaxis_title=y,
        meta={
            "observation_dependencies": dependencies,
            "notes": [
                "置信带为 OLS 均值响应区间。置换仅在用户声明的独立重复均值间进行，仍依赖重复可交换假设；细胞级拟合仅作描述。"
            ],
            "association": summary,
            "export_tables": {
                "cells": points.to_csv(index=False),
                "analysis_units": fit_points.to_csv(),
                "regression": lines.to_csv(index=False),
                "statistics": pd.DataFrame([summary]).to_csv(index=False),
            },
        },
    )
    return figure


def memberships(
    data,
    *,
    group_key,
    groups,
    layer=None,
    intensity_threshold=0.0,
    detection_rate=0.0,
    annotation_key=None,
    entity="feature",
    kind="upset",
    top=30,
):
    if group_key not in data.obs or len(groups) < 2 or len(set(groups)) != len(groups):
        raise ValueError("请选择至少两个不重复的分组。")
    labels = data.obs[group_key].astype("string")
    values = matrix(data, layer)
    result = pd.DataFrame(False, index=data.var_names, columns=groups)
    for group in groups:
        selected = labels.eq(group).fillna(False).to_numpy(dtype=bool)
        if not selected.any():
            raise ValueError(f"分组没有细胞：{group}")
        counts = np.sum(
            np.isfinite(values[selected]) & (values[selected] > intensity_threshold), axis=0
        )
        result[group] = (counts > 0) & (counts / selected.sum() >= detection_rate)
    result = result.loc[result.any(axis=1)]
    candidate_records = None
    if entity == "candidate":
        from scMM.util.lipid_annotation import annotation_store, version_valid

        store = annotation_store(data)
        version = next((v for v in store["versions"] if v["id"] == store["active"]), None)
        if version is None or not version_valid(data, version):
            raise ValueError("候选集合需要当前有效的脂质候选版本。")
        candidate_records = pd.DataFrame(version["candidates"])
        if candidate_records.empty:
            raise ValueError("当前版本没有候选。")
        candidate_records["identity"] = (
            version["database"]["sha256"] + ":" + candidate_records.database_id.astype(str)
        )
        combined = pd.DataFrame(
            False,
            index=pd.Index(candidate_records.identity.unique(), name="candidate_identity"),
            columns=groups,
        )
        for group in groups:
            present = candidate_records[
                candidate_records.feature_id.isin(result.index[result[group]])
            ]
            combined.loc[present.identity.unique(), group] = True
        result = combined.loc[combined.any(axis=1)]
    elif entity != "feature":
        raise ValueError("集合对象须为特征或候选身份。")
    # Names remain labels on stable features. Never treat names as chemical identity.
    if candidate_records is not None:
        names = (
            candidate_records.drop_duplicates("identity")
            .set_index("identity")["name"]
            .reindex(result.index)
        )
    elif annotation_key:
        if annotation_key not in data.var:
            raise ValueError("注释字段不存在。")
        names = data.var[annotation_key].reindex(result.index).fillna("").astype(str)
    else:
        names = pd.Series(result.index, index=result.index)
    if result.empty:
        raise ValueError("所选阈值下没有检出的集合成员，请调整阈值。")
    display_names = group_display_names(data, group_key, groups)
    keys = (
        {g: f"group:{g}" for g in groups}
        if set(groups) & {"label", "count", "intersection"}
        else {g: g for g in groups}
    )
    table = result.rename(columns=keys)
    table.insert(0, "label", names)
    patterns = result.rename(columns=keys).value_counts(sort=True).rename("count").reset_index()
    patterns["intersection"] = [
        " & ".join(display_names[group] for group in groups if row[keys[group]])
        for _, row in patterns.iterrows()
    ]
    figure = go.Figure()
    if kind == "venn":
        if len(groups) > 3:
            raise ValueError("Venn 仅支持 2 或 3 组；更多分组请选择 UpSet。")
        # Exact exclusive regions are also exported; overlaps are not area-scaled.
        centers = (
            [(-0.5, 0), (0.5, 0)] if len(groups) == 2 else [(-0.5, 0.3), (0.5, 0.3), (0, -0.5)]
        )
        for group, (cx, cy) in zip(groups, centers, strict=True):
            figure.add_shape(
                type="circle",
                x0=cx - 1,
                x1=cx + 1,
                y0=cy - 1,
                y1=cy + 1,
                opacity=0.25,
                fillcolor=["#2563eb", "#ef4444", "#10b981"][groups.index(group)],
            )
            figure.add_annotation(x=cx, y=cy + 1, text=display_names[group], showarrow=False)
        for _, row in patterns.iterrows():
            members = [centers[i] for i, g in enumerate(groups) if row[keys[g]]]
            non = [centers[i] for i, g in enumerate(groups) if not row[keys[g]]]
            pos = np.mean(members, axis=0) - (0.5 * np.mean(non, axis=0) if non else 0)
            figure.add_annotation(x=pos[0], y=pos[1], text=str(row["count"]), showarrow=False)
        figure.update_xaxes(range=[-2, 2], visible=False)
        figure.update_yaxes(range=[-2, 2], visible=False, scaleanchor="x")
    else:
        shown = patterns.head(top)
        columns = np.arange(len(shown))
        figure = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            row_heights=[0.68, 0.32],
            vertical_spacing=0.025,
        )
        figure.add_bar(
            x=columns,
            y=shown["count"],
            name="Exclusive intersection",
            customdata=shown.intersection,
            marker_color="#2774a6",
            showlegend=False,
            hovertemplate="%{customdata}<br>Count: %{y}<extra></extra>",
            row=1,
            col=1,
        )
        line_x = []
        line_y = []
        for i, (_, pattern) in enumerate(shown.iterrows()):
            enabled = [j for j, group in enumerate(groups) if pattern[keys[group]]]
            line_x.extend((i, i, None))
            line_y.extend((enabled[0], enabled[-1], None))
        figure.add_scatter(
            x=line_x,
            y=line_y,
            mode="lines",
            line_color="#111827",
            showlegend=False,
            hoverinfo="skip",
            row=2,
            col=1,
        )
        for i, group in enumerate(groups):
            figure.add_trace(
                go.Scatter(
                    x=columns,
                    y=[i] * len(shown),
                    mode="markers",
                    marker={
                        "color": ["#111827" if v else "#d1d5db" for v in shown[keys[group]]],
                        "size": 7,
                    },
                    name=display_names[group],
                    showlegend=False,
                    hoverinfo="name",
                ),
                row=2,
                col=1,
            )
        figure.update_xaxes(showticklabels=False)
        figure.update_yaxes(title_text="Count", row=1, col=1)
        figure.update_yaxes(
            tickvals=list(range(len(groups))),
            ticktext=[display_names[g] for g in groups],
            range=[len(groups) - 0.5, -0.5],
            row=2,
            col=1,
        )
    exclusive = result.sum(axis=1).eq(1)
    figure.update_layout(
        title="Candidate set intersections"
        if entity == "candidate"
        else "Feature set intersections",
        meta={
            "observation_dependencies": [group_key],
            "set_counts": {
                "union": len(result),
                "intersection": int(result.all(axis=1).sum()),
                "groups": [
                    {
                        "id": g,
                        "name": display_names[g],
                        "total": int(result[g].sum()),
                        "unique": int((result[g] & exclusive).sum()),
                    }
                    for g in groups
                ],
            },
            "notes": [
                "按稳定特征 ID 计数；注释仅作标签，不按同名合并候选物质。Venn 圆面积不代表数量。"
            ],
            "export_tables": {
                "membership": table.to_csv(),
                "intersections": patterns.to_csv(index=False),
            },
        },
    )
    if candidate_records is not None:
        figure.layout.meta["export_tables"]["candidate_sources"] = candidate_records.to_csv(
            index=False
        )
        figure.layout.meta["notes"] = [
            "按数据库版本和数据库记录 ID 统计候选集合；同一记录可由多个特征支持，保留完整映射，不代表已鉴定物质或合并强度。"
        ]
    return figure
