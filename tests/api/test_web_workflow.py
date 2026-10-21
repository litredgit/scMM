"""HTTP migration parity, transactional state, task ownership and export boundaries."""

# ruff: noqa: RUF001
import json
import time
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from tests.support.workflow import get, import_data, operation, raw_samples


def test_qc_candidate_apply_failure_history_and_complete_reset(workflow):
    data = import_data(workflow)
    before = workflow[-2]()
    qc = get(workflow, "/analysis/qc").json()
    assert qc["cells"]["total"] == 64
    candidate = operation(workflow, "normalize", {"method": "total"}, preview=True)
    assert candidate["workspace"] == before
    assert workflow[-2]() == before
    operation(workflow, "filter", {"min_total": float(np.median(data.X.sum(axis=1)))})
    assert workflow[-2]()["project"]["dataset"]["cells"] < 64
    current = workflow[-2]()
    failure = workflow[-1](
        "/analysis/operation", {"operation": "filter", "options": {"min_total": 1e9}}
    )
    assert failure.status_code == 400
    assert workflow[-2]() == current
    operation(workflow, "normalize", {"method": "total"})
    history = get(workflow, "/analysis").json()["history"]
    assert [row["operation"] for row in history] == ["filter", "normalize"]
    operation(workflow, "reset")
    restored = get(workflow, "/results/download?kind=matrix").text
    np.testing.assert_allclose(pd.read_csv(StringIO(restored), index_col=0).to_numpy(), data.X)


def test_analysis_plots_results_staleness_and_saved_report_reload(workflow):
    import_data(workflow)
    operation(workflow, "reduce", {"method": "pca", "store_key": "X_pca"})
    operation(workflow, "cluster", {"method": "kmeans", "key": "clusters", "n_clusters": 2})
    current = workflow[-2]()
    failure = workflow[-1](
        "/analysis/operation",
        {"operation": "reduce", "options": {"method": "pca", "store_key": "X_pca"}},
    )
    assert failure.status_code == 400 and workflow[-2]() == current
    operation(workflow, "differential", {"group_key": "group", "group_a": "a", "group_b": "b"})
    operation(workflow, "markers", {"group_key": "clusters"})
    operation(workflow, "network", {"top_features": 5, "min_abs_correlation": 0.2})
    for kind, options in [
        ("embedding", {"key": "X_pca", "color": "feature:f0"}),
        ("volcano", {}),
        ("violin", {"features": ["f0"], "hide_zero": True}),
        ("network_plot", {}),
    ]:
        response = workflow[-1]("/analysis/plot", {"kind": kind, "options": options})
        assert response.status_code == 200, response.text
        assert response.json()["value"]["data"]
    assert (
        get(workflow, "/analysis/results/differential?offset=2&limit=2").json()["table"]["total"]
        == 8
    )
    complete = get(workflow, "/analysis/results/differential?limit=100").json()["table"]["rows"]
    assert (
        get(workflow, "/analysis/results/differential?offset=2&limit=2").json()["table"]["rows"]
        == complete[2:4]
    )
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert "differential" in get(workflow, "/analysis").json()["results"]
    assert get(workflow, "/results/download?kind=differential").status_code == 200
    assert workflow[-1]("/analysis/plot", {"kind": "volcano"}).status_code == 200
    operation(workflow, "normalize", {"method": "total"})
    assert get(workflow, "/analysis").json()["embeddings"] == []
    assert get(workflow, "/results/download?kind=differential").status_code == 400
    assert get(workflow, "/results/download?kind=figure&key=volcano").status_code == 400


@pytest.mark.filterwarnings(
    "ignore:The set_(bad|under|over) function will be deprecated:PendingDeprecationWarning:shap.plots.colors._colors"
)
def test_supervised_grouped_cv_shap_and_readonly_reload(workflow):
    import_data(workflow)
    operation(
        workflow,
        "train",
        {
            "label_key": "group",
            "group_key": "subject",
            "model": "lda",
            "cv": 2,
            "test_size": 0.5,
            "calibration_bins": 2,
        },
    )
    result = get(workflow, "/analysis/results/supervised").json()
    audit = result["diagnostics"]["validation_audit"]
    assert audit["validation_mode"] == "grouped"
    assert audit["all_source_support"]["a"] == {"cells": 32, "source_groups": 4}
    before_revision = workflow[-2]()["revision"]
    rejected = workflow[-1](
        "/analysis/operation",
        {"operation": "train", "options": {"label_key": "group", "group_key": "group", "cv": 2}},
    )
    assert rejected.status_code == 400
    assert "每类至少有 3 个来源组" in rejected.json()["error"]["message"]
    assert workflow[-2]()["revision"] == before_revision
    assert (
        get(workflow, "/analysis/results/supervised").json()["diagnostics"]["validation_audit"]
        == audit
    )
    assert set(result["train_obs"]).isdisjoint(result["test_obs"])
    train_groups = {int(name[1:]) // 8 for name in result["train_obs"]}
    test_groups = {int(name[1:]) // 8 for name in result["test_obs"]}
    assert train_groups.isdisjoint(test_groups)
    for kind in ("roc", "pr", "calibration"):
        assert workflow[-1]("/analysis/plot", {"kind": kind}).status_code == 200
    for normalize in (False, True):
        response = workflow[-1](
            "/analysis/plot", {"kind": "confusion", "options": {"normalize": normalize}}
        )
        assert response.status_code == 200, response.text
        figure = response.json()["value"]
        frame = pd.read_csv(
            StringIO(figure["layout"]["meta"]["export_tables"]["row_normalized.csv"]), index_col=0
        )
        np.testing.assert_allclose(frame.sum(axis=1), 1)
    operation(workflow, "save_latent", {"key": "X_latent"})
    assert "X_latent" in get(workflow, "/analysis").json()["embeddings"]
    operation(workflow, "explain_shap", {"max_background": 4, "max_samples": 2})
    assert get(workflow, "/analysis/results/shap").json()["table"]["total"] == 8
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    info = get(workflow, "/analysis").json()
    assert not info["live_results"] and not info["latent_supported"]
    assert workflow[-1]("/analysis/plot", {"kind": "roc"}).status_code == 200
    failure = workflow[-1]("/analysis/operation", {"operation": "explain_shap"})
    assert failure.status_code == 400
    assert get(workflow, "/results/download?kind=supervised").status_code == 200
    reloaded = get(workflow, "/analysis/results/supervised").json()
    assert reloaded["diagnostics"]["validation_audit"] == audit
    downloaded = get(workflow, "/results/download?kind=supervised").json()
    assert downloaded["diagnostics"]["validation_audit"] == audit


def test_export_snapshot_and_shared_recycle_protections(workflow):
    data = import_data(workflow)
    assert workflow[-1]("/project/save").status_code == 200
    response = workflow[-1]("/results/export", {"root": "Output", "filename": "export.h5ad"})
    assert response.status_code == 200, response.text
    np.testing.assert_array_equal(read_h5ad(response.json()["value"]["path"]).X, data.X)
    assert (
        workflow[-1]("/results/export", {"root": "Output", "filename": "export.h5ad"}).status_code
        == 400
    )
    assert (
        workflow[-1](
            "/results/export", {"root": "Output", "filename": "../escape.h5ad"}
        ).status_code
        == 400
    )
    assert get(workflow, "/results/download?kind=snapshot&filename=data.h5ad").content.startswith(
        b"\x89HDF"
    )
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/saved/plan", {"root": "项目结果", "path": path}).status_code == 409
    assert workflow[-1]("/project/close").status_code == 200
    plan = workflow[-1]("/saved/plan", {"root": "项目结果", "path": path})
    assert plan.status_code == 200, plan.text
    assert workflow[-1]("/saved/move", {"token": plan.json()["token"]}).status_code == 200
    trash = get(workflow, "/saved/trash").json()
    assert len(trash) == 1
    assert workflow[-1]("/saved/restore", {"entry": trash[0]["entry"]}).status_code == 200
    assert not get(workflow, "/saved/trash").json()
    assert workflow[-1]("/saved/clear").json() == 0


def test_runtime_detects_unsaved_busy_and_clean_sessions(workflow):
    client, _, manager, *_ = workflow
    assert client.get("/api/v1/runtime").json()["unsaved_workspaces"] == 0
    raw_samples(workflow)
    assert client.get("/api/v1/runtime").json()["unsaved_workspaces"] == 1
    assert workflow[-1]("/project/save").status_code == 200
    assert client.get("/api/v1/runtime").json()["unsaved_workspaces"] == 0
    assert manager.runtime()["busy_workspaces"] == 0


def test_panel_saved_view_compatibility_and_independent_legends(workflow):
    import_data(workflow)
    identity = workflow[1]["X-SCMM-Workspace"]
    manager = workflow[2]
    with manager.access(identity) as workspace:
        workspace.project.views = {
            "settings": {
                "reduction": "pca",
                "embedding_key": "X_old",
                "color": "feature:f1",
                "cv": 2,
            },
            "figures": {
                "roc": json.dumps(
                    {"data": [{"type": "scatter", "x": [0, 1], "y": [0, 1]}], "layout": {}}
                )
            },
        }
        workspace.project.saved_reports = {"supervised": {"diagnostics": {"test_accuracy": 1.0}}}
    info = get(workflow, "/analysis").json()
    assert info["settings"]["reduction"]["store_key"] == "X_old"
    assert info["settings"]["colorSource"] == "feature"
    figure = workflow[-1]("/analysis/plot", {"kind": "roc"}).json()["value"]
    assert isinstance(figure, dict) and figure["data"]
    assert get(workflow, "/analysis/figures/roc").json() == figure
    assert get(workflow, "/analysis").json()["figures"] == ["roc"]
    downloaded = get(workflow, "/results/download?kind=figure&key=roc&filename=roc.json")
    assert downloaded.status_code == 200 and downloaded.json() == figure
    assert (
        workflow[-1](
            "/presentation", {"key": "analysis.roc", "position": "hidden"}, "PUT"
        ).status_code
        == 200
    )
    assert workflow[-2]()["project"]["presentation"] == {"analysis.roc": "hidden"}
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert workflow[-2]()["project"]["presentation"] == {"analysis.roc": "hidden"}


def test_qc_stable_total_axis_preserves_precision_zeros_and_file_identity(workflow):
    data = import_data(workflow)
    data.X[0] = 0
    data.obs["source_file"] = ["/a/same.raw"] * 32 + ["/b/same.raw"] * 32
    data.write_h5ad(workflow[4] / "data.h5ad")
    assert (
        workflow[-1]("/dataset/import", {"root": "Output", "path": "data.h5ad"}).status_code == 200
    )
    operation(workflow, "normalize", {"method": "total"})
    result = get(workflow, "/analysis/qc").json()
    assert result["figure"]["layout"]["xaxis"]["range"] == [-0.05, 1.05]
    assert result["figure"]["layout"]["yaxis"]["dtick"] == 1
    traces = result["figure"]["data"]
    assert [t["name"] for t in traces] == ["same.raw（1）", "same.raw（2）"]
    assert {t["customdata"][0][1] for t in traces} == {"/a/same.raw", "/b/same.raw"}
    values = np.array([r["total_intensity"] for r in result["cells"]["rows"]])
    assert values[0] == 0
    np.testing.assert_allclose(values[1:], 1, rtol=0, atol=1e-14)
    exported = pd.read_csv(
        StringIO(get(workflow, "/results/download?kind=qc").text), float_precision="round_trip"
    )["total_intensity"].to_numpy()
    assert np.any(exported[1:] != 1)  # Actual exported totals retain the summation differences.
    operation(workflow, "normalize", {"method": "log"})
    changed = get(workflow, "/analysis/qc").json()
    assert "range" not in changed["figure"]["layout"]["xaxis"]
    assert all(r["detected_features"] == data.n_vars for r in changed["cells"]["rows"])


def test_result_browser_latest_snapshot_excludes_baseline_and_caches(workflow):
    import_data(workflow)
    assert workflow[-1]("/project/save").status_code == 200
    view = workflow[-2]()["project"]
    project = workflow[2].store.open(view["path"])
    preview = project.folder / "processing" / "preview-new"
    preview.mkdir()
    AnnData(np.ones((2, 2))).write_h5ad(preview / "data.h5ad")
    response = workflow[0].get(
        "/api/v1/storage/entries", params={"root": "项目结果", "kind": "results"}
    )
    assert response.status_code == 200, response.text
    latest = response.json()["latest"]
    assert latest["role"] == "当前快照"
    assert latest["path"].endswith(project.manifest["artifacts"]["current"])
    assert latest["project_name"] == project.manifest["name"]
    browse = {"root": "项目结果", "kind": "results", "path": view["path"]}
    entries = workflow[0].get("/api/v1/storage/entries", params=browse).json()["entries"]
    assert all(not e["internal"] for e in entries)
    entries = (
        workflow[0]
        .get("/api/v1/storage/entries", params={**browse, "include_internal": True})
        .json()["entries"]
    )
    assert {e["name"] for e in entries} >= {"processing", "snapshots"}
    assert any(e["role"] == "当前快照目录" for e in entries)


def test_latest_export_and_foreign_project_are_classified_without_cross_root_open(workflow):
    import os

    from scMM.application.projects import ProjectStore

    import_data(workflow)
    assert workflow[-1]("/project/save").status_code == 200
    folder = workflow[2].store._folder(workflow[-2]()["project"]["path"])
    export = folder / "exports" / "last-export.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(export)
    future = time.time() + 60
    os.utime(export, (future, future))
    current = (
        workflow[0]
        .get("/api/v1/storage/entries", params={"root": "项目结果", "kind": "results"})
        .json()
    )
    assert current["latest"]["name"] == "last-export.h5ad"
    assert current["latest"]["role"] == "独立导出 H5AD"
    foreign_store = ProjectStore(workflow[4])
    foreign = foreign_store.create("other environment")
    foreign.workspace.replace(AnnData(np.ones((2, 2))))
    foreign_store.save(foreign)
    listing = (
        workflow[0]
        .get("/api/v1/storage/entries", params={"root": "Output", "kind": "results"})
        .json()
    )
    item = next(e for e in listing["entries"] if e["name"] == foreign.folder.name)
    assert item["project_name"] == "other environment"
    assert item["project_path"] is None
    assert "所属环境" in item["protection"]
    assert workflow[-1]("/project/open", {"path": str(foreign.folder)}).status_code == 403


@pytest.mark.parametrize(
    ("name", "options"),
    [
        ("differential", {"group_key": "group", "group_a": "a", "group_b": "b"}),
        ("markers", {"group_key": "group"}),
        ("network", {"top_features": 5, "min_abs_correlation": 0.2}),
    ],
)
def test_analysis_failed_replacement_retains_complete_precision_export(workflow, name, options):
    import_data(workflow)
    operation(workflow, name, options)
    before = workflow[-2]()
    payload = get(workflow, f"/results/download?kind={name}").content
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        expected = workspace.project.workspace.result(name)["table"].copy()
    exported = pd.read_csv(StringIO(payload.decode()), float_precision="round_trip")
    for column in exported.select_dtypes(include="number"):
        np.testing.assert_array_equal(exported[column].to_numpy(), expected[column].to_numpy())
    failure = workflow[-1](
        "/analysis/operation",
        {"operation": name, "options": {**options, "layer": "missing_layer"}},
    )
    assert failure.status_code == 400
    assert workflow[-2]() == before
    assert get(workflow, f"/results/download?kind={name}").content == payload
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert get(workflow, f"/results/download?kind={name}").content == payload


def test_legend_order_persists_independently_of_position(workflow):
    workflow[-1](
        "/presentation", {"key": "example", "position": "hidden"}, "PUT"
    ).raise_for_status()
    workflow[-1](
        "/presentation", {"key": "example", "order": ["B", "A", "B"]}, "PUT"
    ).raise_for_status()
    project = workflow[-2]()["project"]
    assert project["presentation"] == {"example": "hidden"}
    assert project["legend_orders"] == {"example": ["B", "A"]}
    workflow[-1]("/project/save").raise_for_status()
    workflow[-1]("/project/open", {"path": project["path"]}).raise_for_status()
    assert workflow[-2]()["project"]["legend_orders"] == {"example": ["B", "A"]}
    workflow[-1]("/presentation", {"key": "example", "order": []}, "PUT").raise_for_status()
    assert workflow[-2]()["project"]["presentation"]["example"] == "hidden"
    assert workflow[-2]()["project"]["legend_orders"]["example"] == []


def test_retention_advice_is_read_only_and_revision_guarded(workflow):
    _, _, manager, _, _, _, _, current, post = workflow
    before = current()
    project_path = before["project"]["path"]
    manager_state = manager.saved_items()
    snapshot = {str(p): p.read_bytes() for p in Path(project_path).rglob("*") if p.is_file()}
    response = post("/saved/retention", {"root": "项目结果", "path": project_path})
    assert response.status_code == 200, response.text
    advice = response.json()
    assert advice["read_only"] and "token" not in advice
    assert advice["immediate_freed_bytes"] == 0
    assert current()["revision"] == before["revision"]
    assert snapshot == {
        str(p): p.read_bytes() for p in Path(project_path).rglob("*") if p.is_file()
    }
    assert not manager_state.trash_root.exists()
    assert post("/saved/retention", {"root": "Output", "path": project_path}).status_code == 400
    assert (
        post(
            "/saved/retention", {"root": "项目结果", "path": str(Path(project_path).parent)}
        ).status_code
        == 403
    )
    assert (
        post(
            "/saved/retention",
            {"root": "项目结果", "path": project_path, "revision": before["revision"] + 1},
        ).status_code
        == 409
    )
    assert post("/saved/move", {"token": "retention-advice"}).status_code == 400


def test_clustering_parameters_reach_algorithm_and_persist_in_history(workflow):
    data = import_data(workflow)
    options = {
        "method": "dbscan",
        "key": "dbscan_tuned",
        "eps": 0.001,
        "min_samples": 2,
        "metric": "manhattan",
    }
    operation(workflow, "cluster", options)
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as browser:
        project = browser.project
    assert set(project.workspace.data.obs["dbscan_tuned"].astype(str)) == {"-1"}
    assert project.workspace.history()[-1]["parameters"]["effective_parameters"] == {
        "eps": 0.001,
        "min_samples": 2,
        "metric": "manhattan",
    }
    before = workflow[-2]()["revision"]
    invalid = workflow[-1](
        "/analysis/operation",
        {"operation": "cluster", "options": {**options, "key": "bad", "eps": -1}},
    )
    assert invalid.status_code == 422
    assert workflow[-2]()["revision"] == before
    assert "bad" not in project.workspace.data.obs
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as browser:
        reloaded = browser.project
    assert reloaded.workspace.history()[-1]["parameters"]["effective_parameters"]["eps"] == 0.001
    np.testing.assert_array_equal(reloaded.workspace.data.X, data.X)


def test_feature_scatter_reload_export_staleness_and_metadata_dependencies(workflow):
    data = import_data(workflow)
    options = {"feature_a": "f0", "feature_b": "f1", "color_key": "group", "regression": True}
    response = workflow[-1]("/analysis/plot", {"kind": "feature_scatter", "options": options})
    assert response.status_code == 200, response.text
    figure = response.json()["value"]
    assert figure["layout"]["meta"]["regression"]["n_cells"] == 64
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    saved = get(workflow, "/analysis/figures/feature_scatter").json()
    assert saved["layout"]["meta"]["regression"] == figure["layout"]["meta"]["regression"]
    assert (
        workflow[0]
        .post("/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": saved})
        .status_code
        == 200
    )
    before = workflow[-2]()["revision"]
    bad = workflow[-1](
        "/analysis/plot",
        {"kind": "feature_scatter", "options": {**options, "feature_a": "150.0001"}},
    )
    assert bad.status_code == 400 and workflow[-2]()["revision"] == before
    samples = workflow[-2]()["project"]["manifest"]["samples"]
    edits = [
        {key: sample[key] for key in ("id", "name", "group", "subject", "batch")}
        for sample in samples
    ]
    edits[0]["batch"] = "unrelated-change"
    assert workflow[-1]("/samples", {"samples": edits}, "PATCH").status_code == 200
    assert get(workflow, "/analysis/figures/feature_scatter").status_code == 200
    edits[0]["group"] = "different"
    assert workflow[-1]("/samples", {"samples": edits}, "PATCH").status_code == 200
    assert get(workflow, "/analysis/figures/feature_scatter").status_code == 400
    assert (
        workflow[-1]("/analysis/plot", {"kind": "feature_scatter", "options": options}).status_code
        == 200
    )
    fresh = get(workflow, "/analysis/figures/feature_scatter").json()
    operation(workflow, "normalize", {"method": "total"})
    assert get(workflow, "/analysis/figures/feature_scatter").status_code == 400
    assert (
        workflow[0]
        .post("/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": fresh})
        .status_code
        == 400
    )
    assert data.shape == (64, 8)


def test_preprocessing_options_precision_history_and_roundtrip(workflow):
    import_data(workflow)
    operation(workflow, "normalize", {"method": "total", "scale": 100.0})
    matrix = pd.read_csv(StringIO(get(workflow, "/results/download?kind=matrix").text), index_col=0)
    np.testing.assert_allclose(matrix.sum(axis=1), 100)
    current = workflow[-2]()
    for options in (
        {"method": "total", "scale": -1},
        {"method": "max", "axis": True},
        {"method": "total", "unknown": 1},
    ):
        response = workflow[-1](
            "/analysis/operation", {"operation": "normalize", "options": options}
        )
        assert response.status_code == 422
        assert workflow[-2]() == current
    response = workflow[-1](
        "/analysis/operation", {"operation": "remove_outliers", "options": {"max_samples": "2bad"}}
    )
    assert response.status_code == 400
    assert workflow[-2]() == current
    operation(workflow, "impute", {"method": "most_frequent"})
    operation(
        workflow,
        "remove_outliers",
        {"n_estimators": 11, "max_samples": "0.5", "max_features": "1.0", "random_state": 3},
    )
    expected = get(workflow, "/analysis").json()["history"]
    assert expected[-1]["parameters"]["effective_parameters"]["max_features"] == 1.0
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/save", {}).status_code == 200
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert get(workflow, "/analysis").json()["history"] == expected


def test_feature_embedding_exact_features_saved_export_and_matrix_staleness(workflow):
    import_data(workflow)
    options = {"features": ["f0", "f1", "f2", "f3"], "metric": "euclidean", "random_state": 19}
    response = workflow[-1]("/analysis/plot", {"kind": "feature_embedding", "options": options})
    assert response.status_code == 200, response.text
    figure = response.json()["value"]
    assert figure["layout"]["meta"]["effective_parameters"]["n_features"] == 4
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    saved = get(workflow, "/analysis/figures/feature_embedding").json()
    assert saved["layout"]["meta"]["export_tables"] == figure["layout"]["meta"]["export_tables"]
    assert (
        workflow[0]
        .post("/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": saved})
        .status_code
        == 200
    )
    operation(workflow, "normalize", {"method": "total"})
    assert "feature_embedding" not in get(workflow, "/analysis").json()["figures"]
    assert (
        workflow[0]
        .post("/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": saved})
        .status_code
        != 200
    )


def test_subset_preview_apply_save_reopen_and_reset(workflow):
    data = import_data(workflow)
    ids = list(data.obs_names[[4, 1, 0]])
    options = {"cell_ids": ids, "feature_ids": ["f3", "f0"]}
    before = workflow[-2]()
    preview = operation(workflow, "subset", options, preview=True)
    assert preview["value"]["impact"][:2] == [
        {"object": "细胞", "before": 64, "after": 3},
        {"object": "特征", "before": 8, "after": 2},
    ]
    assert workflow[-2]() == before
    for invalid in ({"feature_ids": ["missing"]}, {"cell_ids": [ids[0], ids[0]]}, {}):
        assert (
            workflow[-1](
                "/analysis/operation", {"operation": "subset", "options": invalid}
            ).status_code
            == 400
        )
        assert workflow[-2]() == before
    operation(workflow, "subset", options)
    frame = pd.read_csv(StringIO(get(workflow, "/results/download?kind=matrix").text), index_col=0)
    assert frame.index.tolist() == ids and frame.columns.tolist() == ["f3", "f0"]
    np.testing.assert_array_equal(frame.to_numpy(), data[ids, ["f3", "f0"]].X)
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert workflow[-2]()["project"]["dataset"]["cells"] == 3
    operation(workflow, "reset")
    assert workflow[-2]()["project"]["dataset"]["cells"] == 64
    assert workflow[-2]()["project"]["dataset"]["features"] == 8


def test_stability_plot_saved_full_tables_and_metadata_dependency(workflow):
    import_data(workflow)
    options = {"source_key": "sample", "feature": "f0", "time_kind": "stored_order", "bins": 4}
    response = workflow[-1]("/analysis/plot", {"kind": "stability", "options": options})
    assert response.status_code == 200, response.text
    figure = response.json()["value"]
    assert figure["layout"]["yaxis"]["tickformat"] == ".1e"
    assert figure["layout"]["yaxis2"]["tickformat"] == "d"
    cells = pd.read_csv(StringIO(figure["layout"]["meta"]["export_tables"]["cells.csv"]))
    assert len(cells) == 64 and cells.included.all()
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    saved = get(workflow, "/analysis/figures/stability").json()
    assert saved["layout"]["meta"]["export_tables"] == figure["layout"]["meta"]["export_tables"]
    assert (
        workflow[0]
        .post("/api/v1/workspace/figures/data", headers=workflow[1], json={"figure": saved})
        .status_code
        == 200
    )
    samples = workflow[-2]()["project"]["manifest"]["samples"]
    edits = [
        {key: sample[key] for key in ("id", "name", "group", "subject", "batch")}
        for sample in samples
    ]
    edits[0]["batch"] = "unrelated-qc"
    assert workflow[-1]("/samples", {"samples": edits}, "PATCH").status_code == 200
    assert get(workflow, "/analysis/figures/stability").status_code == 200
    edits[0]["name"] = "renamed-source"
    assert workflow[-1]("/samples", {"samples": edits}, "PATCH").status_code == 200
    assert get(workflow, "/analysis/figures/stability").status_code == 400
    assert (
        workflow[-1]("/analysis/plot", {"kind": "stability", "options": options}).status_code == 200
    )
    operation(workflow, "normalize", {"method": "total"})
    assert "stability" not in get(workflow, "/analysis").json()["figures"]


def test_current_quality_pdf_and_report_archive_are_read_only_and_revision_bound(
    workflow, monkeypatch
):
    import io
    import zipfile

    def request(path, **params):
        return workflow[0].get(f"/api/v1/workspace{path}", headers=workflow[1], params=params)

    data = import_data(workflow)
    token = request("/analysis").json()["token"]
    before = workflow[-2]()
    response = request(
        "/results/download",
        kind="quality_pdf",
        key=json.dumps(token),
        filename="中文QC.pdf",
    )
    assert response.status_code == 200, response.text[:100] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert workflow[-2]() == before
    assert request("/results/download", kind="quality_pdf", key="").status_code == 400
    assert (
        request(
            "/results/download", kind="quality_pdf", key=json.dumps([token[0], True])
        ).status_code
        == 400
    )
    operation(workflow, "reduce", {"method": "pca", "store_key": "X_pca", "n_components": 3})
    operation(workflow, "differential", {"group_key": "group", "group_a": "a", "group_b": "b"})
    operation(workflow, "network", {"min_abs_correlation": 0.0, "top_features": 8})
    assert (
        workflow[-1](
            "/analysis/plot",
            {"kind": "feature_scatter", "options": {"feature_a": "f0", "feature_b": "f1"}},
        ).status_code
        == 200
    )
    token = request("/analysis").json()["token"]
    before = workflow[-2]()
    bundle = request(
        "/results/download", kind="report_zip", key=json.dumps(token), filename="报告.zip"
    )
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        meta = json.loads(archive.read("metadata.json"))
        assert meta["dataset_id"] == token[0] and meta["dataset_revision"] == token[1]
        assert meta["unsaved"] is True and meta["matrix"] == "current X"
        assert meta["available_results"] == ["differential", "network"]
        assert "results/network_correlation.csv" in archive.namelist()
        assert len(json.loads(archive.read("results.json"))["network"]["nodes"]) == 8
        figure_files = meta["figures"]["feature_scatter"]
        graph_cells = pd.read_csv(io.BytesIO(archive.read(figure_files["tables"]["cells.csv"])))
        assert len(graph_cells) == 64
        assert archive.read(figure_files["file"]).startswith(b"{")
        embedding = pd.read_csv(
            io.BytesIO(archive.read(meta["embeddings"]["X_pca"]["file"])), index_col=0
        )
        assert embedding.shape == (64, 3) and embedding.index.tolist() == data.obs_names.tolist()
        table = pd.read_csv(io.BytesIO(archive.read("results/differential.csv")))
        assert len(table) == 8
        assert not any(
            name.endswith((".pkl", ".pickle", ".skops", ".h5ad")) for name in archive.namelist()
        )
    assert workflow[-2]() == before
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    assert request("/results/download", kind="report_zip", key=json.dumps(token)).status_code == 400
    new_token = request("/analysis").json()["token"]
    reopened = request("/results/download", kind="report_zip", key=json.dumps(new_token))
    with zipfile.ZipFile(io.BytesIO(reopened.content)) as archive:
        assert json.loads(archive.read("metadata.json"))["unsaved"] is False
        assert "results/differential.csv" in archive.namelist()
    operation(workflow, "normalize", {"method": "total"})
    assert (
        request("/results/download", kind="report_zip", key=json.dumps(new_token)).status_code
        == 400
    )
    final_token = request("/analysis").json()["token"]
    clean = request("/results/download", kind="report_zip", key=json.dumps(final_token))
    with zipfile.ZipFile(io.BytesIO(clean.content)) as archive:
        assert json.loads(archive.read("results.json")) == {}
        assert json.loads(archive.read("metadata.json"))["embeddings"] == {}
    from scMM.application import reporting

    def fail(*_args, **_kwargs):
        raise ValueError("synthetic report export failure")

    monkeypatch.setattr(reporting, "quality_report_bytes", fail)
    before = workflow[-2]()
    assert (
        request("/results/download", kind="quality_pdf", key=json.dumps(final_token)).status_code
        == 400
    )
    assert workflow[-2]() == before


@pytest.mark.parametrize(
    "params",
    [{"solver": "lbfgs", "penalty": "l1"}, {"C": 0}, {"fit_intercept": 1}, {"unknown": "value"}],
)
def test_invalid_model_parameters_preserve_fitted_result(workflow, params):
    import_data(workflow)
    operation(workflow, "train", {"label_key": "group", "model": "lda", "cv": 2})
    before = workflow[-2]()
    report = get(workflow, "/analysis/results/supervised").json()
    response = workflow[-1](
        "/analysis/operation",
        {
            "operation": "train",
            "options": {"label_key": "group", "model": "logistic", "model_params": params},
        },
    )
    assert response.status_code == 422
    assert workflow[-2]() == before
    assert get(workflow, "/analysis/results/supervised").json() == report


def test_network_catalog_roundtrip_preserves_full_matrix_and_can_redraw(workflow):
    from io import BytesIO
    from zipfile import ZipFile

    import_data(workflow)
    operation(workflow, "network", {"min_abs_correlation": 0.99, "top_features": 4})
    current = workflow[-2]()
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        expected = workspace.project.workspace.result("network")["correlation"].copy()
    assert workflow[-1]("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert workflow[-1]("/project/open", {"path": path}).status_code == 200
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        restored = workflow[2].result_value(workspace.project, "network")
        pd.testing.assert_frame_equal(restored["correlation"], expected)
        token = list(workspace.project.workspace.token)
    drawn = workflow[-1]("/analysis/plot", {"kind": "network_plot", "options": {}})
    assert drawn.status_code == 200, drawn.text
    archive = get(workflow, "/results/download?kind=report_zip&key=" + json.dumps(token))
    assert archive.status_code == 200
    with ZipFile(BytesIO(archive.content)) as z:
        names = [name for name in z.namelist() if "correlation" in name]
        assert names
    assert current["project"]["dataset"]["cells"] == workflow[-2]()["project"]["dataset"]["cells"]


def test_retraining_invalidates_every_shap_plot_variant(workflow):
    import_data(workflow)
    operation(workflow, "train", {"label_key": "group", "model": "lda", "cv": 2})
    keys = ("shap_plot", "shap_beeswarm", "shap_waterfall", "shap_dependence")
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        workspace.project.views["figures"] = {name: {"data": [], "layout": {}} for name in keys}
        workspace.project.saved_reports["shap"] = {"table": []}
    operation(workflow, "train", {"label_key": "group", "model": "lda", "cv": 2})
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        assert not set(keys) & workspace.project.views["figures"].keys()
        assert "shap" not in workspace.project.saved_reports
