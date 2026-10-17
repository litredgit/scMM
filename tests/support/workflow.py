"""HTTP migration parity, transactional state, task ownership and export boundaries."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from fastapi.testclient import TestClient

from scMM.api.app import create_app
from scMM.application.storage import StorageRoot
from scMM.application.trash import SavedItems
from tests.support.auth import auth_options, login_client
from tests.support.project import setup_project


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    raw, output, projects = [tmp_path / name for name in ("raw", "output", "projects")]
    for folder in (raw, output, projects):
        folder.mkdir()
    reference, _ = setup_project(raw)
    reference.manifest["parameters"].update(extraction_method="snr_v1", reference_ppm_tol=50.0)
    monkeypatch.setenv("SCMM_PREFERENCES", str(tmp_path / "preferences.json"))
    options, credential = auth_options(tmp_path)
    app = create_app(
        [StorageRoot("Raw", raw)],
        [StorageRoot("Output", output)],
        project_root=projects,
        static_root=None,
        **options,
    )
    manager = app.state.workspaces
    monkeypatch.setattr(
        manager,
        "saved_items",
        lambda: SavedItems(
            manager.store,
            [StorageRoot("Output", output)],
            active_paths=manager.active_paths,
            trash_root=tmp_path / "trash",
        ),
    )
    with TestClient(app, headers={"X-SCMM-Client": "web"}) as client:
        login_client(client, credential)
        identity = client.post("/api/v1/workspaces").json()["workspace_id"]
        headers = {"X-SCMM-Workspace": identity}
        client.post(
            "/api/v1/workspace/project",
            headers=headers,
            json={"revision": 0, "name": "HTTP workflow"},
        ).raise_for_status()

        def current():
            return client.get("/api/v1/workspace", headers=headers).json()

        def post(path, values=None, method="POST"):
            return client.request(
                method,
                f"/api/v1/workspace{path}",
                headers=headers,
                json={"revision": current()["revision"], **(values or {})},
            )

        yield client, headers, manager, raw, output, projects, reference, current, post


def import_data(workflow):
    _, _, _, _, output, _, _, _, post = workflow
    rng = np.random.default_rng(12)
    data = AnnData(
        rng.uniform(1, 10, (64, 8)),
        obs=pd.DataFrame(
            {
                "sample": np.repeat([f"s{i}" for i in range(8)], 8),
                "group": ["a"] * 32 + ["b"] * 32,
                "subject": np.repeat([f"s{i}" for i in range(8)], 8),
            },
            index=[f"c{i}" for i in range(64)],
        ),
        var=pd.DataFrame({"mz": np.arange(8.0) + 150}, index=[f"f{i}" for i in range(8)]),
    )
    data.X[:32, 0] *= 5
    data.write_h5ad(output / "data.h5ad")
    result = post("/dataset/import", {"root": "Output", "path": "data.h5ad"})
    assert result.status_code == 200, result.text
    return data


def get(workflow, path):
    return workflow[0].get(f"/api/v1/workspace{path}", headers=workflow[1])


def operation(workflow, name, options=None, preview=False):
    result = workflow[-1](
        "/analysis/operation", {"operation": name, "options": options or {}, "preview": preview}
    )
    assert result.status_code == 200, result.text
    return result.json()


def raw_samples(workflow):
    post = workflow[-1]
    assert post("/samples", {"root": "Raw", "paths": ["a.mzML", "b.mzML"]}).status_code == 200
    params = workflow[6].manifest["parameters"]
    assert post("/parameters", {"parameters": params}, "PUT").status_code == 200
    return workflow[-2]()["project"]["manifest"]["samples"]
