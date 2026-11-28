"""Transactional preprocessing and analysis operations exposed to web clients."""
# ruff: noqa: RUF001

import json
from collections import Counter
from copy import deepcopy
from pathlib import PureWindowsPath
from uuid import uuid4

import numpy as np
import pandas as pd
import plotly.express as px

from scMM.plot.presentation import feature_label, qc_file_table, style_figure
from scMM.plot.workbench import (
    embedding_figure,
    network_figure,
    supervised_figures,
    violin_figure,
    volcano_figure,
)
from scMM.plugins import _bundled
from scMM.util.observations import observation_kind

from .result_catalog import (
    PLOT_RESULTS,
    RESULT_NAMES,
    RESULT_PLOTS,
    RESULTS,
    live_report,
    project_result_identities,
    rebind_figure_identity,
    related_results,
    restore_report,
)
from .web_support import figure_view, json_view, table_view
from .workbench import dense

PREPROCESS = {"subset", "filter", "normalize", "impute", "remove_outliers", "restore", "reset"}
ANALYSES = {
    "reduce",
    "cluster",
    "differential",
    "markers",
    *_bundled.OPERATIONS,
}


def quality_view(state, *, preview_of=None):
    qc = state.qc()
    unit = observation_kind(state.require_data())
    unit_name = "样本" if unit == "sample" else "细胞"
    files = qc_file_table(qc["file"])
    files.insert(0, "source_path", files.attrs["source_paths"])
    if unit == "sample":
        files = files.rename(columns={"cells": "samples"})
    cell_frame = qc["cell"].copy()
    identifier = "observation_id" if unit == "sample" else "cell_id"
    cell_frame[identifier] = state.require_data().obs_names.astype(str)
    figure = px.scatter(
        cell_frame,
        x="total_intensity",
        y="detected_features",
        color="source_file",
        labels={
            "source_file": "Sample",
            "total_intensity": "Total intensity",
            "detected_features": "Detected features",
        },
        title=f"{unit.title()} quality control · current matrix",
        custom_data=[identifier, "source_file"],
    )
    names = Counter(PureWindowsPath(str(trace.name)).name for trace in figure.data)
    occurrences = Counter()
    for trace in figure.data:
        name = PureWindowsPath(str(trace.name)).name
        occurrences[name] += 1
        trace.name = name if names[name] == 1 else f"{name}（{occurrences[name]}）"
        trace.hovertemplate = (
            "File: %{customdata[1]}<br>Current total intensity: %{x:.1e}"
            "<br>Features with intensity > 0: %{y}<extra></extra>"
        )
    figure.update_layout(
        legend_title_text="",
        meta={
            "point_kind": unit,
            "observation_kind": unit,
            "dataset_token": list(state.token)
            if preview_of is None
            else preview_of["source_token"],
            "matrix_status": "current" if preview_of is None else "preview",
            "preview_of": preview_of,
            "parameters": {
                "definition": "current matrix; detected >0"
                if preview_of is None
                else "unapplied candidate; detected >0"
            },
            "export_tables": {f"{unit}s": cell_frame.to_csv(), "files": files.to_csv(index=False)},
        },
    )
    style_figure(figure)
    detected = qc["cell"]["detected_features"]
    figure.update_yaxes(
        rangemode="nonnegative", dtick=1 if detected.max() - detected.min() <= 8 else None
    )
    notes = [
        "QC 基于当前矩阵；检出特征按强度 > 0 计数。变换后的总强度不代表原始信号量。"
        if preview_of is None
        else "QC 基于未应用的预览候选；检出特征按强度 > 0 计数，不代表当前矩阵。"
    ]
    if preview_of is not None:
        figure.update_layout(title=f"{unit.title()} quality control · unapplied preview")
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
            f"非零{unit_name}总强度约为 1；横轴采用稳定范围，避免浮点求和误差形成假分群。零总和{unit_name}仍显示在 0，下载保留完整数值精度。"
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
        from scMM.analysis.plot_scope import group_display_names

        from .method_reports import report_summaries

        with self.access(identity) as workspace:
            project = workspace.require_project()
            state = project.workspace
            data = state.require_data()
            values = {
                str(key): sorted(data.obs[key].dropna().astype(str).unique().tolist())
                for key in data.obs
            }
            results = sorted((set(state.results) | set(project.saved_reports)) & RESULTS.keys())
            return {
                "token": list(state.token),
                "layers": list(data.layers),
                "original_layer": data.uns.get("scmm_workbench", {}).get("original_layer"),
                "numeric_observations": [
                    str(key)
                    for key in data.obs
                    if pd.api.types.is_numeric_dtype(data.obs[key])
                    and not pd.api.types.is_bool_dtype(data.obs[key])
                ],
                "sample_labels": group_display_names(
                    data, "sample_id", values.get("sample_id", [])
                ),
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
                "method_reports": report_summaries(data),
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
            rebind_figure_identity(
                value, project.workspace, kind=key, identities=project_result_identities(project)
            )
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
            from .annotation_sources import analysis_annotations

            names, _ = analysis_annotations(workspace.require_project(), data)
            display_names = data.var.get("display_name")
            rows = []
            for j in order:
                name = str(data.var_names[j])
                mz = data.var.iloc[j].get("mz")
                label = f"{feature_label(name, mz)} · {name} · #{j + 1}"
                if display_names is not None and pd.notna(display_names.iloc[j]):
                    display = str(display_names.iloc[j]).strip()
                    if display:
                        label += f" · {display}"
                if names.get(name):
                    label += " · " + " / ".join(sorted(names[name]))
                if query.casefold() in f"{label} {mz}".casefold():
                    rows.append({"value": name, "label": label})
            return {"total": len(rows), "rows": rows[offset : offset + limit]}

    def qc_view(self, identity):
        with self.access(identity) as workspace:
            return quality_view(workspace.require_project().workspace)

    def qc_plot(self, identity, revision, kind, group_key, layer, **options):
        from scMM.analysis.qc_plots import distribution_figure, sample_correlation_figure

        with self.access(identity) as workspace:
            workspace.check(revision)
            state = workspace.require_project().workspace
            data = state.require_data()
            if layer is not None and layer not in data.layers:
                raise ValueError("所选 QC 数据层已失效，请重新选择。")
            if kind == "distribution":
                figure = distribution_figure(
                    data,
                    group_key=group_key,
                    layer=layer,
                    **{key: options[key] for key in ("metric", "bins", "relative", "palette")},
                )
            else:
                figure = sample_correlation_figure(
                    data,
                    sample_key=group_key,
                    layer=layer,
                    **{key: options[key] for key in ("aggregate", "colorscale", "square")},
                )
            figure.update_layout(
                meta={
                    **figure.layout.meta,
                    "dataset_token": list(state.token),
                    "parameters": {"kind": kind, "group_key": group_key, "layer": layer, **options},
                }
            )
            return {"workspace": self.view(workspace), "value": figure_view(figure)}

    def run_operation(self, identity, revision, operation, options, *, preview=False):
        from .web_projects import project_candidate

        if operation not in PREPROCESS | ANALYSES or (preview and operation not in PREPROCESS):
            raise ValueError("不支持的分析操作。")
        if operation in _bundled.OPERATIONS:
            self.require_plugin(_bundled.OPERATIONS[operation])
        with self.access(identity, operation=operation) as workspace:
            from .analysis_inputs import resolve_analysis_input

            workspace.check(revision)
            project = workspace.require_project()
            candidate = project_candidate(project)
            if operation in ANALYSES and candidate.ion_state is not None:
                resolve_analysis_input(candidate, purpose=operation)
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
                    "value": {
                        "impact": impact,
                        "qc": quality_view(
                            state,
                            preview_of={
                                "operation": operation,
                                "parameters": options,
                                "source_token": list(project.workspace.token),
                            },
                        ),
                    },
                }
            if operation in PREPROCESS:
                candidate.saved_reports = {}
                candidate.views.pop("figures", None)
            elif operation in {"reduce", "cluster", "save_latent"}:
                for key, figure in candidate.views.get("figures", {}).items():
                    if isinstance(figure, str):
                        figure = stored_figure(figure)
                        candidate.views["figures"][key] = figure
                    rebind_figure_identity(
                        figure,
                        state,
                        previous_token=project.workspace.token,
                        kind=key,
                        identities=project_result_identities(candidate),
                    )
            else:
                result_name = RESULT_NAMES.get(operation, operation)
                for name in related_results({result_name}):
                    candidate.saved_reports.pop(name, None)
                    for figure in RESULT_PLOTS.get(name, ()):
                        candidate.views.get("figures", {}).pop(figure, None)
            candidate.report_token = state.token
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            workspace.ai_completed = operation
            if operation in {"filter", "remove_outliers"}:
                workspace.ai_before_filter = {
                    "observations": int(project.workspace.data.n_obs),
                    "features": int(project.workspace.data.n_vars),
                }
            elif operation == "reset":
                workspace.ai_before_filter = {}
            if operation in PREPROCESS:
                workspace.ai_parameters = {}
            workspace.ai_parameters[operation] = options.copy()
            return self.view(workspace)

    def invalidate_results(self, identity, revision, names):
        for name in names:
            if name in _bundled.RESULTS:
                self.require_plugin(_bundled.RESULTS[name])

        def action(workspace):
            project = workspace.project
            selected = related_results(names)
            for name in selected:
                project.workspace.results.pop(name, None)
                project.saved_reports.pop(name, None)
                for figure in RESULT_PLOTS.get(name, ()):
                    project.views.get("figures", {}).pop(figure, None)
            project.dirty = True

        return self.mutate(identity, revision, action)

    @staticmethod
    def result_value(project, name):
        if name not in RESULTS:
            raise ValueError("结果类型不存在。")
        if name in project.workspace.results:
            return live_report(name, project.workspace.result(name))
        if name in project.saved_reports:
            return restore_report(name, project.saved_reports[name])
        raise ValueError("结果不存在或已失效，请重新计算。")

    def result_view(self, identity, name, offset=0, limit=200, *, row_filter="all"):
        with self.access(identity) as workspace:
            result = self.result_value(workspace.require_project(), name)
            if "table" in result:
                table = result["table"]
                if name == "differential" and row_filter != "all":
                    if row_filter == "finite_effect":
                        table = table[
                            np.isfinite(pd.to_numeric(table.log2_fold_change, errors="coerce"))
                        ]
                    elif row_filter == "not_estimable":
                        table = table[pd.to_numeric(table.p_value, errors="coerce").isna()]
                    elif row_filter == "both_zero":
                        table = table[(table.mean_a == 0) & (table.mean_b == 0)]
                    elif row_filter == "single_zero":
                        table = table[(table.mean_a == 0) ^ (table.mean_b == 0)]
                payload = table_view(table.iloc[offset : offset + limit], limit=limit)
                payload.update(total=len(table), offset=offset, row_filter=row_filter)
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
        if kind in _bundled.PLOTS:
            self.require_plugin(_bundled.PLOTS[kind])
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            state = project.workspace
            data = state.require_data()
            options = options.copy()
            scope = options.get("scope")
            if kind in {"embedding", "violin", "feature_scatter"}:
                from scMM.analysis.plot_scope import plot_subset

                data = plot_subset(data, options.pop("scope", None))
            if kind == "msms_evidence":
                return {
                    "workspace": self.view(workspace),
                    "value": self.saved_figure(identity, kind),
                }
            if kind in {"target_correlations", "association", "set_comparison"}:
                from scMM.analysis.exploration import association, correlated_features, memberships

                figure = {
                    "target_correlations": correlated_features,
                    "association": association,
                    "set_comparison": memberships,
                }[kind](data, **options)
            elif kind == "embedding":
                figure = embedding_figure(data, **options)
            elif kind == "volcano":
                figure = volcano_figure(
                    self.result_value(project, "differential")["table"], **options
                )
            elif kind == "violin":
                figure = violin_figure(data, self.result_value(project, "differential"), **options)
            elif kind == "network_plot":
                figure = network_figure(self.result_value(project, "network")["graph"])
            elif kind in {"shap_plot", "shap_beeswarm", "shap_waterfall", "shap_dependence"}:
                from scMM.plot.explanations import shap_figure

                figure = shap_figure(self.result_value(project, "shap"), kind, **options)
            elif kind == "heatmap":
                from scMM.analysis.heatmap import heatmap_figure

                figure = heatmap_figure(data, **options)
            elif kind == "stability":
                from scMM.analysis.stability import stability_figure

                figure = stability_figure(data, **options)
            elif kind == "time_plot":
                from .time_analysis import time_figure

                figure = time_figure(data, **options)
            elif kind == "feature_embedding":
                from scMM.analysis.feature_embedding import feature_embedding_figure

                figure = feature_embedding_figure(data, **options)
            elif kind == "feature_scatter":
                from scMM.analysis.feature_scatter import feature_scatter_figure

                figure = feature_scatter_figure(data, **options)
            elif kind == "confusion":
                from scMM.plugins._supervised import confusion_figure

                figure = confusion_figure(self.result_value(project, "supervised"), options)
            elif kind in {"roc", "pr", "calibration"}:
                if "supervised" not in state.results:
                    if kind in project.views.get("figures", {}):
                        value = stored_figure(project.views["figures"][kind])
                        rebind_figure_identity(
                            value, state, kind=kind, identities=project_result_identities(project)
                        )
                        return {"workspace": self.view(workspace), "value": value}
                    raise ValueError("重载的模型报告只读；请重新训练以生成新图。")
                figure = supervised_figures(state.result("supervised"))[
                    {"roc": 0, "pr": 1, "calibration": 2}[kind]
                ]
            else:
                raise ValueError("不支持的图形。")
            parent = PLOT_RESULTS.get(kind)
            result_identity = project_result_identities(project).get(parent) if parent else None
            if parent and not result_identity:
                result_identity = uuid4().hex
            if parent:
                figure.update_layout(
                    meta={
                        **(figure.layout.meta or {}),
                        "result_name": parent,
                        "result_identity": result_identity,
                        "result_identity_valid": True,
                    }
                )
            figure.update_layout(
                meta={
                    **(figure.layout.meta or {}),
                    "dataset_token": list(state.token),
                    "analysis_input": json.loads(data.uns.get("scmm_analysis_input_json", "{}")),
                    "selected_cells": (figure.layout.meta or {}).get("selected_cells", data.n_obs),
                    "total_cells": state.require_data().n_obs,
                    "parameters": {**options, **({"scope": scope} if scope is not None else {})},
                    "observation_dependencies": sorted(
                        set((figure.layout.meta or {}).get("observation_dependencies", []))
                        | set((figure.layout.meta or {}).get("observation_dependencies", []))
                        | (
                            {options["color"][4:]}
                            if kind == "embedding"
                            and (options.get("color") or "").startswith("obs:")
                            else set()
                        )
                        | {
                            scope[key]
                            for key, values in (("group_key", "groups"), ("sample_key", "samples"))
                            if scope and scope.get(values) is not None and scope.get(key)
                        }
                        | (
                            {options["group_key"]}
                            if kind == "heatmap" and options.get("group_key")
                            else set()
                        )
                        | (
                            {options["sample_key"]}
                            if kind == "heatmap"
                            and options.get("equal_samples")
                            and options.get("sample_key")
                            else set()
                        )
                    ),
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
            if parent:
                if parent in state.results:
                    state._result_identities[parent] = result_identity
                elif parent in project.saved_reports:
                    project.saved_reports[parent]["_result_identity"] = result_identity
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
