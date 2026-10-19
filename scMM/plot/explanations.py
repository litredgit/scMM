"""Complete SHAP diagnostics with class/cell selectors and numeric exports."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def shap_figure(result, kind="shap_plot", *, class_index=0, cell_index=0, feature=None, top=20):
    values = np.asarray(result["values"])
    base = np.asarray(result["base_values"])
    data = np.asarray(result["data"])
    names = result["feature_names"]
    classes = result["classes"]
    if values.ndim == 3:
        if class_index >= values.shape[2]:
            raise ValueError("类别超出 SHAP 解释范围。")
        selected = values[:, :, class_index]
        baselines = (
            base[:, class_index] if base.ndim == 2 else np.repeat(base[class_index], len(values))
        )
    else:
        # Binary linear SHAP explains the positive class only.
        if class_index not in (0, 1) or len(classes) != 2:
            raise ValueError("SHAP 类别无效。")
        selected = values if class_index == 1 else -values
        baselines = base if class_index == 1 else -base
        if np.ndim(baselines) == 0:
            baselines = np.repeat(baselines, len(values))
    if cell_index >= len(selected):
        raise ValueError("细胞超出已解释范围。")
    importance = np.abs(selected).mean(axis=0)
    indices = np.argsort(-importance, kind="stable")[:top]
    figure = go.Figure()
    if kind == "shap_plot":
        figure.add_bar(
            x=importance[indices][::-1], y=np.asarray(names)[indices][::-1], orientation="h"
        )
        figure.update_layout(xaxis_title="平均绝对 SHAP", yaxis_title="特征")
    elif kind == "shap_beeswarm":
        rng = np.random.default_rng(42)
        for position, index in enumerate(indices[::-1]):
            figure.add_scatter(
                x=selected[:, index],
                y=position + rng.uniform(-0.28, 0.28, len(selected)),
                mode="markers",
                name=names[index],
                marker={
                    "color": data[:, index],
                    "colorscale": "RdBu",
                    "reversescale": True,
                    "size": 5,
                    "colorbar": {"title": "特征值"},
                    "showscale": position == 0,
                },
                customdata=np.asarray(result["obs_names"])[:, None],
                hovertemplate="%{customdata[0]}<br>SHAP=%{x}<extra>%{fullData.name}</extra>",
            )
        figure.update_layout(
            yaxis={
                "tickvals": list(range(len(indices))),
                "ticktext": np.asarray(names)[indices][::-1],
            },
            xaxis_title="SHAP",
            showlegend=False,
        )
    elif kind == "shap_waterfall":
        index = np.argsort(-np.abs(selected[cell_index]), kind="stable")[:top]
        residual = float(selected[cell_index].sum() - selected[cell_index, index].sum())
        figure.add_waterfall(
            x=["基准", *np.asarray(names)[index], "其他特征", "预测输出"],
            y=[float(baselines[cell_index]), *selected[cell_index, index], residual, 0],
            measure=["absolute", *["relative"] * (len(index) + 1), "total"],
        )
        figure.update_layout(
            xaxis_title=f"细胞 {result['obs_names'][cell_index]}",
            yaxis_title=result.get("output_space", "解释输出"),
        )
    else:
        feature = feature or names[indices[0]]
        if feature not in names:
            raise ValueError("请选择有效特征。")
        index = names.index(feature)
        figure.add_scatter(
            x=data[:, index],
            y=selected[:, index],
            mode="markers",
            customdata=np.asarray(result["obs_names"])[:, None],
        )
        figure.update_layout(xaxis_title=feature, yaxis_title="SHAP")
    tables = {"input.csv": pd.DataFrame(data, index=result["obs_names"], columns=names).to_csv()}
    for i in range(values.shape[2] if values.ndim == 3 else 1):
        tables[f"shap_{i}.csv"] = pd.DataFrame(
            values[:, :, i] if values.ndim == 3 else values,
            index=result["obs_names"],
            columns=names,
        ).to_csv()
    tables["baselines.csv"] = pd.DataFrame(base if base.ndim else [base]).to_csv(index=False)
    figure.update_layout(
        title=f"SHAP · {classes[class_index]}",
        meta={
            "point_kind": "cell" if kind in {"shap_beeswarm", "shap_dependence"} else "feature",
            "classes": classes,
            "class_index": class_index,
            "output_space": "explainer output; see parameters",
            "export_tables": tables,
        },
    )
    return figure
