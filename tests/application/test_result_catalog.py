"""Cross-entry result coverage, independent metadata and read-only artifacts."""

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from scMM.application.result_catalog import (
    RESULTS,
    frontend_contract,
    related_results,
    restore_report,
    serialize_reports,
    stale_metadata_results,
)


def test_frontend_contract_matches_registered_results():
    path = (
        Path(__file__).resolve().parents[2] / "frontend/src/features/analysis/results.contract.json"
    )
    assert json.loads(path.read_text()) == frontend_contract()
    assert set(frontend_contract()["resultPlots"]) == set(RESULTS)


def test_shap_inherits_model_dependencies_and_all_plot_variants_invalidate():
    reports = {
        "supervised": {"label_key": "condition", "group_key": "subject"},
        "shap": {"parameters": {}},
    }
    assert stale_metadata_results(reports, {"batch"}, readonly=True) == set()
    assert stale_metadata_results(reports, {"condition"}, readonly=True) == {"supervised", "shap"}
    assert related_results({"supervised"}) == {"supervised", "shap"}
    assert stale_metadata_results({"shap": {}}, {"batch"}, readonly=True) == {"shap"}
    assert stale_metadata_results({"supervised": {}}, {"batch"}, readonly=True) == {
        "supervised",
        "shap",
    }


def test_empty_network_and_full_correlation_roundtrip_without_models():
    graph = nx.Graph()
    graph.add_nodes_from(["isolated", "other"])
    correlation = pd.DataFrame(
        [[1.0, 0.12345678901234567], [0.12345678901234567, 1.0]],
        index=["isolated", "other"],
        columns=["isolated", "other"],
    )
    correlation.index.name = "reference_feature"
    correlation.columns.name = "target_feature"
    table = pd.DataFrame(columns=["source", "target", "correlation"])
    value = {
        "graph": graph,
        "correlation": correlation,
        "table": table,
        "parameters": {"method": "pearson"},
    }
    report = serialize_reports({"network": value})["network"]
    loaded = restore_report("network", json.loads(json.dumps(report)))
    assert list(loaded["table"]) == list(table)
    assert list(loaded["graph"]) == ["isolated", "other"]
    pd.testing.assert_frame_equal(loaded["correlation"], correlation)
    pd.testing.assert_frame_equal(value["correlation"], correlation)
    legacy = restore_report("network", {"table": [], "nodes": ["alone"]})
    assert "correlation" not in legacy
    assert list(legacy["graph"]) == ["alone"]


def test_live_reports_keep_tensor_precision_and_saved_dependencies():
    values = np.array([[0.12345678901234567, -0.8765432109876543]])
    tensor = {
        "table": pd.DataFrame({"feature_id": ["a", "b"], "mean_abs_shap": abs(values[0])}),
        "values": values,
        "_observation_dependencies": ["condition"],
    }
    report = serialize_reports({"shap": tensor})["shap"]
    loaded = restore_report(
        "shap", json.loads(json.dumps(report, default=lambda value: value.tolist()))
    )
    np.testing.assert_array_equal(loaded["values"], values)
    assert stale_metadata_results({"shap": report}, {"condition"}, readonly=True) == {"shap"}
    assert stale_metadata_results({"shap": report}, {"batch"}, readonly=True) == set()
    assert "_observation_dependencies" not in loaded
    with pytest.raises(ValueError):
        restore_report("unknown", {})


def test_http_result_and_plot_whitelists_cover_catalog():
    from typing import get_args

    from scMM.api.workflow_schemas import Invalidate, Plot

    assert set(get_args(get_args(Invalidate.model_fields["names"].annotation)[0])) == RESULTS.keys()
    plot_kinds = set(get_args(Plot.model_fields["kind"].annotation))
    assert {kind for spec in RESULTS.values() for kind in spec.plots} <= plot_kinds
