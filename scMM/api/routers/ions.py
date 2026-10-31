"""Ion workflows: explicit endpoints, owner checks and revisioned mutations."""

import base64
import json
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from .. import ion_schemas as s
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1/workspace/ions", tags=["ions"])


@router.get("/info")
def info(manager: Service, identity: Identity):
    return manager.ion_info(identity)


@router.post("/initialize")
def initialize(body: s.Initialize, manager: Service, identity: Identity):
    return manager.ion_initialize(identity, **body.model_dump())


@router.post("/run")
def run(body: s.Run, manager: Service, identity: Identity):
    return manager.ion_run(identity, **body.model_dump())


@router.get("/status")
def status(job_id: str, manager: Service, identity: Identity):
    return manager.ion_job(identity, job_id)


@router.post("/cancel")
def cancel(body: s.Job, manager: Service, identity: Identity):
    with manager.access(identity) as workspace:
        workspace.check(body.revision)
    value = manager.ion_job(identity, body.job_id, cancel=True)
    return {"workspace": manager.current(identity), "value": value}


@router.post("/collect")
def collect(body: s.Job, manager: Service, identity: Identity):
    return manager.ion_collect(identity, **body.model_dump())


@router.post("/review")
def review(body: s.Review, manager: Service, identity: Identity):
    return manager.ion_review(identity, **body.model_dump())


@router.post("/represent")
def represent(body: s.Represent, manager: Service, identity: Identity):
    return manager.ion_represent(identity, **body.model_dump())


@router.post("/annotate")
def annotate(body: s.Annotate, manager: Service, identity: Identity):
    return manager.ion_annotate(identity, **body.model_dump())


@router.post("/evidence")
def evidence(body: s.Evidence, manager: Service, identity: Identity):
    return manager.ion_evidence(identity, **body.model_dump())


@router.post("/activate")
def activate(body: s.Activate, manager: Service, identity: Identity):
    from scMM.application.data_views import activate_view

    return manager._ion_mutate(
        identity,
        body.revision,
        lambda project: activate_view(
            project,
            body.view_id,
            branch_id=body.branch_id,
            expected_catalog_revision=body.catalog_revision,
        ),
    )


@router.post("/availability")
def availability(body: s.Availability, manager: Service, identity: Identity):
    from scMM.ion.representation import preview_complete_availability

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        project = workspace.require_project()
        source = project.ion_state["source_matrices"][body.view_id]
        return {
            "workspace": manager.view(workspace),
            "value": preview_complete_availability(
                source, cell_ids=body.cell_ids, variable_ids=body.variable_ids
            ),
        }


@router.post("/materialize")
def materialize(body: s.Materialize, manager: Service, identity: Identity):
    from scMM.application.data_views import materialize_analysis_branch

    return manager._ion_mutate(
        identity,
        body.revision,
        lambda project: materialize_analysis_branch(
            project, view_id=body.view_id, preview=body.preview
        ),
    )


@router.post("/compare")
def compare(body: s.Compare, manager: Service, identity: Identity):
    from scMM.application.analysis_inputs import compare_views

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        return {
            "workspace": manager.view(workspace),
            "value": compare_views(
                workspace.require_project(), **body.model_dump(exclude={"revision"})
            ),
        }


@router.post("/shared-normalization")
def shared(body: s.SharedNormalization, manager: Service, identity: Identity):
    from scMM.application.analysis_inputs import apply_shared_normalization

    return manager._ion_mutate(
        identity,
        body.revision,
        lambda project: apply_shared_normalization(project.workspace, body.factors),
    )


@router.post("/replicates")
def replicates(body: s.Replicate, manager: Service, identity: Identity):
    from scMM.application.analysis_inputs import replicate_summary

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        table = replicate_summary(
            workspace.require_project().workspace.require_data(),
            **body.model_dump(exclude={"revision"}),
        )
        return Response(
            table.to_csv(index=False),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="replicate-summary.csv"'},
        )


@router.get("/table")
def table(
    manager: Service,
    identity: Identity,
    version: str = "",
    kind: Literal[
        "relations",
        "groups",
        "diagnostics",
        "candidates",
        "unknown",
        "evidence",
        "reviews",
        "representations",
    ] = "relations",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
):
    return manager.ion_table(identity, version=version, kind=kind, offset=offset, limit=limit)


@router.get("/download")
def download(
    manager: Service,
    identity: Identity,
    kind: Literal["version", "annotation", "bundle", "source_l2", "registry"],
    key: str = "",
    revision: int = Query(ge=0),
):
    from scMM.application.data_views import freeze_active_branch
    from scMM.application.web_ions import grouping_version
    from scMM.file.ion_bundle import export_project_bundle
    from scMM.file.ion_view import export_compound_source

    with manager.access(identity) as workspace:
        workspace.check(revision)
        project = workspace.require_project()
        if kind == "bundle":
            content = export_project_bundle(project)
            filename, media = "ion-project.zip", "application/zip"
        elif kind == "source_l2":
            content = export_compound_source(project, key)
            filename, media = "compound-source.h5ad", "application/octet-stream"
        else:
            registry = freeze_active_branch(project)["registry"]
            value = (
                grouping_version(project, key)
                if kind == "version"
                else registry["annotation"][key]
                if kind == "annotation"
                else registry
            )
            content = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            filename, media = "ion-evidence.json", "application/json"
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/import")
def import_data(body: s.Import, manager: Service, identity: Identity):
    from scMM.application.data_view_storage import install_catalog_state
    from scMM.file.ion_bundle import import_project_bundle
    from scMM.file.ion_view import import_compound_source

    content = base64.b64decode(body.content_base64, validate=True)

    def apply(project):
        if body.kind == "source_l2":
            return import_compound_source(project, content, max_bytes=75_000_000)
        if project.ion_state is not None or project.workspace.data is not None:
            raise ValueError("import a complete project bundle into an empty project")
        candidate = import_project_bundle(content, max_bytes=75_000_000)
        install_catalog_state(project, candidate["state"])
        return {"imported": "complete_bundle", "models_included": False}

    return manager._ion_mutate(identity, body.revision, apply)


@router.post("/evidence/preview")
def evidence_preview(body: s.EvidenceLink, manager: Service, identity: Identity):
    from scMM.ion.evidence import link_external_evidence

    with manager.access(identity) as workspace:
        workspace.check(body.revision)
        registry = workspace.require_project().ion_state["registry"]
        records = [registry["evidence"][key] for key in body.evidence_ids]
        preview = link_external_evidence(records, body.targets, mapping=body.mapping, ppm=body.ppm)
        return {"workspace": manager.view(workspace), "value": preview}


@router.post("/assertion")
def assertion(body: s.Assertion, manager: Service, identity: Identity):
    from datetime import UTC, datetime

    from scMM.application.identity import actor
    from scMM.ion.evidence import identification_assertion
    from scMM.ion.identity import json_identity

    def apply(project):
        registry = project.ion_state["registry"]
        if not body.evidence_ids or any(
            key not in registry["evidence"] for key in body.evidence_ids
        ):
            raise ValueError("identification assertion requires imported evidence")
        kind = body.target.get("kind")
        version = body.target.get("version")
        target = body.target.get("id")
        if kind == "candidate":
            rows = registry["annotation"].get(version, {}).get("candidates", [])
            valid = any(row["candidate_id"] == target for row in rows)
        elif kind == "feature":
            valid = any(
                target in root["data"].var_names and version == key
                for key, root in project.ion_state["roots"].items()
            )
        elif kind == "ec":
            valid = any(
                row["ec_id"] == target
                for row in registry["grouping"]
                .get(version, {})
                .get("grouping", {})
                .get("groups", [])
            )
        else:
            valid = False
        if not valid:
            raise ValueError("assertion target/version is unavailable")
        result = identification_assertion(**body.model_dump(exclude={"revision", "target"}))
        result.update(
            target=body.target,
            reviewer=(actor.get() or {}).get("id", "local-api"),
            timestamp=datetime.now(UTC).isoformat(),
        )
        key = json_identity(result)
        registry.setdefault("identification_assertions", {})[key] = result
        project.ion_state["revision"] += 1
        return {"assertion_id": key, **result}

    return manager._ion_mutate(identity, body.revision, apply)


@router.post("/merge-compounds")
def merge_compounds(body: s.CompoundMerge, manager: Service, identity: Identity):
    from uuid import uuid4

    from scMM.application.data_views import DataViewCatalog, freeze_active_branch
    from scMM.application.ion_merge import merge_compound_sources
    from scMM.ion.identity import dataset_identity

    def apply(project):
        state = freeze_active_branch(project)
        sources = []
        for key in body.view_ids:
            view = state["views"][key]
            if view["level"] != "L2":
                raise ValueError("compound merge requires only L2 sources")
            sources.append(
                {
                    "source_id": key,
                    "root_id": view["root_id"],
                    "view_id": key,
                    "data": state["source_matrices"][key],
                }
            )
        data, provenance = merge_compound_sources(sources, body.alignments)
        key = uuid4().hex
        view = {
            "schema_version": 1,
            "id": key,
            "root_id": "composite-" + provenance["merge_id"],
            "root_identity": provenance["merge_id"],
            "root_available": False,
            "level": "L2",
            "variable_kind": "empirical_compound",
            "cell_ids": list(data.obs_names),
            "variable_ids": list(data.var_names),
            "feature_ids": [],
            "source_identity": dataset_identity(data, allow_missing=True),
            "grouping_id": None,
            "quantification_id": provenance["merge_id"],
            "source_views": body.view_ids,
        }
        state["views"][key] = view
        state["source_matrices"][key] = data
        state["registry"].setdefault("compound_merges", {})[provenance["merge_id"]] = provenance
        state["revision"] += 1
        DataViewCatalog.from_state(state)
        project.ion_state = state
        return view

    return manager._ion_mutate(identity, body.revision, apply)
