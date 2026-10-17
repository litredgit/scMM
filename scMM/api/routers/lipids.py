"""Lipid MS1 annotation, natural isotope review and filtered downloads."""

from fastapi import APIRouter
from fastapi.responses import Response

from .. import lipid_schemas as s
from ..schemas import RevisionRequest
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1/workspace/lipids", tags=["lipids"])


@router.get("")
def info(manager: Service, identity: Identity):
    return manager.lipid_info(identity)


@router.post("/database")
def database(body: RevisionRequest, manager: Service, identity: Identity):
    return manager.lipid_prepare(identity, body.revision)


@router.post("/run")
def run(body: s.LipidRun, manager: Service, identity: Identity):
    return manager.lipid_run(
        identity, body.revision, body.options.model_dump(), body.rules, body.label
    )


@router.post("/rules/import")
def import_rules(body: s.LipidRulesImport, manager: Service, identity: Identity):
    return manager.lipid_import_rules(identity, body.revision, body.content, body.format)


@router.post("/rules/apply")
def apply_rules(body: s.LipidRulesApply, manager: Service, identity: Identity):
    return manager.lipid_apply_rules(identity, body.revision, body.version, body.rules)


@router.post("/presets")
def preset(body: s.LipidPreset, manager: Service, identity: Identity):
    return manager.lipid_preset(identity, body.revision, body.name, body.rules)


@router.post("/activate")
def activate(body: s.LipidActivate, manager: Service, identity: Identity):
    return manager.lipid_activate(identity, body.revision, body.version)


@router.post("/review")
def review(body: s.LipidReview, manager: Service, identity: Identity):
    return manager.lipid_review(identity, body.revision, body.model_dump())


@router.post("/query")
def query(body: s.LipidQuery, manager: Service, identity: Identity):
    return manager.lipid_query(identity, body.revision, body.model_dump())


@router.post("/charts")
def charts(body: s.LipidCharts, manager: Service, identity: Identity):
    return manager.lipid_charts(
        identity, body.revision, body.version, body.filters.model_dump(), body.view.model_dump()
    )


@router.post("/charts/save")
def save_charts(body: s.LipidCharts, manager: Service, identity: Identity):
    return manager.lipid_chart_view(
        identity, body.revision, body.version, body.filters.model_dump(), body.view.model_dump()
    )


@router.post("/representative")
def representative(body: s.LipidRepresentative, manager: Service, identity: Identity):
    return manager.lipid_representative(
        identity, body.revision, body.version, body.database_id, body.feature_id
    )


@router.post("/export")
def export(body: s.LipidExport, manager: Service, identity: Identity):
    content, media = manager.lipid_export(
        identity,
        body.revision,
        body.version,
        body.filters.model_dump(),
        body.kind,
        body.view.model_dump(),
    )
    extension = "json" if body.kind in {"rules", "charts"} else "csv"
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="lipid-{body.kind}.{extension}"'},
    )
