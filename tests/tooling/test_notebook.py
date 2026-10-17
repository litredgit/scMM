import ast
import json
import re
from pathlib import Path

NOTEBOOK_PATH = Path(__file__).resolve().parents[2] / "scMM_workflow.ipynb"


def test_workflow_notebook_is_clean_and_uses_project_kernel() -> None:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]

    assert notebook["metadata"]["kernelspec"] == {
        "display_name": "scMM",
        "language": "python",
        "name": "scmm",
    }
    assert "parameters" in code_cells[0].get("metadata", {}).get("tags", [])
    cell_ids = [cell.get("id") for cell in notebook["cells"]]
    assert all(cell_ids)
    assert len(cell_ids) == len(set(cell_ids))
    assert all(cell.get("execution_count") is None for cell in code_cells)
    assert all(not cell.get("outputs") for cell in code_cells)

    for index, cell in enumerate(code_cells):
        source = "".join(cell["source"])
        ast.parse(source, filename=f"{NOTEBOOK_PATH}:code-cell-{index}")
        assert "/home/" not in source
        assert not re.search(r"[A-Za-z]:[\\/]", source)
