"""Bundled training and explanation workflow."""
# ruff: noqa: RUF001

import json

import numpy as np
import pandas as pd

from scMM.analysis.supervised import SupervisedAnalyzer
from scMM.application.result_catalog import metadata_dependencies


def train(state, label_key, *, group_key=None, layer=None, model="logistic", **options):
    token = state.token
    analyzer = SupervisedAnalyzer(
        state.require_data(),
        label_key,
        group_key=group_key,
        layer=layer,
        random_state=options.pop("random_state", 42),
    )
    analyzer.label_key = label_key
    analyzer.group_key = group_key
    analyzer.evaluate(model, **options)
    state.results.pop("shap", None)
    state.put_result("supervised", analyzer, token)
    return analyzer


def explain_shap(state, **options):
    state.results.pop("shap", None)
    token = state.token
    analyzer = state.result("supervised")
    explanation = analyzer.explain_shap(**options)
    values = np.abs(explanation.values)
    if values.ndim not in (2, 3):
        raise ValueError("Unsupported SHAP value shape")
    importance = values.mean(axis=(0, 2) if values.ndim == 3 else 0)
    table = pd.DataFrame({"feature_id": analyzer.feature_names, "mean_abs_shap": importance})
    result = {
        "table": table.sort_values("mean_abs_shap", ascending=False),
        "parameters": {**options, **analyzer.shap_parameters_},
        "output_space": analyzer.shap_output_space_,
        "background_obs": analyzer.shap_background_obs_.tolist(),
        "obs_names": analyzer.shap_obs_names_.tolist(),
        "values": explanation.values,
        "base_values": explanation.base_values,
        "data": explanation.data,
        "feature_names": list(analyzer.feature_names),
        "classes": analyzer.classes_.tolist(),
    }
    state.put_result("shap", result, token)
    return result


def save_latent(state, key):
    analyzer = state.result("supervised")
    candidate = state.require_data().copy()
    if key in candidate.obsm or f"{key}_split" in candidate.obs:
        raise ValueError("Latent output key already exists")
    if not key or "/" in key:
        raise ValueError("Invalid output key")
    scores = analyzer.latent_scores().reindex(candidate.obs_names)
    candidate.obsm[key] = scores.to_numpy()
    split = pd.Series("unlabeled", index=candidate.obs_names)
    split.loc[analyzer.train_obs_names_] = "train"
    split.loc[analyzer.test_obs_names_] = "test"
    candidate.obs[f"{key}_split"] = pd.Categorical(split)
    metadata = candidate.uns["scmm_workbench"]
    metadata["derived_obs"] = [*metadata.get("derived_obs", []), f"{key}_split"]
    fields = sorted(metadata_dependencies("supervised", analyzer, {}))
    rules = json.loads(metadata.get("latent_dependencies_json", "{}"))
    if not isinstance(rules, dict):
        raise ValueError("invalid latent dependency metadata")
    rules[key] = fields
    metadata["latent_dependencies_json"] = json.dumps(rules)
    state._commit(
        candidate,
        "latent",
        {
            "model": analyzer.model_name_,
            "store_key": key,
            "label_key": analyzer.label_key,
            "group_key": analyzer.group_key,
            "observation_dependencies": fields,
        },
        clear_derived=False,
        save_layer=False,
    )
    state.put_result("supervised", analyzer, state.token)


def confusion_figure(report_value, options):
    import plotly.graph_objects as go

    report = report_value
    try:
        classes = np.asarray(report["classes"])
        values = np.asarray(report["diagnostics"]["confusion_matrix"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("监督报告缺少有效混淆矩阵，请重新训练。") from exc
    if (
        classes.ndim != 1
        or values.shape != (len(classes), len(classes))
        or not len(classes)
        or not np.isfinite(values).all()
        or (values < 0).any()
        or not np.equal(values, np.floor(values)).all()
    ):
        raise ValueError("监督报告的混淆矩阵无效，请重新训练。")
    normalized = np.divide(
        values,
        values.sum(axis=1, keepdims=True),
        out=np.zeros_like(values, dtype=float),
        where=values.sum(axis=1, keepdims=True) > 0,
    )
    display = normalized if options.get("normalize", False) else values
    figure = go.Figure(
        go.Heatmap(
            z=display,
            x=classes.astype(str),
            y=classes.astype(str),
            colorscale="Blues",
            text=display,
            texttemplate="%{text:.2f}" if options.get("normalize", False) else "%{text}",
        )
    )
    figure.update_layout(
        title="Held-out confusion matrix",
        xaxis_title="Predicted class",
        yaxis_title="True class",
        meta={
            "export_tables": {
                "counts.csv": pd.DataFrame(values, index=classes, columns=classes).to_csv(),
                "row_normalized.csv": pd.DataFrame(
                    np.divide(
                        values,
                        values.sum(axis=1, keepdims=True),
                        out=np.zeros_like(values, dtype=float),
                        where=values.sum(axis=1, keepdims=True) > 0,
                    ),
                    index=classes,
                    columns=classes,
                ).to_csv(),
            }
        },
    )
    return figure
