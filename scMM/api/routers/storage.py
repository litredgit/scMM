from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Query

from scMM.application.parameters import ANALYSIS_SPECS, PROCESSING_HELP
from scMM.application.storage import SUPPORTED_RAW_SUFFIXES

from .. import schemas as s
from .projects import Service

router = APIRouter(prefix="/api/v1", tags=["storage", "parameters"])


@router.get("/configuration", response_model=s.ConfigurationView)
def configuration(manager: Service):
    defaults = asdict(manager.defaults.processing)
    return {
        "storage": [
            {"label": root.label, "path": str(root.path)} for root in manager.storage.roots
        ],
        "results": [
            {"label": root.label, "path": str(root.path)} for root in manager.results.roots
        ],
        "project_root": str(manager.store.root),
        "processing": [
            {"name": key, "default": value, "help": PROCESSING_HELP[key]}
            for key, value in defaults.items()
        ],
        "analysis": [
            {"name": key, "default": value, "help": ANALYSIS_SPECS[key][3]}
            for key, value in manager.defaults.analysis.items()
        ],
        "workspace_idle_seconds": manager.idle_seconds,
    }


@router.get("/storage/entries", response_model=s.DirectoryView)
def browse(
    manager: Service,
    root: str,
    path: str = ".",
    kind: Literal["raw", "results"] = "raw",
    search: str = Query(default="", max_length=1000),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    catalog = manager.storage if kind == "raw" else manager.results
    directory = catalog.resolve(root, path)
    if not directory.is_dir():
        raise ValueError("请选择目录。")
    entries = []
    suffixes = SUPPORTED_RAW_SUFFIXES if kind == "raw" else {".h5ad"}
    for child in directory.iterdir():
        try:
            resolved = catalog.resolve(root, child)
            is_directory = resolved.is_dir()
            if search.casefold() not in child.name.casefold() or (
                not is_directory
                and (not resolved.is_file() or resolved.suffix.lower() not in suffixes)
            ):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(child.relative_to(catalog.root(root).path)),
                    "directory": is_directory,
                    "bytes": None if is_directory else resolved.stat().st_size,
                }
            )
        except (OSError, ValueError):
            continue
    entries.sort(key=lambda entry: (not entry["directory"], entry["name"].casefold()))
    relative = directory.relative_to(catalog.root(root).path)
    return {
        "root": root,
        "path": str(relative),
        "parent": None if relative.parts == () else str(relative.parent),
        "entries": entries[offset : offset + limit],
        "total": len(entries),
    }
