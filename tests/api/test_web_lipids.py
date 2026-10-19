"""HTTP annotation parity, review atomicity and project round trips."""

from io import StringIO

import numpy as np
import pandas as pd
import pytest

from scMM.util.lipid_annotation import STORAGE_KEY, annotation_store
from tests.support.lipids import options, sdf_record, synthetic_data
from tests.support.workflow import get


def setup_lipids(workflow, monkeypatch):
    root = workflow[4] / "database"
    root.mkdir()
    (root / "test.sdf").write_text(sdf_record() + sdf_record("LMGP01010002", name="Synthetic B"))
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(root))
    data = synthetic_data(duplicate=True)
    data.write_h5ad(workflow[4] / "lipid.h5ad")
    workflow[-1]("/dataset/import", {"root": "Output", "path": "lipid.h5ad"}).raise_for_status()
    return data


def run_lipids(workflow, **overrides):
    response = workflow[-1]("/lipids/run", {"options": {**options(), **overrides}})
    assert response.status_code == 200, response.text
    return get(workflow, "/lipids").json()["active"]


def test_unknown_import_origin_is_not_offered_or_accepted_after_reset(workflow, monkeypatch):
    from scMM.util.intensity import PROVENANCE_KEY

    data = setup_lipids(workflow, monkeypatch)
    del data.uns[PROVENANCE_KEY]
    data.write_h5ad(workflow[4] / "unknown.h5ad")
    post = workflow[-1]
    post("/dataset/import", {"root": "Output", "path": "unknown.h5ad"}).raise_for_status()
    for reopen in (False, True):
        if reopen:
            post("/project/save").raise_for_status()
            path = workflow[-2]()["project"]["path"]
            post("/project/open", {"path": path}).raise_for_status()
        post("/analysis/operation", {"operation": "reset", "options": {}}).raise_for_status()
        summary = get(workflow, "/lipids").json()
        assert summary["layers"] == [] and summary["molecule_layers"] == []
        response = post("/lipids/run", {"options": options()})
        assert response.status_code == 400
        assert "来源未知" in response.text


def query(workflow, version, **kwargs):
    response = workflow[-1]("/lipids/query", {"version": version, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def test_lipid_http_roundtrip_preserves_matrix_snr_analysis_and_all_candidates(
    workflow, monkeypatch
):
    original = setup_lipids(workflow, monkeypatch)
    workflow[-1](
        "/analysis/operation",
        {"operation": "reduce", "options": {"method": "pca", "store_key": "X_pca"}},
    ).raise_for_status()
    token = get(workflow, "/analysis").json()["token"]
    version = run_lipids(workflow)
    result = query(workflow, version)
    assert result["candidates"]["total"] == 4
    assert result["isotopes"]["total"] == 8
    relation = result["isotopes"]["rows"][0]
    spectrum = workflow[-1](
        "/lipids/isotope-spectrum", {"version": version, "relation_id": relation["relation_id"]}
    )
    assert spectrum.status_code == 200, spectrum.text
    figure = spectrum.json()["value"]
    assert "theoretical_peak" in figure["layout"]["meta"]["export_tables"]
    assert any("理论" in trace.get("name", "") for trace in figure["data"])
    assert result["total_features"] == 4
    assert {r["name"] for r in result["candidates"]["rows"]} == {"Synthetic A", "Synthetic B"}
    assert get(workflow, "/analysis").json()["token"] == token
    assert "X_pca" in get(workflow, "/analysis").json()["embeddings"]
    response = workflow[-1](
        "/lipids/export", {"version": version, "kind": "matrix", "filters": {"isotopes": "hide"}}
    )
    frame = pd.read_csv(StringIO(response.text), index_col=0, float_precision="round_trip")
    assert list(frame.columns) == ["f0", "f2", "f3"]
    np.testing.assert_array_equal(frame.to_numpy(), original.X[:, [0, 2, 3]])
    current = pd.read_csv(
        StringIO(get(workflow, "/results/download?kind=matrix").text),
        index_col=0,
        float_precision="round_trip",
    )
    np.testing.assert_array_equal(current.to_numpy(), original.X)
    workflow[-1]("/project/save").raise_for_status()
    path = workflow[-2]()["project"]["path"]
    workflow[-1]("/project/open", {"path": path}).raise_for_status()
    assert query(workflow, version)["candidates"]["total"] == 4
    manager, headers = workflow[2], workflow[1]
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        data = workspace.project.workspace.require_data()
        np.testing.assert_array_equal(data.layers["feature_snr"], original.layers["feature_snr"])
        assert STORAGE_KEY in data.uns
        assert STORAGE_KEY not in workspace.project.workspace._original.uns
        assert data.var["lipid_isotope_match"].tolist() == [False, True, False, False]


def test_rules_review_versions_and_failed_mutations_are_atomic(workflow, monkeypatch):
    setup_lipids(workflow, monkeypatch)
    version = run_lipids(workflow)
    result = query(workflow, version, feature_id="f0", limit=1)
    assert result["candidates"]["total"] == 2 and len(result["suggested"]) == 2
    selected = result["suggested"][:1]
    workflow[-1](
        "/lipids/review", {"version": version, "feature_id": "f0", "candidate_ids": selected}
    ).raise_for_status()
    assert (
        query(workflow, version, feature_id="f0", filters={"candidates": "top"})["candidates"][
            "total"
        ]
        == 1
    )
    workflow[-1](
        "/lipids/review", {"version": version, "feature_id": "f0", "candidate_ids": None}
    ).raise_for_status()
    assert (
        query(workflow, version, feature_id="f0", filters={"candidates": "top"})["candidates"][
            "total"
        ]
        == 2
    )
    before = workflow[-2]()
    invalid = workflow[-1](
        "/lipids/review",
        {"version": version, "feature_id": "f0", "candidate_ids": ["not-a-candidate"]},
    )
    assert invalid.status_code == 400 and workflow[-2]() == before
    relation = query(workflow, version)["isotopes"]["rows"][0]
    workflow[-1](
        "/lipids/review",
        {"version": version, "relation_id": relation["relation_id"], "review": "rejected"},
    ).raise_for_status()
    assert query(workflow, version)["isotopes"]["rows"][0]["review"] == "rejected"
    second = run_lipids(workflow)
    assert len(get(workflow, "/lipids").json()["versions"]) == 2
    workflow[-1]("/lipids/activate", {"version": ""}).raise_for_status()
    assert get(workflow, "/lipids").json()["active"] == ""
    workflow[-1]("/lipids/activate", {"version": version}).raise_for_status()
    assert get(workflow, "/lipids").json()["active"] == version
    assert second != version


def test_rule_import_presets_and_reordering_need_no_recalculation(workflow, monkeypatch):
    setup_lipids(workflow, monkeypatch)
    version = run_lipids(workflow)
    text = "kind,level,value,polarity,adduct,score\nclass,CATEGORY,GP,pos,,7\n"
    response = workflow[-1]("/lipids/rules/import", {"format": "csv", "content": text})
    assert response.status_code == 200, response.text
    rules = response.json()
    workflow[-1]("/lipids/presets", {"name": "自定义", "rules": rules}).raise_for_status()
    assert "自定义" in get(workflow, "/lipids").json()["presets"]
    assert workflow[-1]("/lipids/presets", {"name": "自定义", "rules": rules}).status_code == 400
    monkeypatch.setattr(
        "scMM.application.web_lipids.load_database", lambda *args: pytest.fail("unneeded search")
    )
    workflow[-1]("/lipids/rules/apply", {"version": version, "rules": rules}).raise_for_status()
    assert all(r["rule_score"] == 7 for r in query(workflow, version)["candidates"]["rows"])
    response = workflow[-1]("/lipids/export", {"version": version, "kind": "rules"})
    assert response.json()["rules"][0]["score"] == 7


def test_invalid_inputs_stale_revision_and_stale_exports(workflow, monkeypatch):
    setup_lipids(workflow, monkeypatch)
    before = workflow[-2]()
    assert (
        workflow[-1](
            "/lipids/run", {"options": {**options(), "isotope_tolerance": -0.1}}
        ).status_code
        == 422
    )
    assert workflow[-2]() == before
    assert (
        workflow[-1]("/lipids/run", {"options": {**options(), "adducts": ["[M-H]-"]}}).status_code
        == 400
    )
    assert workflow[-2]() == before
    version = run_lipids(workflow)
    old_revision = workflow[-2]()["revision"]
    workflow[-1]("/lipids/activate", {"version": version}).raise_for_status()
    response = workflow[0].post(
        "/api/v1/workspace/lipids/review",
        headers=workflow[1],
        json={
            "revision": old_revision,
            "version": version,
            "feature_id": "f0",
            "candidate_ids": [],
        },
    )
    assert response.status_code == 409
    workflow[-1](
        "/analysis/operation", {"operation": "normalize", "options": {"method": "total"}}
    ).raise_for_status()
    assert query(workflow, version)["candidates"]["total"] == 4
    workflow[-1](
        "/analysis/operation", {"operation": "restore", "options": {"layer": "scmm_input_0"}}
    ).raise_for_status()
    workflow[-1](
        "/analysis/operation", {"operation": "filter", "options": {"min_total": 1000.0}}
    ).raise_for_status()
    assert not get(workflow, "/lipids").json()["versions"][0]["valid"]
    assert workflow[-1]("/lipids/export", {"version": version, "kind": "matrix"}).status_code == 400
    assert workflow[-1]("/lipids/activate", {"version": version}).status_code == 400


def test_empty_annotation_keeps_matrix_and_exports_headers(workflow, monkeypatch):
    original = setup_lipids(workflow, monkeypatch)
    version = run_lipids(workflow, adducts=["[M+Cl]-"], polarity="neg")
    result = query(workflow, version)
    assert result["candidates"]["total"] == 0 and len(result["features"]) == 4
    response = workflow[-1]("/lipids/export", {"version": version, "kind": "candidates"})
    assert "feature_id" in response.text.splitlines()[0]
    response = workflow[-1](
        "/lipids/export",
        {"version": version, "kind": "matrix", "filters": {"include_unannotated": False}},
    )
    assert pd.read_csv(StringIO(response.text), index_col=0).shape == (40, 0)
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        np.testing.assert_array_equal(workspace.project.workspace.data.X, original.X)


def test_save_reload_manual_state_and_filtered_csv_full_precision(workflow, monkeypatch):
    original = setup_lipids(workflow, monkeypatch)
    version = run_lipids(workflow)
    result = query(workflow, version, feature_id="f0")
    candidate = result["candidates"]["rows"][0]
    workflow[-1](
        "/lipids/review",
        {"version": version, "feature_id": "f0", "candidate_ids": [candidate["candidate_id"]]},
    ).raise_for_status()
    relation = result["isotopes"]["rows"][0]
    workflow[-1](
        "/lipids/review",
        {"version": version, "relation_id": relation["relation_id"], "review": "accepted"},
    ).raise_for_status()
    workflow[-1]("/project/save").raise_for_status()
    path = workflow[-2]()["project"]["path"]
    workflow[-1]("/project/open", {"path": path}).raise_for_status()
    result = query(workflow, version, feature_id="f0")
    assert result["selected"]["f0"] == [candidate["candidate_id"]]
    assert any(r["review"] == "accepted" for r in result["isotopes"]["rows"])
    response = workflow[-1](
        "/lipids/export",
        {
            "version": version,
            "kind": "matrix",
            "filters": {"adduct_mode": "strongest", "candidates": "all"},
        },
    )
    frame = pd.read_csv(StringIO(response.text), index_col=0, float_precision="round_trip")
    np.testing.assert_allclose(frame.to_numpy(), original.X[:, :3], rtol=2e-16)
    assert (
        workflow[-1](
            "/lipids/export",
            {"version": version, "kind": "matrix", "filters": {"adduct_mode": "specified"}},
        ).status_code
        == 400
    )
    workflow[-1]("/analysis/operation", {"operation": "reset", "options": {}}).raise_for_status()
    with workflow[2].access(workflow[1]["X-SCMM-Workspace"]) as workspace:
        assert not annotation_store(workspace.project.workspace.data)["versions"]


def test_builtin_presets_available_without_preferences_and_custom_values_preserved(
    tmp_path, monkeypatch
):
    import json

    from scMM.application.web_lipids import rules_presets, save_rules_preset

    monkeypatch.setenv("SCMM_PREFERENCES", str(tmp_path / "preferences.json"))
    presets = rules_presets()
    assert len(presets) == 5
    assert all(p["rules"] and p["name"] == name for name, p in presets.items())
    assert not (tmp_path / "lipid-rules.json").exists()
    name = next(iter(presets))
    override = {**presets[name], "rules": []}
    (tmp_path / "lipid-rules.json").write_text(json.dumps({name: override}))
    assert rules_presets()[name]["rules"] == []
    result = save_rules_preset("custom", {"schema_version": 1, "rules": []})
    assert len(result) == 6
    assert set(json.loads((tmp_path / "lipid-rules.json").read_text(encoding="utf-8"))) == {
        name,
        "custom",
    }
    with pytest.raises(ValueError, match="已存在"):
        save_rules_preset(name, override)


def test_network_charts_save_manual_mapping_exports_and_failed_update(workflow, monkeypatch):
    setup_lipids(workflow, monkeypatch)
    version = run_lipids(workflow, network={"min_joint_cells": 10})
    body = {"version": version, "view": {"node_limit": 1}}
    response = workflow[-1]("/lipids/charts", body)
    assert response.status_code == 200, response.text
    chart = response.json()
    assert chart["pie"]["denominator"] == 4
    assert sum(r["count"] for r in chart["pie"]["counts"]) == 4
    assert chart["network"]["truncated"] and len(chart["network"]["nodes"]) == 1
    assert not chart["network"]["molecule_nodes"]  # Two isomer candidates per feature.
    before = workflow[-2]()
    invalid = workflow[-1](
        "/lipids/representative", {"version": version, "database_id": "invalid", "feature_id": "f0"}
    )
    assert invalid.status_code == 400 and before == workflow[-2]()
    invalid = workflow[-1](
        "/lipids/charts/save", {"version": version, "view": {"scope": "condition:guessed"}}
    )
    assert invalid.status_code == 400 and before == workflow[-2]()
    invalid = workflow[-1](
        "/lipids/run", {"options": {**options(), "network": {"condition_field": "not-a-field"}}}
    )
    assert invalid.status_code == 400 and before == workflow[-2]()
    assert (
        workflow[-1](
            "/lipids/run", {"options": {**options(), "network": {"support_all": 1.1}}}
        ).status_code
        == 422
    )
    rows = query(workflow, version)["candidates"]["rows"]
    selected = next(r for r in rows if r["feature_id"] == "f0")
    workflow[-1](
        "/lipids/review",
        {"version": version, "feature_id": "f0", "candidate_ids": [selected["candidate_id"]]},
    ).raise_for_status()
    chart = workflow[-1](
        "/lipids/charts", {"version": version, "view": {"graph": "molecule"}}
    ).json()
    assert len(chart["network"]["molecule_nodes"]) == 1
    identity = chart["network"]["nodes"][0]["id"]
    workflow[-1](
        "/lipids/representative", {"version": version, "database_id": identity, "feature_id": "f0"}
    ).raise_for_status()
    workflow[-1](
        "/lipids/charts/save",
        {
            "version": version,
            "view": {"graph": "molecule", "node_limit": 2},
            "filters": {"isotopes": "hide"},
        },
    ).raise_for_status()
    workflow[-1]("/project/save").raise_for_status()
    path = workflow[-2]()["project"]["path"]
    workflow[-1]("/project/open", {"path": path}).raise_for_status()
    assert query(workflow, version)["chart_view"]["graph"] == "molecule"
    assert query(workflow, version)["chart_filters"]["isotopes"] == "hide"
    chart = workflow[-1]("/lipids/charts", {"version": version}).json()
    assert (
        chart["network"]["kind"] == "feature"
    )  # Explicit request defaults override saved settings.
    for kind in [
        "pie",
        "feature_nodes",
        "feature_edges",
        "molecule_nodes",
        "molecule_edges",
        "network_evidence",
        "charts",
    ]:
        response = workflow[-1](
            "/lipids/export", {"version": version, "kind": kind, "view": {"node_limit": 1}}
        )
        assert response.status_code == 200, response.text
        if kind == "feature_nodes":
            frame = pd.read_csv(StringIO(response.text))
            assert len(frame) == 4  # Node cap is never a table-export cap.
            assert set(frame.layer) == {"scmm_input_0"}
        if kind == "charts":
            assert response.json()["network"]["method"] == "spearman"
            assert response.json()["evidence"]


def test_network_condition_changes_stale_download_and_preserve_other_fields(workflow, monkeypatch):
    setup_lipids(workflow, monkeypatch)
    manager, headers = workflow[2], workflow[1]
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.project.workspace.data.obs["condition"] = "control"
    version = run_lipids(workflow, network={"condition_field": "condition", "min_joint_cells": 10})
    response = workflow[-1](
        "/lipids/charts", {"version": version, "view": {"scope": "condition:control"}}
    )
    assert response.status_code == 200
    assert response.json()["network"]["edges"]
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.project.workspace.data.obs["unrelated"] = "new"
    assert get(workflow, "/lipids").json()["versions"][0]["valid"]
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        data = workspace.project.workspace.data
        data.obs.loc[data.obs["sample"] == "a", "condition"] = "treated"
    assert not get(workflow, "/lipids").json()["versions"][0]["valid"]
    for kind in ["charts", "feature_edges", "molecule_nodes", "network_evidence"]:
        assert workflow[-1]("/lipids/export", {"version": version, "kind": kind}).status_code == 400


def test_display_sorting_is_global_and_does_not_change_recommendations(workflow, monkeypatch):
    setup_lipids(workflow, monkeypatch)
    version = run_lipids(workflow)
    original = query(workflow, version)
    sorting = {
        "candidate_sort": "name",
        "candidate_descending": True,
        "relation_sort": "valid_cells",
        "relation_descending": True,
    }
    ordered = query(workflow, version, sorting=sorting)
    names = [r["name"] for r in ordered["candidates"]["rows"]]
    assert names == sorted(names, reverse=True)
    expected = sorted(original["isotopes"]["rows"], key=lambda r: r["valid_cells"], reverse=True)
    pages = [
        query(workflow, version, sorting=sorting, relation_offset=i, limit=1)["isotopes"]["rows"][0]
        for i in range(len(expected))
    ]
    assert [r["relation_id"] for r in pages] == [r["relation_id"] for r in expected]
    assert query(workflow, version)["suggested"] == original["suggested"]
    assert ordered["selected"] == original["selected"]
    exported = workflow[-1](
        "/lipids/export", {"version": version, "kind": "candidates", "sorting": sorting}
    )
    exported.raise_for_status()
    assert pd.read_csv(StringIO(exported.text))["name"].tolist() == names
    assert (
        workflow[-1](
            "/lipids/query", {"version": version, "sorting": {"candidate_sort": "unknown"}}
        ).status_code
        == 422
    )
    features = get(workflow, "/analysis/features?query=Synthetic+B&sort=mz").json()
    assert features["total"] > 0
    assert all("Synthetic B" in r["label"] for r in features["rows"])
