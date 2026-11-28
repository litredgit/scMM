"""Exercise installed method protocols and optional analyses through authenticated APIs."""

import json
import os
import time
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from zipfile import ZipFile

import numpy as np
import pytest
from anndata import read_h5ad

from scMM.plugins._registry import MethodRegistry
from tests.support.method_package import install_method_package
from tests.support.workflow import get, import_data, operation, raw_samples

PLUGIN = "fixture-methods"
VERSION = "1.2.0"


@pytest.fixture
def workflow_plugins(request, tmp_path, monkeypatch):
    mode = getattr(request, "param", "methods")
    if mode == "bundled":
        return ("network", "supervised", "time")
    if mode == "default":
        return ()
    package = install_method_package(tmp_path / "method-site")
    monkeypatch.syspath_prepend(str(package))
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join(filter(None, (str(package), os.environ.get("PYTHONPATH"))))
    )
    return (PLUGIN,)


def run(workflow, method, **kwargs):
    return workflow[-1](
        "/methods/run", {"method_id": f"{PLUGIN}:{method}", "version": VERSION, **kwargs}
    )


@pytest.mark.parametrize("workflow_plugins", ["default"], indirect=True)
def test_default_core_rejects_optional_execution(workflow):
    import_data(workflow)
    client, _, manager, *_, current, post = workflow
    configuration = client.get("/api/v1/configuration").json()
    assert configuration["enabled_plugins"] == configuration["methods"] == []
    assert set(manager.plugins.bundled) == set()
    before = current()
    for name, params in (
        ("network", {}),
        ("train", {"label_key": "group"}),
        ("explain_shap", {}),
        ("save_latent", {"key": "latent"}),
    ):
        response = post("/analysis/operation", {"operation": name, "options": params})
        assert response.status_code == 409 and response.json()["error"]["code"] == "plugin_disabled"
    response = post(
        "/analysis/time",
        {
            "operation": "velocity",
            "options": {
                "key": "speed",
                "time_key": "missing",
                "time_kind": "experimental_time",
                "unit": "seconds",
            },
        },
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "plugin_disabled"
    assert post("/analysis/plot", {"kind": "network_plot"}).status_code == 409
    assert current() == before
    operation(workflow, "reduce", {"method": "pca", "store_key": "basic_pca", "n_components": 2})
    operation(
        workflow, "cluster", {"method": "kmeans", "use_rep": "basic_pca", "key": "basic_clusters"}
    )
    assert run(workflow, "report", options={"column": "group"}).status_code == 400


@pytest.mark.parametrize("workflow_plugins", ["bundled"], indirect=True)
def test_saved_optional_result_remains_readable_with_plugin_disabled(workflow):
    import_data(workflow)
    operation(workflow, "network", {"top_features": 8, "min_abs_correlation": 0})
    workflow[-1]("/analysis/plot", {"kind": "network_plot"}).raise_for_status()
    path = workflow[-2]()["project"]["path"]
    workflow[-1]("/project/save").raise_for_status()
    workflow[2].plugins = MethodRegistry()
    workflow[-1]("/project/open", {"path": path}).raise_for_status()
    assert get(workflow, "/analysis/results/network").json()["table"]["total"] > 0
    assert get(workflow, "/analysis/figures/network_plot").json()["data"]
    assert get(workflow, "/results/download?kind=network").status_code == 200


def test_installed_methods_use_core_transactions_and_read_only_results(workflow):
    data = import_data(workflow)
    descriptors = workflow[0].get("/api/v1/configuration").json()["methods"]
    assert len(descriptors) == 7 and {item["version"] for item in descriptors} == {VERSION}
    before = workflow[-2]()
    assert run(workflow, "scale", version="0.9").status_code == 400
    assert run(workflow, "scale", options={"scale": 0}).status_code == 400
    assert run(workflow, "scale", options={"constructor": "unused"}).status_code == 400
    preview = run(workflow, "scale", preview=True)
    assert preview.status_code == 200 and preview.json()["value"]["qc"]["figure"]
    assert workflow[-2]() == before
    run(workflow, "scale").raise_for_status()
    run(workflow, "project", output_key="fixture_embedding").raise_for_status()
    run(
        workflow, "cluster", embedding="fixture_embedding", output_key="fixture_clusters"
    ).raise_for_status()
    assert run(workflow, "project", output_key="fixture_embedding").status_code == 400
    info = get(workflow, "/analysis").json()
    assert "fixture_embedding" in info["embeddings"] and "fixture_clusters" in info["observations"]
    annotation = run(workflow, "annotate", source="current").json()["value"]
    assert annotation["candidates"] == 1
    reviewed = workflow[-1](
        "/lipids/query", {"source": "current", "version": annotation["version"]}
    )
    assert reviewed.status_code == 200, reviewed.text
    run(workflow, "report", options={"column": "group"}).raise_for_status()
    path = f"/methods/reports/{PLUGIN}:report"
    result = get(workflow, path)
    assert result.status_code == 200, result.text
    report = result.json()
    np.testing.assert_array_equal(
        [row["value"] for row in report["table"]["rows"]], data.X[:, 0] * 2
    )
    assert report["figure"]["layout"]["meta"]["method_result_identity"]
    project_path = workflow[-2]()["project"]["path"]
    workflow[-1]("/project/save").raise_for_status()
    workflow[2].plugins = MethodRegistry()
    workflow[-1]("/project/open", {"path": project_path}).raise_for_status()
    assert get(workflow, path).json()["table"] == report["table"]
    assert get(workflow, f"{path}?download=true").text.count("\n") == data.n_obs + 1
    token = get(workflow, "/analysis").json()["token"]
    params = urlencode({"kind": "report_zip", "key": json.dumps(token)})
    archive = get(workflow, f"/results/download?{params}")
    assert archive.status_code == 200, archive.text if archive.status_code != 200 else ""
    with ZipFile(BytesIO(archive.content)) as bundle:
        assert any("fixture-methods-report" in name for name in bundle.namelist())
    operation(workflow, "normalize", {"method": "total"})
    assert get(workflow, path).status_code == 400


def _poll(workflow, path, read, pending):
    for _ in range(300):
        state = read(get(workflow, path).json())
        if state["status"] not in pending:
            return state
        time.sleep(0.1)
    pytest.fail(f"Task timed out: {state}")


def test_extraction_plugin_workers_share_frozen_selection_and_cache_identity(workflow):
    samples = raw_samples(workflow)
    sample = samples[0]["id"]
    post = workflow[-1]
    parameters = deepcopy(workflow[6].manifest["parameters"])
    parameters["method_plugins"] = {
        "cell_detection": {"id": f"{PLUGIN}:detect", "version": VERSION, "options": {}},
        "cell_extraction": {"id": f"{PLUGIN}:quantify", "version": VERSION, "options": {}},
    }
    post("/parameters", {"parameters": parameters}, "PUT").raise_for_status()
    post("/raw/open", {"sample_id": sample}).raise_for_status()
    preview = post("/raw/preview", {"sample_id": sample, "parameters": parameters})
    preview.raise_for_status()
    status = _poll(
        workflow, "/raw/preview", lambda state: state, {"queued", "running", "succeeded"}
    )
    assert status["status"] == "ready", status
    collected = post("/raw/preview/collect", {"job_id": preview.json()["value"]["id"]})
    assert collected.json()["value"]["cell_count"] == 1
    started = post("/extraction/start")
    started.raise_for_status()
    batch = _poll(workflow, "/extraction/batches", lambda rows: rows[0], {"queued", "running"})
    assert batch["status"] == "completed", batch
    assert batch["samples"][0]["reused_preview"] is True
    assert [row["cells"] for row in batch["samples"]] == [1, 1]
    batch_dir = Path(started.json()["value"]["path"]).parent
    request = json.loads((batch_dir / "request.json").read_text())
    selection = request["parameters"]["method_plugins"]
    assert selection["cell_extraction"]["options"] == {"scale": 2.0}
    assert read_h5ad(batch_dir / batch["samples"][1]["output"]).n_obs == 1
    parameters["method_plugins"]["cell_extraction"]["options"] = {"scale": 3}
    post("/parameters", {"parameters": parameters}, "PUT").raise_for_status()
    assert (
        post("/extraction/start", {"retry_path": started.json()["value"]["path"]}).status_code
        == 409
    )


def test_plugin_labeled_outputs_reject_reordered_axes_and_report_progress(workflow, monkeypatch):
    from dataclasses import replace

    import pandas as pd

    import_data(workflow)
    current = workflow[-2]
    registry = workflow[2].plugins
    key = f"{PLUGIN}:scale"
    registered = registry.methods[key]

    def reversed_observations(inputs, _):
        return pd.DataFrame(
            inputs.values, index=inputs.observation_ids, columns=inputs.feature_ids
        ).iloc[::-1]

    monkeypatch.setitem(
        registry.methods,
        key,
        replace(registered, method=replace(registered.method, run=reversed_observations)),
    )
    before = current()
    assert "观测 ID" in run(workflow, "scale").json()["error"]["message"]
    assert current() == before
    monkeypatch.setitem(registry.methods, key, registered)
    run(workflow, "scale").raise_for_status()
    run(workflow, "report", options={"column": "group"}).raise_for_status()
    progress = get(workflow, "/analysis/workflow-status").json()
    assert progress["/preprocess"] and progress["/analysis"]


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf")])
def test_nonfinite_preprocessing_output_is_rejected_atomically(workflow, monkeypatch, nonfinite):
    from dataclasses import replace

    from numpy import testing

    import_data(workflow)
    registry = workflow[2].plugins
    key = f"{PLUGIN}:scale"
    registered = registry.methods[key]
    manager, current = workflow[2], workflow[-2]
    identity = current()["workspace_id"]
    with manager.access(identity) as workspace:
        state = workspace.project.workspace
        before = (state.token, state.data.X.copy(), state.history())

    def bad_output(inputs, _):
        values = inputs.values.copy()
        values[0, 0] = nonfinite
        return values

    monkeypatch.setitem(
        registry.methods,
        key,
        replace(registered, method=replace(registered.method, run=bad_output)),
    )
    response = run(workflow, "scale")
    assert response.status_code >= 400
    assert "有限数值" in response.json()["error"]["message"]
    with manager.access(identity) as workspace:
        state = workspace.project.workspace
        assert state.token == before[0] and state.history() == before[2]
        testing.assert_array_equal(state.data.X, before[1])


def test_measurement_root_candidates_are_available_in_statistics(workflow):
    import_data(workflow)
    post = workflow[-1]
    post(
        "/ions/initialize", {"linearity": "unknown", "origin_kind": "imported_feature"}
    ).raise_for_status()
    root = get(workflow, "/ions/info").json()["roots"][0]["id"]
    run(workflow, "annotate", source=root).raise_for_status()
    assert get(workflow, "/analysis/annotated-features").json()["features"] == ["f0"]
    target = get(workflow, "/analysis/feature-review-target?feature=f0").json()
    assert target == {"source": root, "feature": "f0"}
    assert get(workflow, "/analysis/workflow-status").json()["/annotation"]


def test_heatmap_uses_full_positive_classifier_markers_for_selected_group(workflow):
    import pandas as pd

    import_data(workflow)
    manager, current = workflow[2], workflow[-2]
    rows = pd.DataFrame(
        {
            "group": ["A"] * 250 + ["B"] * 2,
            "weight": [1.0] * 251 + [-0.1],
            "rank": [*range(1, 251), 1, 2],
            "feature_id": [f"a{i}" for i in range(250)] + ["positive", "negative"],
        }
    )
    with manager.access(current()["workspace_id"]) as workspace:
        state = workspace.project.workspace
        state.put_result("markers", {"method": "classifier", "table": rows}, state.token)
    table = get(workflow, "/analysis/results/markers?limit=1000").json()["table"]
    assert len(table["rows"]) == table["total"] == 252
    response = get(workflow, "/analysis/marker-features?group=B")
    assert response.json() == {"groups": ["A", "B"], "features": ["positive"]}
