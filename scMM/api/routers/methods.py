"""Authenticated API for public method execution and read-only reports."""

from fastapi import APIRouter, Query, Response
from pydantic import Field

from ..schemas import RevisionRequest
from .projects import Identity, Service

router = APIRouter(prefix="/api/v1/workspace/methods", tags=["methods"])


class MethodRun(RevisionRequest):
    method_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}:[a-z][a-z0-9_-]{0,63}$")
    version: str = Field(min_length=1, max_length=128)
    options: dict = Field(default_factory=dict, max_length=64)
    layer: str | None = Field(default=None, max_length=250)
    embedding: str | None = Field(default=None, max_length=250)
    output_key: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=128)
    preview: bool = False


@router.post("/run")
def run(body: MethodRun, manager: Service, identity: Identity):
    return manager.run_method(identity, **body.model_dump())


@router.get("/reports/{key}")
def report(
    key: str,
    manager: Service,
    identity: Identity,
    download: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    value = manager.method_result(identity, key, offset=offset, limit=limit, download=download)
    if download:
        filename = key.replace(":", "-") + ".csv"
        return Response(
            value,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    return value
