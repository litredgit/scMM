import numpy as np

from tests.support.workflow import get, import_data


def test_new_plots_annotation_and_msms_roundtrip(workflow):
    import_data(workflow)
    post = workflow[-1]
    for kind, options in [
        ("target_correlations", {"target": "feature:f0"}),
        (
            "association",
            {"x": "feature:f0", "y": "feature:f1", "replicate_key": "subject", "permutations": 9},
        ),
        ("set_comparison", {"group_key": "group", "groups": ["a", "b"]}),
    ]:
        result = post("/analysis/plot", {"kind": kind, "options": options})
        assert result.status_code == 200, result.text
        assert result.json()["value"]["layout"]["meta"]["export_tables"]
    options = {
        "content": "feature_id,name\nf0,example\n",
        "mapping": {"name": "manual_name"},
        "source_key": "feature_id",
    }
    preview = post("/analysis/annotations/preview", options)
    assert preview.status_code == 200, preview.text
    assert preview.json()["value"]["matched"] == 1
    assert post("/analysis/annotations/apply", options).status_code == 200
    spectrum = "BEGIN IONS\nTITLE=reference\nPEPMASS=150\n100 4\n120 1\nEND IONS\n"
    result = post(
        "/analysis/msms",
        {
            "measured": spectrum,
            "library": spectrum,
            "sample_pool": "pool",
            "polarity": "positive",
            "minimum_matches": 2,
        },
    )
    assert result.status_code == 200, result.text
    assert post("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert post("/project/open", {"path": path}).status_code == 200
    saved = get(workflow, "/analysis/figures/msms_evidence")
    assert saved.status_code == 200, saved.text
    assert "candidates" in saved.json()["layout"]["meta"]["export_tables"]


def test_label_filter_save_reopen_disable_and_stale_revision(workflow):
    data = import_data(workflow)
    post = workflow[-1]
    selected = list(data.obs_names[:10])
    result = post("/analysis/selection-labels", {"name": "review", "ids": selected})
    assert result.status_code == 200, result.text
    assert workflow[-2]()["project"]["dataset"]["cells"] == 10
    assert post("/project/save").status_code == 200
    path = workflow[-2]()["project"]["path"]
    assert post("/project/open", {"path": path}).status_code == 200
    result = post(
        "/analysis/selection-labels", {"name": "review", "mode": "toggle", "enabled": False}
    )
    assert result.status_code == 200, result.text
    assert workflow[-2]()["project"]["dataset"]["cells"] == 64
    identity = workflow[1]["X-SCMM-Workspace"]
    with workflow[2].access(identity) as workspace:
        np.testing.assert_array_equal(workspace.project.workspace.data.X, data.X)
    current = workflow[-2]()
    bad = workflow[0].post(
        "/api/v1/workspace/analysis/selection-labels",
        headers=workflow[1],
        json={
            "revision": current["revision"] - 1,
            "name": "review",
            "mode": "toggle",
            "enabled": True,
        },
    )
    assert bad.status_code == 409
