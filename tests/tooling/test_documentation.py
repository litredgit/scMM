"""Local links/anchors and executable examples, restricted to affected guides."""

import ast
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_FILES = (
    [ROOT / p for p in json.loads(os.environ["SCMM_DOCUMENTS"])]
    if "SCMM_DOCUMENTS" in os.environ
    else [*ROOT.glob("*.md"), *sorted((ROOT / "docs").glob("*.md"))]
)


def anchors(text):
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    result, counts = set(), {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        result.add(f"{slug}-{number}" if number else slug)
    result.update(re.findall(r'(?:id|name)=["\']([^"\']+)["\']', text))
    return result


@pytest.mark.parametrize("path", MARKDOWN_FILES, ids=lambda path: path.name)
def test_guide_links_anchors_and_python_examples(path):
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        file, _, anchor = unquote(target).partition("#")
        destination = path.parent / file if file else path
        assert destination.exists(), f"Broken link in {path}: {target}"
        if anchor and destination.suffix == ".md":
            assert anchor in anchors(destination.read_text(encoding="utf-8")), (
                f"Broken anchor in {path}: {target}"
            )
    for index, source in enumerate(re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL), 1):
        ast.parse(source, filename=f"{path}:python-block-{index}")
