"""Authenticated module import/export, revision checks and feature-only boundaries."""

import base64
import io
import json
import zipfile

import numpy as np
import pytest
from anndata import AnnData

from tests.support.workflow import get


def test_independent_matrix_import_and_complete_export(workflow):
    client, headers, _, _, _, _, _, current, post = workflow
    imported = post(
        "/exchange/statistics/import",
        {
            "format": "matrix_csv",
            "matrix_csv": "Sample,Class,100.5,200.5\na,A,0,2\nb,B,3,4\n",
            "observation_kind": "sample",
        },
    )
    assert imported.status_code == 200, imported.text
    status = get(workflow, "/exchange/statistics/status")
    assert status.json()["quantitation_available"]
    assert status.json()["observation_kind"] == "sample"
    revision = current()["revision"]
    package = client.get(
        "/api/v1/workspace/exchange/statistics/export",
        headers=headers,
        params={"revision": revision, "format": "package"},
    )
    assert package.status_code == 200, package.text
    assert ".scmm-exchange.zip" in package.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert "manifest.json" in archive.namelist()
        assert "project/project.json" in archive.namelist()
    stale = client.get(
        "/api/v1/workspace/exchange/statistics/export",
        headers=headers,
        params={"revision": revision - 1},
    )
    assert stale.status_code == 409
    imported_again = post(
        "/exchange/annotation/import",
        {"format": "package", "file_base64": base64.b64encode(package.content).decode()},
    )
    assert imported_again.status_code == 200, imported_again.text
    assert current()["project"]["dataset"]["cells"] == 2


def test_feature_table_disables_numeric_operations_and_retains_failed_state(workflow):
    _, _, _, _, _, _, _, current, post = workflow
    result = post(
        "/exchange/annotation/import",
        {"format": "feature_csv", "matrix_csv": "feature_id,mz\nx,150.25\ny,300.5\n"},
    )
    assert result.status_code == 200, result.text
    status = get(workflow, "/exchange/annotation/status").json()
    assert status["feature_only"]
    assert not status["quantitation_available"]
    renamed = post(
        "/analysis/annotations/apply",
        {
            "content": "feature_id,name\nx,feature x\n",
            "format": "csv",
            "mapping": {"name": "display_name"},
            "source_key": "feature_id",
            "target_key": "feature_id",
            "mode": "key",
        },
    )
    assert renamed.status_code == 200, renamed.text
    inspected = get(workflow, "/analysis/data-inspection").json()
    assert inspected["observations"] == 0
    assert inspected["feature_rows"][0]["name"] == "feature x"
    before = current()
    failed = post("/analysis/operation", {"operation": "normalize", "options": {"method": "total"}})
    assert failed.status_code == 400, failed.text
    assert current() == before
    save = post("/project/save")
    assert save.status_code == 200, save.text


def test_invalid_archive_does_not_replace_current_project(workflow):
    _, _, _, _, _, _, _, current, post = workflow
    before = current()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../outside", "malicious")
    failed = post(
        "/exchange/extraction/import",
        {"format": "package", "file_base64": base64.b64encode(stream.getvalue()).decode()},
    )
    assert failed.status_code == 400, failed.text
    assert current() == before
    failed = post(
        "/exchange/statistics/import", {"format": "matrix_csv", "file_base64": "bad base64"}
    )
    assert failed.status_code == 400
    assert current() == before


@pytest.mark.parametrize(
    "metadata",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": 1, "observation_kind": "unknown"},
    ],
)
def test_invalid_observation_declaration_rejects_before_publishing(workflow, metadata):
    _, _, _, _, output, _, _, current, post = workflow
    data = AnnData(np.ones((2, 2)))
    data.uns["scmm_exchange_json"] = json.dumps(metadata)
    data.write_h5ad(output / "invalid-unit.h5ad")
    before = current()
    failed = post("/dataset/import", {"root": "Output", "path": "invalid-unit.h5ad"})
    assert failed.status_code == 400, failed.text
    assert current() == before
