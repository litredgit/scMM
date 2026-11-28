"""Workspace transactions for public method plugins."""
# ruff: noqa: RUF001

import re

import numpy as np
import pandas as pd

from scMM.ion.semantics import value_states
from scMM.plugins import MatrixInput, StatisticalReport
from scMM.util.observations import observation_kind

from ..analysis_inputs import resolve_analysis_input
from ..method_reports import current_reports, report_frame, store_report
from ..result_catalog import project_result_identities, rebind_figure_identity
from ..web_analysis import quality_view, stored_figure
from ..web_projects import project_candidate
from ..workbench import dense


def matrix_input(data, layer, embedding, fields):
    if not set(fields) <= set(data.obs.columns):
        raise ValueError("所选观测元数据列不存在。")
    if embedding:
        if embedding not in data.obsm:
            raise ValueError("所选嵌入已不存在。")
        values = dense(data.obsm[embedding]).copy()
        ids = tuple(f"axis_{i + 1}" for i in range(values.shape[1]))
        space = "embedding"
    else:
        if layer and layer not in data.layers:
            raise ValueError("所选强度层已不存在。")
        values = dense(data.layers[layer] if layer else data.X).copy()
        ids = tuple(data.var_names)
        space = value_states(data)[layer or "X"]["space"]
    if not np.isfinite(values).all():
        raise ValueError("所选输入含非有限值。")
    return MatrixInput(
        values,
        tuple(data.obs_names),
        ids,
        data.obs[fields].copy(),
        observation_kind(data),
        embedding or layer or "X",
        space,
    )


def check_output_axes(output, inputs, *, check_features=False):
    """Labeled outputs must preserve the input identities in their original order."""
    if (
        isinstance(output, (pd.DataFrame, pd.Series))
        and tuple(output.index) != inputs.observation_ids
    ):
        raise ValueError("插件输出的观测 ID 或顺序与输入不一致。")
    if (
        check_features
        and isinstance(output, pd.DataFrame)
        and tuple(output.columns) != inputs.feature_ids
    ):
        raise ValueError("插件输出的特征 ID 或顺序与输入不一致。")


def apply_coordinates(state, data, kind, result, key, provenance):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", key) or key.startswith("scmm_"):
        raise ValueError("请填写有效且未保留的输出名称。")
    values = np.asarray(result)
    if kind == "reduction":
        if key in data.obsm:
            raise ValueError("嵌入名称已占用，请选择新名称。")
        if (
            values.ndim != 2
            or values.shape[0] != data.n_obs
            or values.shape[1] < 2
            or values.dtype.kind not in "fiu"
            or not np.isfinite(values).all()
        ):
            raise ValueError("降维结果必须为按细胞对齐、至少二维的有限坐标。")
        data.obsm[key] = values.copy()
    else:
        if key in data.obs:
            raise ValueError("观察列名称已占用，请选择新名称。")
        if values.shape != (data.n_obs,) or any(
            not isinstance(v, (str, int, np.integer)) or isinstance(v, bool) or not str(v).strip()
            for v in np.asarray(result, dtype=object)
        ):
            raise ValueError("聚类结果必须为每个细胞提供一个整数或文本标签。")
        data.obs[key] = pd.Categorical(values.astype(str))
        workbench = data.uns["scmm_workbench"]
        workbench["derived_obs"] = [*workbench.get("derived_obs", []), key]
    key_field = "store_key" if kind == "reduction" else "key"
    state._commit(
        data,
        "reduce" if kind == "reduction" else "cluster",
        {**provenance, key_field: key},
        clear_derived=False,
        save_layer=False,
    )


class MethodWorkflow:
    def __init__(self, service):
        self._service = service

    def run_method(
        self,
        identity,
        revision,
        method_id,
        version,
        options,
        *,
        layer=None,
        embedding=None,
        output_key="",
        source="",
        preview=False,
    ):
        method = self._service.plugins.get(method_id, version=version)
        kind = method.method.kind
        if kind in {"cell_detection", "cell_extraction"}:
            raise ValueError("提取方法请通过原始谱预览和批次入口使用。")
        if (
            (preview and kind != "preprocessing")
            or (embedding and kind not in {"reduction", "clustering"})
            or (layer and (kind == "annotation" or embedding))
            or (source and kind != "annotation")
            or (output_key and kind not in {"reduction", "clustering"})
        ):
            raise ValueError("这些输入选项不适用于该方法类型。")
        options = method.options(options)
        layer = None if layer == "X" else layer
        with self._service.access(identity, operation="plugin_method") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            candidate = project_candidate(project)
            state = candidate.workspace
            if kind == "annotation":
                from ..method_annotation import annotate

                value = annotate(candidate, source, method, options)
            else:
                data = state.require_data()
                context = resolve_analysis_input(candidate, layer=layer, purpose=method.id)
                fields = method.observation_fields(options)
                inputs = matrix_input(data, layer, embedding, fields)
                output = method.method.run(inputs, options.copy())
                if kind in {"preprocessing", "reduction", "clustering"}:
                    check_output_axes(output, inputs, check_features=kind == "preprocessing")
                provenance = {
                    "plugin": method.provenance(options),
                    "layer": layer,
                    "embedding": embedding,
                }
                if kind == "preprocessing":
                    values = np.asarray(output)
                    if values.shape != data.shape or values.dtype.kind not in "fiu":
                        raise ValueError("预处理必须返回与输入同轴同形状的数值矩阵。")
                    if not np.isfinite(values).all():
                        raise ValueError("预处理结果必须全部为有限数值。")
                    data.X = values.copy()
                    state._commit(data, "plugin_preprocess", provenance)
                    if preview:
                        return {
                            "workspace": self._service.view(workspace),
                            "value": {
                                "qc": quality_view(
                                    state,
                                    preview_of={
                                        "operation": method.id,
                                        "parameters": options,
                                        "source_token": list(project.workspace.token),
                                    },
                                ),
                            },
                        }
                    candidate.saved_reports.clear()
                    candidate.views.pop("figures", None)
                    workspace.ai_parameters = {}
                    value = {}
                elif kind in {"reduction", "clustering"}:
                    apply_coordinates(state, data, kind, output, output_key, provenance)
                    for key, raw in candidate.views.get("figures", {}).items():
                        figure = stored_figure(raw)
                        rebind_figure_identity(
                            figure,
                            state,
                            previous_token=project.workspace.token,
                            kind=key,
                            identities=project_result_identities(candidate),
                        )
                        candidate.views["figures"][key] = figure
                    value = {"key": output_key}
                else:
                    from plotly.graph_objects import Figure

                    from scMM.plot.presentation import style_figure

                    from ..web_support import figure_view

                    if not isinstance(output, StatisticalReport):
                        raise ValueError("统计方法必须返回 StatisticalReport。")
                    figure = None
                    if output.figure is not None:
                        chart = Figure(output.figure)
                        chart.layout.meta = {}
                        figure = figure_view(style_figure(chart))
                    store_report(
                        data,
                        method,
                        options,
                        layer=layer,
                        fields=fields,
                        table=output.table,
                        figure=figure,
                        context=context,
                    )
                    value = {"report": method.id}
            candidate.report_token = state.token
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self._service.view(workspace), "value": value}

    def method_result(self, identity, key, *, offset=0, limit=200, download=False):
        with self._service.access(identity) as workspace:
            reports = current_reports(workspace.require_project().workspace.require_data())
            if key not in reports:
                raise ValueError("结果不存在或输入已改变，请重新计算。")
            report = reports[key]
            if download:
                return report_frame(report).to_csv(index=False)
            return {
                "method": report["method"],
                "analysis_input": report["analysis_input"],
                "table": {
                    "columns": report["columns"],
                    "total": len(report["rows"]),
                    "rows": report["rows"][offset : offset + limit],
                },
                "figure": report.get("figure"),
            }
