"""Independent import and export boundaries for the three scientific modules."""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from scMM.application.module_exchange import (
    export_exchange,
    import_exchange,
    module_status,
)

from ..exchange_schemas import ExchangeImport, ModuleName
from ..schemas import WorkspaceView
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1/workspace/exchange", tags=["module exchange"])


@router.get("/{module}/status")
def status(module: ModuleName, manager: Service, identity: Identity):
    return module_status(manager, identity, module)


@router.post("/{module}/import", response_model=WorkspaceView)
def import_data(module: ModuleName, body: ExchangeImport, manager: Service, identity: Identity):
    return import_exchange(manager, identity, module, body.model_dump())


@router.get("/{module}/export")
def export_data(
    module: ModuleName,
    manager: Service,
    identity: Identity,
    revision: int = Query(ge=0),
    format: Literal["package", "csv", "h5ad", "features"] = "package",
):
    content, media, filename = export_exchange(manager, identity, module, revision, format)
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
