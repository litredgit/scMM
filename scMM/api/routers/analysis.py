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
