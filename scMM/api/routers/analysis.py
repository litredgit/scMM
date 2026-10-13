"""Feature routes for the remaining five workbench stages."""

from typing import Literal

from fastapi import APIRouter, Query

from .. import workflow_schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.get("/workspace/analysis")
def analysis(manager: Service, identity: Identity):
    return manager.analysis_info(identity)


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
