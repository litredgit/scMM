"""Synthetic end-to-end grouping, review, views, annotations and persistence."""

import time

import numpy as np
import pandas as pd
from anndata import AnnData

from scMM.ion.semantics import unknown_state, write_value_states
from scMM.util.intensity import write_intensity_states
from tests.support.workflow import get


def prepare(workflow):
    _, _, _, _, output, _, _, _, post = workflow
    data = AnnData(
        np.tile([100.0, 10.0, 50.0, 7.0], (24, 1)) * np.arange(1, 25)[:, None],
        obs=pd.DataFrame(
            {"sample": ["s"] * 24, "group": ["a"] * 12 + ["b"] * 12},
            index=[f"c{i}" for i in range(24)],
        ),
        var=pd.DataFrame(
            {"mz": [101.007276452, 102.010631287, 122.989220702, 300.0]},
            index=["h", "iso", "na", "u"],
        ),
    )
    write_value_states(data, {"X": {**unknown_state(), "space": "linear_abundance"}})
    write_intensity_states(data, {"X": "raw"})
    data.write_h5ad(output / "ions.h5ad")
    response = post("/dataset/import", {"root": "Output", "path": "ions.h5ad"})
    response.raise_for_status()
    response = post(
        "/ions/initialize", {"linearity": "linear_abundance", "origin_kind": "imported_feature"}
    )
    assert response.status_code == 200, response.text
    return get(workflow, "/ions/info").json()["roots"][0]["id"]


def run_job(workflow, root):
    *_, post = workflow
    payload = {
        "root_id": root,
        "request_id": "first",
        "options": {"species": ["[M+H]+", "[M+Na]+"], "ppm": 5.0},
    }
    response = post("/ions/run", payload)
    assert response.status_code == 200, response.text
    task = response.json()["value"]["id"]
    assert post("/ions/run", payload).json()["value"]["id"] == task
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        row = get(workflow, f"/ions/status?job_id={task}").json()
        if row["status"] not in {"queued", "running"}:
            break
        time.sleep(0.1)
    assert row["status"] == "succeeded", row
    return task


def test_complete_ion_http_path(workflow):
    client, headers, manager, _, _, _, _, current, post = workflow
    root = prepare(workflow)
    task = run_job(workflow, root)
    response = post("/ions/collect", {"job_id": task})
    assert response.status_code == 200, response.text
    assert post("/ions/collect", {"job_id": task}).status_code == 400
    entry = manager._workspaces[current()["workspace_id"]].project.ion_state["registry"][
        "grouping"
    ][task]
    group = next(
        g for g in entry["grouping"]["groups"] if set(g["feature_ids"]) == {"h", "iso", "na"}
    )
    hypothesis = next(
        h
        for h in group["hypotheses"]
        if h["members"]["h"]["species_id"] == "[M+H]+"
        and h["members"]["h"]["isotope_shift"] == 0
        and h["members"]["iso"]["isotope_shift"] > 0
    )
    relation_ids = [
        r["relation_id"]
        for r in entry["grouping"]["relations"]
        if {r["left_feature_id"], r["right_feature_id"]}.issubset(set(group["feature_ids"]))
        and r["kind"] in {"isotope", "adduct"}
        and (r["kind"] != "isotope" or r["charge_magnitude"] == 1)
    ]
    response = post(
        "/ions/review",
        {
            "version": task,
            "kind": "group",
            "target_id": group["ec_id"],
            "hypothesis_id": hypothesis["hypothesis_id"],
            "relation_ids": relation_ids,
            "decision": "accepted",
            "reason": "synthetic known construction",
        },
    )
    assert response.status_code == 200, response.text
    response = post("/ions/represent", {"version": task})
    assert response.status_code == 200, response.text
    views = response.json()["value"]
    assert [row["view"]["level"] for row in views] == ["L1", "L2"]
    info = get(workflow, "/ions/info").json()
    l2 = views[1]
    response = post(
        "/ions/activate",
        {
            "view_id": l2["view"]["id"],
            "branch_id": l2["branch_id"],
            "catalog_revision": info["catalog_revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert current()["project"]["dataset"]["features"] == 2
    before = manager._workspaces[current()["workspace_id"]].project.workspace.data.X.copy()
    response = post(
        "/ions/annotate",
        {
            "root_id": root,
            "version": task,
            "namespace": "test",
            "records": [{"record_id": "one", "name": "known", "exact_mass": 100.0}],
            "species": ["[M+H]+"],
        },
    )
    assert response.status_code == 200, response.text
    version = response.json()["value"]["version"]
    assert get(workflow, f"/ions/table?kind=candidates&version={version}").json()["total"] >= 1
    response = post(
        "/ions/evidence",
        {
            "source_name": "manual",
            "records": [
                {
                    "kind": "experience",
                    "target": {"kind": "feature", "id": "h", "version": task},
                    "scope": {"samples": ["s"]},
                    "note": "synthetic",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    np.testing.assert_array_equal(
        before, manager._workspaces[current()["workspace_id"]].project.workspace.data.X
    )
    response = post("/project/save")
    assert response.status_code == 200, response.text
    path = current()["project"]["path"]
    response = post("/project/open", {"path": path})
    assert response.status_code == 200, response.text
    assert len(get(workflow, "/ions/info").json()["views"]) == 3
    response = get(workflow, f"/ions/download?kind=bundle&revision={current()['revision']}")
    assert response.status_code == 200, response.text
    assert response.content[:2] == b"PK"
    bad = client.post(
        "/api/v1/workspace/ions/run",
        headers=headers,
        json={
            "revision": current()["revision"],
            "root_id": root,
            "request_id": "bad",
            "options": {"arbitrary_command": "echo"},
        },
    )
    assert bad.status_code == 422


def test_stale_task_not_collected_and_cancel_idempotent(workflow):
    root = prepare(workflow)
    task = run_job(workflow, root)
    *_, post = workflow
    response = post("/analysis/operation", {"operation": "normalize", "options": {"method": "log"}})
    assert response.status_code == 200, response.text
    row = get(workflow, f"/ions/status?job_id={task}").json()
    assert not row["collectible"] and "changed" in row["reason"]
    assert post("/ions/collect", {"job_id": task}).status_code == 400
    assert post("/ions/cancel", {"job_id": task}).status_code == 200


def test_source_l2_import_materialization_ec_analysis_and_permissions(workflow):
    import base64

    client, headers, manager, _, _, _, _, current, post = workflow
    root = prepare(workflow)
    task = run_job(workflow, root)
    post("/ions/collect", {"job_id": task}).raise_for_status()
    response = post("/ions/represent", {"version": task})
    response.raise_for_status()
    view = next(row["view"] for row in response.json()["value"] if row["view"]["level"] == "L2")
    source = get(
        workflow, f"/ions/download?kind=source_l2&key={view['id']}&revision={current()['revision']}"
    )
    assert source.status_code == 200, source.text
    # A second workspace cannot query or cancel this owner's first workspace task.
    other = client.post("/api/v1/workspaces").json()["workspace_id"]
    denied = client.get(
        f"/api/v1/workspace/ions/status?job_id={task}",
        headers={**headers, "X-SCMM-Workspace": other},
    )
    assert denied.status_code == 400
    post("/project", {"name": "source-only"}).raise_for_status()
    response = post(
        "/ions/import",
        {"kind": "source_l2", "content_base64": base64.b64encode(source.content).decode()},
    )
    assert response.status_code == 200, response.text
    info = get(workflow, "/ions/info").json()
    assert info["roots"] == [] and info["branches"] == []
    imported = info["views"][0]
    response = post(
        "/ions/availability", {"view_id": imported["id"], "cell_ids": imported["cell_ids"]}
    )
    response.raise_for_status()
    preview = response.json()["value"]
    response = post("/ions/materialize", {"view_id": imported["id"], "preview": preview})
    response.raise_for_status()
    branch = response.json()["value"]
    info = get(workflow, "/ions/info").json()
    response = post(
        "/ions/activate",
        {
            "view_id": imported["id"],
            "branch_id": branch,
            "catalog_revision": info["catalog_revision"],
        },
    )
    response.raise_for_status()
    project = manager._workspaces[current()["workspace_id"]].project
    training_layer = project.workspace.data.uns["scmm_workbench"]["original_layer"]
    for operation, options in [
        ("reduce", {"method": "pca", "n_components": 2, "store_key": "X_compound"}),
        (
            "cluster",
            {
                "method": "kmeans",
                "n_clusters": 2,
                "key": "cluster_compound",
                "use_rep": "X_compound",
            },
        ),
        ("differential", {"group_key": "group", "group_a": "a", "group_b": "b"}),
        ("network", {"method": "pearson", "min_abs_correlation": 0.5}),
        ("markers", {"group_key": "group"}),
        ("train", {"label_key": "group", "model": "logistic", "cv": 2, "layer": training_layer}),
    ]:
        response = post("/analysis/operation", {"operation": operation, "options": options})
        assert response.status_code == 200, (operation, response.text)
    project = manager._workspaces[current()["workspace_id"]].project
    assert (
        project.workspace.result("differential")["input"]["variable_kind"] == "empirical_compound"
    )
    assert "view_id" in project.workspace.result("supervised").scmm_analysis_input
    assert project.workspace.result("supervised").scmm_analysis_input["layer"] == training_layer
    stale = current()["revision"] - 1
    assert get(workflow, f"/ions/download?kind=registry&revision={stale}").status_code == 409
    post("/project/save").raise_for_status()
    response = post("/project/open", {"path": current()["project"]["path"]})
    assert response.status_code == 200, response.text
    assert not get(workflow, "/ions/info").json()["roots"]
    reopened = manager._workspaces[current()["workspace_id"]].project
    assert reopened.saved_reports["supervised"]["input"]["layer"] == training_layer
