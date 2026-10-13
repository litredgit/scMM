"""Preview process isolation, result ownership and complete window rendering."""

import asyncio
import json
import os
from copy import deepcopy

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from test_project_batch import setup_project

from scMM.application import CellDetectionPreview, RawPreviewService
from scMM.application.cell_preview import run_preview, submit_preview
from scMM.application.preview_cache import file_identity, prepare_shared_targets
from scMM.application.processing import ProcessingParameters
from scMM.application.project_batch import batches, preflight
from scMM.application.projects import child_path
from scMM.file.data import CyESIData
from scMM.plot.raw import cell_detection_figure


def preview_request(project, catalog):
    return {
        "created_at": "test",
        "project_folder": str(project.folder),
        "manifest": deepcopy(project.manifest),
        "sample_id": project.samples[0]["id"],
        "parameters": dict(project.manifest["parameters"]),
        "roots": [(r.label, str(r.path)) for r in catalog.roots],
        "inputs": {s["path"]: file_identity(s["path"]) for s in project.samples},
    }


@pytest.mark.parametrize("strategy", ["shared", "independent"])
def test_preview_worker_matches_full_extraction_and_reuses_cache(tmp_path, monkeypatch, strategy):
    project, catalog = setup_project(tmp_path)
    project.manifest.update(feature_strategy=strategy, manual_parameters=True)
    request = preview_request(project, catalog)
    snapshot = deepcopy(request)
    state = project.folder / "processing" / "preview-state.json"
    result = run_preview(request, state)
    assert request == snapshot
    assert "preview" not in project.samples[0]
    saved = CyESIData.read_h5ad(child_path(project.folder, result["artifact"]) / "data.h5ad")
    params = ProcessingParameters(**result["parameters"])
    preview = RawPreviewService(catalog).open("data", project.samples[0]["path"])
    targets = (
        prepare_shared_targets(project, preflight(project, catalog))
        if strategy == "shared"
        else None
    )
    expected = preview.cell_detection(params, targets=targets)
    pd.testing.assert_frame_equal(result["detection"].traces, expected.traces)
    pd.testing.assert_frame_equal(
        saved.data.reset_index(drop=True), preview.last_dataset.data.reset_index(drop=True)
    )
    assert result["detection"].window_ranges == expected.window_ranges
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "succeeded"

    request["manifest"]["samples"][0]["preview"] = {
        "artifact": result["artifact"],
        "parameters": result["parameters"],
    }

    def no_open(*args, **kwargs):
        raise AssertionError("validated preview must be reused without reopening raw data")

    monkeypatch.setattr(RawPreviewService, "open", no_open)
    reused = run_preview(request, state)
    assert reused["reused"] and reused["artifact"] == result["artifact"]
    pd.testing.assert_frame_equal(
        reused["detection"].traces, expected.traces, check_dtype=False, check_exact=True
    )


def test_automatic_ranges_are_candidate_only_and_failures_are_recorded(tmp_path):
    project, catalog = setup_project(tmp_path)
    project.manifest.update(auto_ranges=True, manual_parameters=False)
    request = preview_request(project, catalog)
    state = project.folder / "processing" / "preview-state.json"
    result = run_preview(request, state)
    assert result["parameters"]["mz_min"] == 140
    assert result["parameters"]["mz_max"] == 160
    assert all(value["auto_mz_range"] == [140, 160] for value in result["ranges"].values())
    assert all("auto_mz_range" not in sample for sample in project.samples)
    with open(project.samples[0]["path"], "ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValueError, match="Input changed"):
        run_preview(request, state)
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "failed"


def test_actual_spawned_worker_does_not_block_event_loop(tmp_path):
    project, catalog = setup_project(tmp_path)
    request = preview_request(project, catalog)

    async def exercise():
        future, state = submit_preview(request)
        ticks = 0
        while not future.done():
            ticks += 1
            await asyncio.sleep(0.01)
        result = future.result(timeout=30)
        assert ticks > 1
        assert result["detection"].cell_count == 2
        assert json.loads(state.read_text(encoding="utf-8"))["pid"] != os.getpid()
        assert batches(project) == []  # Preview status is not an extraction batch.

    asyncio.run(asyncio.wait_for(exercise(), timeout=30))


def test_spawn_failure_does_not_leave_queued_status(tmp_path, monkeypatch):
    project, catalog = setup_project(tmp_path)

    def fail(**kwargs):
        raise OSError("no process resources")

    monkeypatch.setattr("scMM.application.cell_preview.ProcessPoolExecutor", fail)
    with pytest.raises(OSError, match="no process resources"):
        submit_preview(preview_request(project, catalog))
    paths = list((project.folder / "processing/preview-jobs").glob("*/state.json"))
    assert (
        len(paths) == 1 and json.loads(paths[0].read_text(encoding="utf-8"))["status"] == "failed"
    )


def test_shared_control_edits_require_applying_project_parameters(tmp_path):
    project, catalog = setup_project(tmp_path)
    project.manifest["manual_parameters"] = True
    request = preview_request(project, catalog)
    request["parameters"]["ppm_tol"] = 250.0
    with pytest.raises(ValueError, match="共同特征参数已编辑"):
        run_preview(request, project.folder / "processing" / "preview-state.json")
    assert all("preview" not in sample for sample in project.samples)


def test_window_rendering_matches_vrect_and_keeps_thousands_of_windows(monkeypatch):
    frame = pd.DataFrame(
        {"rt_seconds": np.arange(6000) / 3, "reference_0": np.ones(6000), "cell_apex": False}
    )
    frame.loc[::2, "cell_apex"] = True
    result = CellDetectionPreview(
        frame, (150.0,), tuple((i, i + 1) for i in range(0, 6000, 2)), 3000
    )
    expected = go.Figure(go.Scatter(x=[0, 1], y=[1, 2]))
    expected.add_vrect(
        x0=frame.rt_seconds.iloc[0],
        x1=frame.rt_seconds.iloc[1],
        fillcolor="green",
        opacity=0.12,
        line_width=0,
    )

    def no_vrect(*args, **kwargs):
        raise AssertionError("must construct shapes in bulk")

    monkeypatch.setattr(go.Figure, "add_vrect", no_vrect)
    figure = cell_detection_figure(result)
    assert len(figure.layout.shapes) == 3000
    assert figure.layout.shapes[0].to_plotly_json() == expected.layout.shapes[0].to_plotly_json()
    assert figure.layout.shapes[-1].x1 == frame.rt_seconds.iloc[-1]
    np.testing.assert_array_equal(figure.data[1].x, frame.loc[frame.cell_apex, "rt_seconds"])
    assert result.traces is frame
