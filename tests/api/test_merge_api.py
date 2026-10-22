"""Owned preview/apply, source changes, candidate failure and project reset recovery."""

import numpy as np
import pandas as pd
from anndata import AnnData

from tests.support.workflow import get


def sources(workflow):
    _, _, _, _, output, _, _, _, post = workflow
    left = AnnData(
        np.array([[1.123456789012345, 2.0], [3.0, 4.0]]),
        obs=pd.DataFrame(
            {"sample": ["a", "a"], "group": ["A", "A"], "time": [0.0, 1.0]}, index=["c0", "c1"]
        ),
        var=pd.DataFrame({"mz": [100.0, 200.0]}, index=["f0", "f1"]),
    )
    right = AnnData(
        np.array([[5.0, 6.0]]),
        obs=pd.DataFrame({"sample": ["b"], "group": ["B"], "time": [2.0]}, index=["c0"]),
        var=pd.DataFrame({"mz": [100.0001, 300.0]}, index=["f0", "f2"]),
    )
    left.write_h5ad(output / "left.h5ad")
    right.write_h5ad(output / "right.h5ad")
    post("/dataset/import", {"root": "Output", "path": "left.h5ad"}).raise_for_status()
    opts = {
        "sources": [
            {"kind": "current", "mass_key": "mz", "sample_key": "sample"},
            {
                "kind": "file",
                "root": "Output",
                "path": "right.h5ad",
                "mass_key": "mz",
                "sample_key": "sample",
            },
        ],
        "reference": 0,
        "mode": "ref",
        "ppm_tol": 5.0,
        "ambiguity": "reject",
        "common_observations": ["time"],
        "mapping": [
            {"input_id": "m0", "source_sample": "a", "name": "left"},
            {"input_id": "m1", "source_sample": "b", "name": "right"},
        ],
    }
    return opts, left, right


def test_merge_preview_apply_complete_baseline_save_and_reset(workflow):
    options, left, _ = sources(workflow)
    _, _, manager, _, _, _, _, current, post = workflow
    post(
        "/analysis/operation",
        {"operation": "subset", "options": {"cell_ids": ["c0"], "feature_ids": ["f0"]}},
    ).raise_for_status()
    before = current()
    preview = post("/dataset/merge/preview", options)
    assert preview.status_code == 200, preview.text
    value = preview.json()["value"]
    assert current() == before
    assert value["summaries"]["data"]["cells"] == 2 and value["summaries"]["data"]["features"] == 1
    assert (
        value["summaries"]["baseline"]["cells"] == 3
        and value["summaries"]["baseline"]["features"] == 3
    )
    post("/dataset/merge/apply", {"token": value["token"]}).raise_for_status()
    applied = current()
    assert applied["project"]["dataset"]["cells"] == 2
    assert post("/dataset/merge/apply", {"token": value["token"]}).status_code == 400
    with manager.access(workflow[1]["X-SCMM-Workspace"]) as space:
        np.testing.assert_equal(space.project.workspace.data.X, [[left.X[0, 0]], [5.0]])
        assert not space.project.workspace.data.obsm
    path = applied["project"]["path"]
    post("/project/save").raise_for_status()
    post("/project/close").raise_for_status()
    post("/project/open", {"path": path}).raise_for_status()
    post("/analysis/operation", {"operation": "reset", "options": {}}).raise_for_status()
    assert current()["project"]["dataset"]["cells"] == 3
    assert current()["project"]["dataset"]["features"] == 3
    assert len(current()["project"]["manifest"]["samples"]) == 2


def test_merge_changed_input_and_stale_revision_never_apply(workflow):
    options, _, right = sources(workflow)
    _, _, _, _, output, _, _, current, post = workflow
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    before = current()
    right.X[:] = 999
    right.write_h5ad(output / "right.h5ad")
    assert post("/dataset/merge/apply", {"token": token}).status_code == 400
    assert current() == before
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    assert (
        post(
            "/dataset/merge/apply", {"token": token, "revision": before["revision"] - 1}
        ).status_code
        == 409
    )
    assert current() == before


def test_merge_failure_after_assembly_preserves_current_and_sources(workflow, monkeypatch):
    options, left, _ = sources(workflow)
    _, _, manager, _, _, _, _, current, post = workflow
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    before = current()
    from scMM.application import processed_merge

    original = processed_merge.assemble

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        result.X[:] = -999
        raise ValueError("after candidate assembly")

    monkeypatch.setattr(processed_merge, "assemble", fail)
    assert post("/dataset/merge/apply", {"token": token}).status_code == 400
    assert current() == before
    with manager.access(workflow[1]["X-SCMM-Workspace"]) as space:
        np.testing.assert_equal(space.project.workspace.data.X, left.X)


def test_merge_preview_full_audit_is_historical_and_not_display_limited(workflow):
    import json
    from io import BytesIO
    from zipfile import ZipFile

    options, _, _ = sources(workflow)
    _, _, _manager, _, _, _, _, current, post = workflow
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    response = get(workflow, f"/results/download?kind=merge_preview&key={token}")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(pd.read_csv(BytesIO(archive.read("data_feature_mapping.csv")))) == 4
    post("/dataset/merge/apply", {"token": token}).raise_for_status()
    key = get(workflow, "/dataset/merge/info").json()["key"]
    post(
        "/analysis/operation", {"operation": "normalize", "options": {"method": "total"}}
    ).raise_for_status()
    response = get(workflow, f"/results/download?kind=merge_audit&key={key}")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert (
            json.loads(archive.read("metadata.json"))["scope"]
            == "historical_merge_not_current_analysis"
        )
    assert get(workflow, "/results/download?kind=merge_audit&key=wrong").status_code == 400
    token = json.dumps(
        [current()["project"]["dataset"]["id"], current()["project"]["dataset"]["revision"]]
    )
    response = workflow[0].get(
        "/api/v1/workspace/results/download",
        headers=workflow[1],
        params={"kind": "report_zip", "key": token},
    )
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert "results/historical_merge_mapping.csv" in archive.namelist()


def test_merge_conflicts_reject_but_readonly_plan_can_be_downloaded(workflow):
    options, _, right = sources(workflow)
    _, headers, manager, _, output, _, _, current, post = workflow
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.project.workspace.data.var["mz"] = [100.0, 100.0001]
        workspace.project.workspace._original.var["mz"] = [100.0, 100.0001]
    right.var["mz"] = [100.00008, 300.0]
    right.write_h5ad(output / "right.h5ad")
    before = current()
    value = post("/dataset/merge/preview", options).json()["value"]
    assert not value["can_apply"] and value["conflicts"] > 0
    assert (
        get(workflow, f"/results/download?kind=merge_preview&key={value['token']}").status_code
        == 200
    )
    assert post("/dataset/merge/apply", {"token": value["token"]}).status_code == 400
    assert current() == before
    options["ambiguity"] = "legacy"
    value = post("/dataset/merge/preview", options).json()["value"]
    assert value["can_apply"]
    post("/dataset/merge/apply", {"token": value["token"]}).raise_for_status()


def test_merge_changed_current_without_revision_and_late_input_change_are_rejected(
    workflow, monkeypatch
):
    options, _, right = sources(workflow)
    _, headers, manager, _, output, _, _, current, post = workflow
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.project.workspace.data.X[0, 0] += 1
    before = current()
    assert post("/dataset/merge/apply", {"token": token}).status_code == 400
    assert current() == before
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    from scMM.application import processed_merge

    original = processed_merge.assemble

    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        right.X[:] = 777
        right.write_h5ad(output / "right.h5ad")
        return value

    monkeypatch.setattr(processed_merge, "assemble", changed)
    assert post("/dataset/merge/apply", {"token": token}).status_code == 400
    assert current() == before


def test_merge_expiry_paths_duplicate_inputs_and_empty_source_scope(workflow):
    import time

    options, _, _ = sources(workflow)
    _, headers, manager, _, _output, _, _, current, post = workflow
    before = current()
    bad = {**options, "sources": [options["sources"][1], options["sources"][1]]}
    assert post("/dataset/merge/preview", bad).status_code == 400
    assert current() == before
    assert post(
        "/dataset/merge/inspect",
        {"source": {"kind": "file", "root": "Output", "path": "../outside.h5ad"}},
    ).status_code in (403, 404)
    assert post("/dataset/merge/preview", {**options, "ppm_tol": True}).status_code == 422
    token = post("/dataset/merge/preview", options).json()["value"]["token"]
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.merge_plan["expires"] = time.monotonic() - 1
    assert post("/dataset/merge/apply", {"token": token}).status_code == 400
    assert current() == before


def test_merge_large_preview_download_keeps_every_mapping_row(workflow):
    from io import BytesIO
    from zipfile import ZipFile

    options, _, _ = sources(workflow)
    output = workflow[4]
    data = AnnData(
        np.arange(120, dtype=float)[None, :],
        obs=pd.DataFrame({"sample": ["b"]}, index=["c"]),
        var=pd.DataFrame(
            {"mz": np.arange(120, dtype=float) + 1000}, index=[f"x{i}" for i in range(120)]
        ),
    )
    data.write_h5ad(output / "right.h5ad")
    options["sources"][0] = {**options["sources"][1], "path": "large-left.h5ad"}
    data.obs["sample"] = ["a"]
    data.write_h5ad(output / "large-left.h5ad")
    options["common_observations"] = []
    post = workflow[-1]
    response = post("/dataset/merge/preview", options)
    assert response.status_code == 200, response.text
    value = response.json()["value"]
    assert len(value["tables"]["data"]["rows"]) == 200
    response = get(workflow, f"/results/download?kind=merge_preview&key={value['token']}")
    response.raise_for_status()
    with ZipFile(BytesIO(response.content)) as archive:
        for role in ("data", "baseline"):
            assert len(pd.read_csv(BytesIO(archive.read(f"{role}_feature_mapping.csv")))) == 240


def test_merge_hardlink_and_decode_budget_reject_without_workspace_mutation(workflow, monkeypatch):
    from scMM.application import merge_sources

    options, _, _ = sources(workflow)
    output = workflow[4]
    (output / "alias.h5ad").hardlink_to(output / "right.h5ad")
    duplicate = {
        **options,
        "sources": [options["sources"][1], {**options["sources"][1], "path": "alias.h5ad"}],
    }
    before = workflow[-2]()
    response = workflow[-1]("/dataset/merge/preview", duplicate)
    assert response.status_code == 400 and "硬链接" in response.text
    assert workflow[-2]() == before
    monkeypatch.setattr(merge_sources, "MAX_VALUES", 1)
    response = workflow[-1]("/dataset/merge/inspect", {"source": options["sources"][1]})
    assert response.status_code == 400 and "未装载大矩阵" in response.text
    assert workflow[-2]() == before


def test_merge_legacy_csv_reads_safely_and_rejects_pickle(workflow):
    from scMM.file.data import CyESIData

    options, _, right = sources(workflow)
    target = CyESIData.from_anndata(right, name="legacy").save(workflow[4])
    for path in target.glob("*.pkl"):
        path.unlink()
    source = {**options["sources"][1], "path": target.name}
    response = workflow[-1]("/dataset/merge/inspect", {"source": source})
    assert response.status_code == 200, response.text
    assert response.json()["value"]["cells"] == 1
    options["sources"][1] = source
    response = workflow[-1]("/dataset/merge/preview", options)
    assert response.status_code == 200, response.text
    # Presence of executable legacy frames is enough to reject; never unpickle them.
    (target / "data.pkl").write_bytes(b"not executable input")
    before = workflow[-2]()
    assert workflow[-1]("/dataset/merge/inspect", {"source": source}).status_code == 403
    assert workflow[-2]() == before
