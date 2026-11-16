"""Analysis and publication-export boundaries."""
# ruff: noqa: RUF001

from typing import Literal

from fastapi import APIRouter, Query, Request, Response

from .. import workflow_schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/workspace/analysis/cell-spectra")
def spectra(body: s.CellSpectra, manager: Service, identity: Identity):
    from scMM.application.cell_spectra import cell_spectra

    return cell_spectra(manager, identity, **body.model_dump())


def _check_figure_identity(metadata, manager, identity):
    if not isinstance(metadata, dict):
        raise ValueError("图的来源身份格式无效。")
    if metadata.get("result_identity_valid") is False:
        raise ValueError("图的计算结果身份不明或已失效，请重新绘图。")
    if not any(
        metadata.get(key)
        for key in ("dataset_token", "result_name", "sample_id", "time_result_key")
    ):
        return
    with manager.access(identity) as workspace:
        project = workspace.require_project()
        if metadata.get("time_result_key"):
            from scMM.util.time_results import valid_time_figure

            if not valid_time_figure(project.workspace.require_data(), metadata):
                raise ValueError("时间结果或作图输入已过期，请重新计算/绘图")
        if metadata.get("result_name"):
            if not isinstance(metadata["result_name"], str):
                raise ValueError("图的计算结果身份格式无效。")
            from scMM.application.result_catalog import project_result_identities

            expected = project_result_identities(project).get(metadata["result_name"])
            if not expected or expected != metadata.get("result_identity"):
                raise ValueError("图的计算结果已改变，请重新绘图。")
        if (
            metadata.get("dataset_token")
            and list(project.workspace.token) != metadata["dataset_token"]
        ):
            raise ValueError("图形已过期，请基于当前数据重新绘图。")
        if metadata.get("sample_id"):
            from scMM.application.preview_cache import file_identity

            sample = manager.sample(project, metadata["sample_id"])
            path = manager.storage.resolve_raw_file(sample["storage"], sample["path"])
            if not isinstance(metadata.get("input_identity"), dict):
                raise ValueError("原始图的输入身份格式无效，请重新读取。")
            expected = {key: str(value) for key, value in file_identity(path).items()}
            supplied = {key: str(value) for key, value in metadata["input_identity"].items()}
            if expected != supplied:
                raise ValueError("原始文件已改变，请重新读取后下载。")


@router.post("/workspace/figures/check", status_code=204)
def figure_check(body: s.FigureIdentity, request: Request, manager: Service):
    _check_figure_identity(body.metadata, manager, request.headers.get("x-scmm-workspace", ""))
    return Response(status_code=204)


@router.post("/workspace/figures/data")
def figure_data(body: s.FigureData, request: Request, manager: Service):
    _check_figure_identity(
        body.figure.get("layout", {}).get("meta") or {},
        manager,
        request.headers.get("x-scmm-workspace", ""),
    )
    from scMM.plot.export import data_archive

    return Response(data_archive(body.figure), media_type="application/zip")


@router.post("/workspace/figures/pdf")
def figure_pdf(body: s.FigurePDF, request: Request, manager: Service):
    _check_figure_identity(body.identity, manager, request.headers.get("x-scmm-workspace", ""))
    from scMM.plot.export import publication_pdf

    return Response(
        publication_pdf(body.svg, body.width_mm, body.height_mm, font_family=body.font_family),
        media_type="application/pdf",
    )


@router.get("/workspace/analysis")
def analysis(manager: Service, identity: Identity):
    return manager.analysis_info(identity)


@router.get("/workspace/analysis/annotated-features")
def annotated_features(manager: Service, identity: Identity):
    from scMM.util.lipid_annotation import annotation_store, version_valid

    with manager.access(identity) as workspace:
        data = workspace.require_project().workspace.require_data()
        store = annotation_store(data)
        version = next((v for v in store["versions"] if v["id"] == store.get("active")), None)
        if not version or not version_valid(data, version):
            raise ValueError("请先计算并激活当前数据的注释。")
        ids = list(
            dict.fromkeys(
                row["feature_id"]
                for row in version["candidates"]
                if row["feature_id"] in data.var_names
            )
        )
        return {"features": ids, "source": "active_annotation_candidates", "summed": False}


@router.get("/workspace/analysis/features")
def features(
    manager: Service,
    identity: Identity,
    query: str = Query(default="", max_length=1000),
    sort: Literal["mean", "total", "median", "detection", "mz", "name"] = "mean",
    descending: bool = True,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    return manager.feature_choices(
        identity, query=query, sort=sort, descending=descending, offset=offset, limit=limit
    )


@router.get("/workspace/analysis/qc")
def qc(manager: Service, identity: Identity):
    return manager.qc_view(identity)


@router.get("/workspace/analysis/figures/{key}")
def saved_figure(key: str, manager: Service, identity: Identity):
    return manager.saved_figure(identity, key)


@router.post("/workspace/analysis/operation")
def operation(body: s.Operation, manager: Service, identity: Identity):
    options = s.options_for(s.OPERATIONS[body.operation], body.options)
    return manager.run_operation(
        identity, body.revision, body.operation, options, preview=body.preview
    )


@router.post("/workspace/analysis/invalidate")
def invalidate(body: s.Invalidate, manager: Service, identity: Identity):
    return manager.invalidate_results(identity, body.revision, body.names)


@router.get("/workspace/analysis/results/{name}")
def result(
    name: Literal["differential", "markers", "network", "supervised", "shap"],
    manager: Service,
    identity: Identity,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    return manager.result_view(identity, name, offset, limit)


@router.post("/workspace/analysis/plot")
def plot(body: s.Plot, manager: Service, identity: Identity):
    options = s.options_for(s.PLOTS.get(body.kind, s.Controls), body.options)
    return manager.analysis_plot(identity, body.revision, body.kind, options)


@router.get("/workspace/analysis/time")
def time_info(
    manager: Service,
    identity: Identity,
    query: str = Query(default="", max_length=256),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    return manager.time_info(identity, query=query, offset=offset, limit=limit)


@router.post("/workspace/analysis/time")
def time_operation(body: s.TimeOperation, manager: Service, identity: Identity):
    options = s.options_for(
        {
            "palantir": s.TimePalantir,
            "trajectory": s.TimeTrajectory,
            "velocity": s.TimeVelocity,
            "trends": s.TimeTrends,
            "trend_clusters": s.TimeTrendClusters,
        }[body.operation],
        body.options,
    )
    return manager.run_time(identity, body.revision, body.operation, options)


@router.get("/workspace/analysis/time/download")
def time_download(manager: Service, identity: Identity, key: str):
    return Response(
        manager.time_download(identity, key),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="scmm-time-result.zip"'},
    )


@router.get("/workspace/analysis/time/result")
def time_result(manager: Service, identity: Identity, key: str):
    return manager.time_result(identity, key)


@router.put("/workspace/analysis/settings")
def settings(body: s.ViewSettings, manager: Service, identity: Identity):
    return manager.save_view_settings(identity, body.revision, body.analysis, body.legend)


@router.post("/workspace/analysis/selection-labels")
def selection_labels(body: s.SelectionLabel, manager: Service, identity: Identity):
    from scMM.application.selection_labels import update
    from scMM.application.web_projects import project_candidate

    with manager.access(identity, operation="selection_labels") as workspace:
        workspace.check(body.revision)
        candidate = project_candidate(workspace.require_project())
        update(candidate.workspace, **body.model_dump(exclude={"revision"}))
        candidate.saved_reports = {}
        candidate.views.pop("figures", None)
        candidate.dirty = True
        candidate.report_token = candidate.workspace.token
        workspace.project = candidate
        workspace.revision += 1
        return manager.view(workspace)


@router.get("/workspace/analysis/selection-labels")
def selection_info(manager: Service, identity: Identity):
    import json

    from scMM.application.selection_labels import source

    with manager.access(identity) as workspace:
        state = workspace.require_project().workspace
        data = source(state)
        return {
            "labels": json.loads(data.uns.get("scmm_selection_json", "{}")),
            "cells": data.n_obs,
            "features": data.n_vars,
        }


@router.post("/workspace/analysis/annotations/{action}")
def annotation_table(
    action: Literal["preview", "apply"],
    body: s.AnnotationTable,
    manager: Service,
    identity: Identity,
):
    import json

    from scMM.analysis.external_annotations import align_annotations, read_table, write_annotations
    from scMM.application.web_projects import project_candidate
    from scMM.application.web_support import table_view

    frame = read_table(
        body.content, format=body.format, header=body.header, transpose=body.transpose
    )
    with manager.access(identity, operation="manual_annotations") as workspace:
        workspace.check(body.revision)
        project = workspace.require_project()
        if project.workspace._selection_source is not None:
            raise ValueError("请先关闭全部标签筛选，再导入注释。")
        table, matched = align_annotations(
            project.workspace.require_data(),
            frame,
            **body.model_dump(
                include={"mapping", "source_key", "target_key", "ppm", "mode", "row_positions"}
            ),
        )
        if action == "preview":
            return {
                "workspace": manager.view(workspace),
                "value": {
                    "table": table_view(table),
                    "matched": int(matched.sum()),
                    "ambiguous": int((table.status == "ambiguous").sum()),
                    "unmatched": int((table.status == "unmatched").sum()),
                },
            }
        candidate = project_candidate(project)
        candidate.workspace.data = write_annotations(
            candidate.workspace.data,
            table,
            matched,
            mapping=body.mapping,
            clear_unmatched=body.clear_unmatched,
        )
        # The reset origin receives matching annotations by stable feature ID.
        baseline = candidate.workspace._original
        for key in body.mapping.values():
            values = (
                baseline.var[key].astype(object).copy()
                if key in baseline.var
                else __import__("pandas").Series("", index=baseline.var_names, dtype=object)
            )
            common = baseline.var_names.intersection(candidate.workspace.data.var_names)
            values.loc[common] = candidate.workspace.data.var.loc[common, key]
            baseline.var[key] = values
        records = json.loads(candidate.workspace.data.uns.get("scmm_manual_annotations_json", "[]"))
        import hashlib

        records.append(
            {
                "source_sha256": hashlib.sha256(body.content.encode()).hexdigest(),
                "mapping": body.mapping,
                "mode": body.mode,
                "source_key": body.source_key,
                "target_key": body.target_key,
                "ppm": body.ppm,
                "matched": int(matched.sum()),
                "clear_unmatched": body.clear_unmatched,
            }
        )
        candidate.workspace.data.uns["scmm_manual_annotations_json"] = json.dumps(records)
        candidate.views.pop("figures", None)
        candidate.dirty = True
        workspace.project = candidate
        workspace.revision += 1
        return {"workspace": manager.view(workspace), "value": {"matched": int(matched.sum())}}


@router.post("/workspace/analysis/msms")
def msms(body: s.MSMSSearch, manager: Service, identity: Identity):
    from scMM.analysis.external_annotations import msms_search
    from scMM.application.web_support import figure_view
    from scMM.plot.presentation import style_figure

    with manager.access(identity, operation="msms_input") as workspace:
        workspace.check(body.revision)
        project = workspace.require_project()
        data = project.workspace.require_data().copy()
        token = project.workspace.token
    options = body.model_dump(exclude={"revision"})
    figure = msms_search(data, **options)
    figure.update_layout(
        meta={
            **figure.layout.meta,
            "dataset_token": list(token),
            "parameters": {k: v for k, v in options.items() if k not in {"measured", "library"}},
        }
    )
    value = figure_view(style_figure(figure))
    with manager.access(identity, operation="msms_collect") as workspace:
        workspace.check(body.revision)
        project = workspace.require_project()
        if token != project.workspace.token:
            raise ValueError("数据已改变，请重新运行 MS/MS 搜索。")
        project.views.setdefault("figures", {})["msms_evidence"] = value
        project.dirty = True
        workspace.revision += 1
        return {"workspace": manager.view(workspace), "value": value}


@router.post("/workspace/analysis/selection-plot")
def selection_plot(body: s.SelectionPlot, manager: Service, identity: Identity):
    import plotly.graph_objects as go

    from scMM.analysis.exploration import vector
    from scMM.application.selection_labels import source
    from scMM.application.web_support import figure_view

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        state = workspace.require_project().workspace
        data = source(state)
        if data.n_obs > 100000:
            raise ValueError("圈选图最多 10 万个细胞，请先使用分组或稳定编号选择。")
        x, _ = vector(data, body.x)
        y, _ = vector(data, body.y)
        figure = go.Figure(
            go.Scattergl(
                x=x,
                y=y,
                mode="markers",
                customdata=[[str(v)] for v in data.obs_names],
                marker={"size": 5},
                hovertemplate="Cell: %{customdata[0]}<br>x: %{x}<br>y: %{y}<extra></extra>",
            )
        )
        figure.update_layout(
            title="Cell selection",
            xaxis_title=body.x,
            yaxis_title=body.y,
            dragmode="lasso",
            meta={"dataset_token": list(state.token), "point_kind": "cell_selection"},
        )
        return {"workspace": manager.view(workspace), "value": figure_view(figure)}
