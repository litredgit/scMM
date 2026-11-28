"""Authenticated access to workbench reference documents."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/api/v1", tags=["documentation"])
DOCUMENTS = frozenset(
    {
        "README.md",
        "AGENTS.md",
        "CHANGELOG.md",
        "docs/README.md",
        "docs/deployment.md",
        "docs/development.md",
        "docs/internal-reference.md",
        "docs/method-plugins.md",
        "docs/appendix/README.md",
        "docs/appendix/lipid-rule-review.md",
        "docs/appendix/statistical-method-notes.md",
        "docs/validation/README.md",
    }
)


@router.get("/documentation/{name:path}")
def document(name: str):
    if name not in DOCUMENTS:
        raise HTTPException(404, "文档不可用。")
    checkout = Path(__file__).resolve().parents[3]
    root = (
        checkout
        if (checkout / "pyproject.toml").is_file()
        else (Path(__file__).resolve().parents[2] / "resources/workbench_docs")
    )
    path = root / name
    try:
        if path.resolve(strict=True) != path or not path.is_file():
            raise FileNotFoundError
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(404, "文档不可用。") from None
    return Response(content, media_type="text/plain")
