"""Transactional preprocessing and analysis operations exposed to web clients."""
# ruff: noqa: RUF001

from collections import Counter
from copy import deepcopy
from pathlib import PureWindowsPath

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from scMM.plot.presentation import feature_label, qc_file_table, style_figure
from scMM.plot.workbench import (
    embedding_figure,
    network_figure,
    supervised_figures,
    violin_figure,
    volcano_figure,
)

from .web_support import figure_view, json_view, table_view
from .workbench import dense

PREPROCESS = {"subset", "filter", "normalize", "impute", "remove_outliers", "restore", "reset"}
ANALYSES = {
    "reduce",
    "cluster",
    "differential",
    "markers",
    "network",
    "train",
    "explain_shap",
    "save_latent",
}
RESULT_NAMES = {"train": "supervised", "explain_shap": "shap"}


def quality_view(state):
    qc = state.qc()
    files = qc_file_table(qc["file"])
    files.insert(0, "source_path", files.attrs["source_paths"])
    cell_frame = qc["cell"].copy()
    cell_frame["cell_id"] = state.require_data().obs_names.astype(str)
    figure = px.scatter(
        cell_frame,
        x="total_intensity",
        y="detected_features",
        color="source_file",
        labels={
            "source_file": "样本",
            "total_intensity": "总强度",
            "detected_features": "检出特征数",
        },
        title="每细胞 QC · 当前矩阵",
        custom_data=["cell_id", "source_file"],
    )
    names = Counter(PureWindowsPath(str(trace.name)).name for trace in figure.data)
    occurrences = Counter()
    for trace in figure.data:
        name = PureWindowsPath(str(trace.name)).name
        occurrences[name] += 1
        trace.name = name if names[name] == 1 else f"{name}（{occurrences[name]}）"
        trace.hovertemplate = (
            "文件：%{customdata[1]}<br>当前总强度：%{x:.1e}"
            "<br>强度 > 0 的特征数：%{y}<extra></extra>"
        )
    figure.update_layout(
        legend_title_text="",
        meta={
            "point_kind": "cell",
            "parameters": {"definition": "current matrix; detected >0"},
            "export_tables": {"cells": cell_frame.to_csv(), "files": files.to_csv(index=False)},
        },
    )
    style_figure(figure)
    detected = qc["cell"]["detected_features"]
    figure.update_yaxes(
        rangemode="nonnegative", dtick=1 if detected.max() - detected.min() <= 8 else None
    )
    notes = ["QC 基于当前矩阵；检出特征按强度 > 0 计数。变换后的总强度不代表原始信号量。"]
    totals = qc["cell"]["total_intensity"].to_numpy(dtype=float)
    nonzero = totals[totals != 0]
    if (
        len(nonzero)
        and np.isfinite(totals).all()
        and np.all(np.abs(nonzero - 1) <= 64 * np.finfo(float).eps)
    ):
        figure.update_xaxes(
            range=[-0.05 if np.any(totals == 0) else 0.95, 1.05],
            tickformat=".1e",
            hoverformat=".1e",
        )
        notes.append(
            "非零细胞总强度约为 1；横轴采用稳定范围，避免浮点求和误差形成假分群。零总和细胞仍显示在 0，下载保留完整数值精度。"
        )
    return {
        "notes": notes,
        "files": table_view(files, limit=len(files)),
        "cells": table_view(qc["cell"]),
        "figure": figure_view(figure),
    }


def stored_figure(value):
    import json

    return json.loads(value) if isinstance(value, str) else deepcopy(value)


def analysis_settings(project):
    if "analysis" in project.views:
        return deepcopy(project.views["analysis"])
    old = project.views.get("settings", {})
    groups = {
        "reduction": {
            "reduction": "method",
            "embedding_key": "store_key",
            "representation": "use_rep",
            "dimensions": "n_components",
            "neighbors": "n_neighbors",
            "perplexity": "perplexity",
            "seed": "random_state",
            "scale": "scale",
        },
        "cluster": {"cluster_method": "method", "cluster_key": "key", "clusters": "n_clusters"},
        "diff": {
            "group": "group_key",
            "group_a": "group_a",
            "group_b": "group_b",
            "diff_layer": "layer",
            "diff_method": "method",
        },
        "network": {
            "network_method": "method",
            "network_threshold": "min_abs_correlation",
            "network_top_features": "top_features",
        },
        "train": {
            "label": "label_key",
            "sample_group": "group_key",
            "model_layer": "layer",
            "model": "model",
            "cv": "cv",
            "test_size": "test_size",
            "calibration_bins": "calibration_bins",
            "smote": "smote",
        },
        "shap": {"shap_background": "max_background", "shap_samples": "max_samples"},
    }
    result = {
        group: {target: old[key] for key, target in mapping.items() if key in old}
        for group, mapping in groups.items()
    }
    for source, target in {
        "embedding_view": "embedding",
        "color_source": "colorSource",
        "color": "color",
        "features": "selectedFeatures",
        "hide_zero": "hideZero",
        "lda_solver": "ldaSolver",
        "latent_key": "latentKey",
    }.items():
        if source in old:
            result[target] = old[source]
    if str(result.get("color", "")).startswith("feature:"):
        result.setdefault("colorSource", "feature")
    return result


class AnalysisWorkflow:
    def analysis_info(self, identity):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            state = project.workspace
            data = state.require_data()
            values = {
                str(key): sorted(data.obs[key].dropna().astype(str).unique().tolist())
                for key in data.obs
            }
            results = sorted(set(state.results) | set(project.saved_reports))
            return {
                "token": list(state.token),
                "layers": list(data.layers),
                "embeddings": list(data.obsm),
                "embedding_dimensions": {
                    key: int(value.shape[1]) for key, value in data.obsm.items()
                },
                "embedding_variance": {
                    key: list(data.uns.get(f"{key}_params", {}).get("explained_variance_ratio", []))
                    for key in data.obsm
                },
                "observations": values,
                "feature_columns": list(data.var.columns),
                "history": state.history(),
                "results": results,
                "live_results": list(state.results),
                "latent_supported": "supervised" in state.results
                and state.result("supervised").supports_latent_scores,
                "settings": analysis_settings(project),
                "legend": project.views.get("legend", "right"),
                "figures": sorted(project.views.get("figures", {})),
            }

    def saved_figure(self, identity, key):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            figures = project.views.get("figures", {})
            if key not in figures:
                raise ValueError("图形不存在或已失效。")
            value = stored_figure(figures[key])
            if key in {"feature_scatter", "feature_embedding", "stability"}:
                value["layout"]["meta"]["dataset_token"] = list(project.workspace.token)
            return value

    def feature_choices(
        self, identity, *, query="", sort="mean", descending=True, offset=0, limit=200
    ):
        with self.access(identity) as workspace:
            data = workspace.require_project().workspace.require_data()
            values = dense(data.X) if sort not in {"mz", "name"} else None
            import numpy as np

            scores = {
                "mean": lambda: values.mean(axis=0),
                "total": lambda: values.sum(axis=0),
                "median": lambda: np.median(values, axis=0),
                "detection": lambda: (values != 0).mean(axis=0),
                "mz": lambda: pd.to_numeric(
                    data.var.get("mz", pd.Series(data.var_names)), errors="coerce"
                ).to_numpy(),
                "name": lambda: np.asarray(data.var_names),
            }[sort]()
            order = (
                pd.Series(scores)
                .sort_values(ascending=not descending, kind="stable", na_position="last")
                .index
            )
            from scMM.util.lipid_annotation import annotation_store, version_valid

            annotations = annotation_store(data)
            active = next(
                (v for v in annotations["versions"] if v["id"] == annotations.get("active")), None
            )
            names = {}
            if active and version_valid(data, active):
                for candidate in active["candidates"]:
                    names.setdefault(candidate["feature_id"], set()).add(
                        str(candidate.get("name", ""))
                    )
            rows = []
            for j in order:
                name = str(data.var_names[j])
                mz = data.var.iloc[j].get("mz")
                label = f"{feature_label(name, mz)} · {name} · #{j + 1}"
                if names.get(name):
                    label += " · " + " / ".join(sorted(names[name]))
                if query.casefold() in f"{label} {mz}".casefold():
                    rows.append({"value": name, "label": label})
            return {"total": len(rows), "rows": rows[offset : offset + limit]}

    def qc_view(self, identity):
        with self.access(identity) as workspace:
            return quality_view(workspace.require_project().workspace)

    def run_operation(self, identity, revision, operation, options, *, preview=False):
        from .web_workspace import project_candidate

        if operation not in PREPROCESS | ANALYSES or (preview and operation not in PREPROCESS):
            raise ValueError("不支持的分析操作。")
        with self.access(identity, operation=operation) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            candidate = project_candidate(project)
            state = candidate.workspace
            # SHAP enriches the fitted analyzer; isolate it too so failures are atomic.
            if operation == "explain_shap":
                state.results = deepcopy(state.results)
            getattr(state, operation)(**options)
            if preview:
                before, after = project.workspace.data, state.data
                impact = [
                    {"object": "细胞", "before": before.n_obs, "after": after.n_obs},
                    {"object": "特征", "before": before.n_vars, "after": after.n_vars},
                ]
                if "sample" in before.obs:
                    counts = after.obs["sample"].value_counts()
                    impact.extend(
                        {"object": str(k), "before": int(v), "after": int(counts.get(k, 0))}
                        for k, v in before.obs["sample"].value_counts().items()
                    )
                return {
                    "workspace": self.view(workspace),
                    "value": {"impact": impact, "qc": quality_view(state)},
                }
            if operation in PREPROCESS:
                candidate.saved_reports = {}
                candidate.views.pop("figures", None)
            elif operation in {"reduce", "cluster", "save_latent"}:
                for key in ("feature_scatter", "feature_embedding", "stability"):
                    figure = candidate.views.get("figures", {}).get(key)
                    if figure:
                        figure["layout"]["meta"]["dataset_token"] = list(state.token)
            else:
                result_name = RESULT_NAMES.get(operation, operation)
                candidate.saved_reports.pop(result_name, None)
                from .web_workspace import RESULT_PLOTS

                for name in RESULT_PLOTS.get(result_name, ()):
                    candidate.views.get("figures", {}).pop(name, None)
                if operation == "train":
                    candidate.saved_reports.pop("shap", None)
                    candidate.views.get("figures", {}).pop("shap_plot", None)
            candidate.report_token = state.token
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            workspace.ai_completed = operation
            if operation in {"filter", "remove_outliers"}:
                workspace.ai_before_filter = {
                    "cells": int(project.workspace.data.n_obs),
                    "features": int(project.workspace.data.n_vars),
                }
            elif operation == "reset":
                workspace.ai_before_filter = {}
            if operation in PREPROCESS:
                workspace.ai_parameters = {}
            workspace.ai_parameters[operation] = options.copy()
            return self.view(workspace)

    def invalidate_results(self, identity, revision, names):
        from .web_workspace import RESULT_PLOTS

        def action(workspace):
            project = workspace.project
            selected = set(names)
            if "supervised" in selected:
                selected.add("shap")
            for name in selected:
                project.workspace.results.pop(name, None)
                project.saved_reports.pop(name, None)
                for figure in RESULT_PLOTS.get(name, ()):
                    project.views.get("figures", {}).pop(figure, None)
            project.dirty = True

        return self.mutate(identity, revision, action)

    @staticmethod
    def result_value(project, name):
        if name in project.workspace.results:
            result = project.workspace.result(name)
            if name == "supervised":
                return {
                    "diagnostics": json_view(result.result_),
                    "label_key": result.label_key,
                    "group_key": result.group_key,
                    "train_obs": result.train_obs_names_.tolist(),
                    "test_obs": result.test_obs_names_.tolist(),
                    "classes": result.classes_.tolist(),
                }
            return result
        if name in project.saved_reports:
            result = deepcopy(project.saved_reports[name])
            if "table" in result:
                result["table"] = pd.DataFrame(result["table"])
            return result
        raise ValueError("结果不存在或已失效，请重新计算。")

    def result_view(self, identity, name, offset=0, limit=200):
        with self.access(identity) as workspace:
            result = self.result_value(workspace.require_project(), name)
            if "table" in result:
                table = result["table"]
                payload = table_view(table.iloc[offset : offset + limit])
                payload["total"] = len(table)
                return {
                    "table": payload,
                    "parameters": json_view(
                        {
                            k: v
                            for k, v in result.items()
                            if k not in {"table", "graph", "correlation"}
                        }
                    ),
                }
            return json_view(result)

    def analysis_plot(self, identity, revision, kind, options):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            state = project.workspace
            data = state.require_data()
            if kind == "embedding":
                figure = embedding_figure(data, **options)
            elif kind == "volcano":
                figure = volcano_figure(
                    self.result_value(project, "differential")["table"], **options
                )
            elif kind == "violin":
                figure = violin_figure(data, self.result_value(project, "differential"), **options)
            elif kind == "network_plot":
                if "network" in state.results:
                    figure = network_figure(state.result("network")["graph"])
                elif kind in project.views.get("figures", {}):
                    return {
                        "workspace": self.view(workspace),
                        "value": stored_figure(project.views["figures"][kind]),
                    }
                else:
                    raise ValueError("请重新计算相关网络。")
            elif kind in {"shap_plot", "shap_beeswarm", "shap_waterfall", "shap_dependence"}:
                from scMM.plot.explanations import shap_figure

                figure = shap_figure(self.result_value(project, "shap"), kind, **options)
            elif kind == "heatmap":
                from scMM.analysis.heatmap import heatmap_figure

                figure = heatmap_figure(data, **options)
            elif kind == "stability":
                from scMM.analysis.stability import stability_figure

                figure = stability_figure(data, **options)
            elif kind == "feature_embedding":
                from scMM.analysis.feature_embedding import feature_embedding_figure

                figure = feature_embedding_figure(data, **options)
            elif kind == "feature_scatter":
                from scMM.analysis.feature_scatter import feature_scatter_figure

                figure = feature_scatter_figure(data, **options)
            elif kind == "confusion":
                analyzer = state.result("supervised")
                values = np.asarray(analyzer.result_["confusion_matrix"])
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
                        x=analyzer.classes_.astype(str),
                        y=analyzer.classes_.astype(str),
                        colorscale="Blues",
                        text=display,
                        texttemplate="%{text:.2f}"
                        if options.get("normalize", False)
                        else "%{text}",
                    )
                )
                figure.update_layout(
                    title="留出测试集混淆矩阵",
                    xaxis_title="预测类别",
                    yaxis_title="真实类别",
                    meta={
                        "export_tables": {
                            "counts.csv": pd.DataFrame(
                                values, index=analyzer.classes_, columns=analyzer.classes_
                            ).to_csv(),
                            "row_normalized.csv": pd.DataFrame(
                                np.divide(
                                    values,
                                    values.sum(axis=1, keepdims=True),
                                    out=np.zeros_like(values, dtype=float),
                                    where=values.sum(axis=1, keepdims=True) > 0,
                                ),
                                index=analyzer.classes_,
                                columns=analyzer.classes_,
                            ).to_csv(),
                        }
                    },
                )
            elif kind in {"roc", "pr", "calibration"}:
                if "supervised" not in state.results:
                    if kind in project.views.get("figures", {}):
                        return {
                            "workspace": self.view(workspace),
                            "value": stored_figure(project.views["figures"][kind]),
                        }
                    raise ValueError("重载的模型报告只读；请重新训练以生成新图。")
                figure = supervised_figures(state.result("supervised"))[
                    {"roc": 0, "pr": 1, "calibration": 2}[kind]
                ]
            else:
                raise ValueError("不支持的图形。")
            figure.update_layout(
                meta={
                    **(figure.layout.meta or {}),
                    "dataset_token": list(state.token),
                    "parameters": options,
                }
            )
            export_tables = dict((figure.layout.meta or {}).get("export_tables", {}))
            if kind == "volcano":
                export_tables["statistics"] = self.result_value(project, "differential")[
                    "table"
                ].to_csv(index=False)
            elif kind == "violin":
                result = self.result_value(project, "differential")
                matrix = data.to_df(layer=result["layer"])[options["features"]]
                export_tables["source"] = matrix.join(data.obs, rsuffix="_annotation").to_csv()
                export_tables["statistics"] = result["table"].to_csv(index=False)
            elif kind == "network_plot" and "network" in state.results:
                result = state.result("network")
                export_tables["edges"] = result["table"].to_csv(index=False)
                export_tables["correlations"] = result["correlation"].to_csv()
            elif (
                kind in {"roc", "pr", "calibration", "confusion"} and "supervised" in state.results
            ):
                analyzer = state.result("supervised")
                export_tables["predictions"] = pd.DataFrame(
                    {
                        "cell_id": analyzer.test_obs_names_,
                        "actual": analyzer.y_test_,
                        "predicted": analyzer.prediction_,
                        **{
                            f"probability_{label}": analyzer.probabilities_[:, i]
                            for i, label in enumerate(analyzer.classes_)
                        },
                    }
                ).to_csv(index=False)
            figure.update_layout(
                meta={**(figure.layout.meta or {}), "export_tables": export_tables}
            )
            payload = figure_view(style_figure(figure))
            project.views.setdefault("figures", {})[kind] = payload
            project.dirty = True
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": payload}

    def save_view_settings(self, identity, revision, analysis, legend):
        def action(workspace):
            project = workspace.project
            project.views["analysis"] = deepcopy(analysis)
            project.views["legend"] = legend
            project.dirty = True

        return self.mutate(identity, revision, action)
