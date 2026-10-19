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


@router.post("/workspace/figures/data")
def figure_data(body: s.FigureData, request: Request, manager: Service):
    metadata = body.figure.get("layout", {}).get("meta") or {}
    if metadata.get("dataset_token"):
        identity = request.headers.get("x-scmm-workspace", "")
        with manager.access(identity) as workspace:
            if list(workspace.require_project().workspace.token) != metadata["dataset_token"]:
                raise ValueError("图形已过期，请基于当前数据重新绘图。")
    if metadata.get("sample_id") and metadata.get("input_identity"):
        from scMM.application.preview_cache import file_identity

        with manager.access(request.headers.get("x-scmm-workspace", "")) as workspace:
            sample = manager.sample(workspace.require_project(), metadata["sample_id"])
            path = manager.storage.resolve_raw_file(sample["storage"], sample["path"])
            if file_identity(path) != metadata["input_identity"]:
                raise ValueError("原始文件已改变，请重新读取后下载。")
    from scMM.plot.export import data_archive

    return Response(data_archive(body.figure), media_type="application/zip")


@router.post("/workspace/figures/pdf")
def figure_pdf(body: s.FigurePDF):
    from scMM.plot.export import publication_pdf

    return Response(
        publication_pdf(body.svg, body.width_mm, body.height_mm), media_type="application/pdf"
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


@router.put("/workspace/analysis/settings")
def settings(body: s.ViewSettings, manager: Service, identity: Identity):
    return manager.save_view_settings(identity, body.revision, body.analysis, body.legend)
