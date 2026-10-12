"""Preview process isolation, result ownership and complete window rendering."""

import asyncio
import json
import os
from concurrent.futures import Future
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
from scMM.ui.app import ProjectWorkspace
from scMM.ui.raw_components import cell_detection_figure


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


def controlled_ui(tmp_path, monkeypatch):
    project, catalog = setup_project(tmp_path)
    project.manifest["manual_parameters"] = True
    ui = ProjectWorkspace(catalog.roots, project_root=tmp_path)
    ui.activate(project)
    ui._open_raw()
    future = Future()
    submitted = []

    def submit(request):
        submitted.append(deepcopy(request))
        return future, project.folder / "processing" / "fake-state.json"

    monkeypatch.setattr("scMM.ui.app.submit_preview", submit)
    return ui, future, submitted


def complete(future, request, tmp_path):
    state = tmp_path / "test-state.json"
    future.set_result(run_preview({**request, "created_at": "test"}, state))


def test_ui_returns_immediately_rejects_duplicates_and_applies_then_saves(tmp_path, monkeypatch):
    ui, future, submitted = controlled_ui(tmp_path, monkeypatch)
    ui.project.dirty = False
    ui.run(ui._preview_cells)
    assert not future.done() and len(submitted) == 1
    assert ui.preview_button.disabled and ui.preview_button.loading
    assert "已启动" in ui.message.object and ui.components.cell_download.disabled
    ui.poll()  # Polling unrelated batch state must still service preview completion.
    with pytest.raises(ValueError, match="已有细胞预览"):
        ui._preview_cells()
    with pytest.raises(ValueError, match="等待"):
        ui._confirm_preview()
    complete(future, submitted[0], tmp_path)
    ui.poll()
    assert not ui.preview_button.disabled and not ui.preview_button.loading
    assert ui.project.dirty and not ui.components.cell_download.disabled
    assert not ui.project.samples[0]["preview"]["confirmed"]
    ui._confirm_preview()
    ui._save()
    restored = ui.store.open(ui.project.folder)
    assert restored.samples[0]["preview"]["confirmed"]
    assert child_path(restored.folder, restored.samples[0]["preview"]["artifact"]).is_dir()


@pytest.mark.parametrize("change", ["parameter", "sample", "reopen", "project", "file", "strategy"])
def test_ui_discards_results_after_context_changes(tmp_path, monkeypatch, change):
    ui, future, submitted = controlled_ui(tmp_path, monkeypatch)
    ui._preview_cells()
    complete(future, submitted[0], tmp_path)
    original = ui.project
    if change == "parameter":
        widget = ui.components.processing.parameter_widgets["cell_snr"]
        before = widget.value
        widget.value = before + 1
        widget.value = before  # Editing back must not revive an invalidated job.
    elif change == "sample":
        ui.raw_sample.value = ui.project.samples[1]["id"]
    elif change == "reopen":
        ui._open_raw()
    elif change == "project":
        ui.activate(ui.store.create("other"))
    elif change == "file":
        with open(ui.project.samples[0]["path"], "ab") as handle:
            handle.write(b"\n")
    else:
        ui.project.manifest["feature_strategy"] = "independent"
    ui.poll()
    assert "结果未应用" in ui.preview_status.object
    assert all("preview" not in s for s in original.samples)
    assert ui.components.cell_download.disabled
    assert not ui.preview_button.disabled


def test_ui_failure_can_retry_and_closing_drops_pending_job(tmp_path, monkeypatch):
    ui, future, _submitted = controlled_ui(tmp_path, monkeypatch)
    ui._preview_cells()
    future.set_exception(RuntimeError("reader failed"))
    ui.poll()
    assert "reader failed" in ui.preview_status.object
    assert ui.error_notice.visible and not ui.preview_button.disabled
    assert ui.components.cell_download.disabled
    replacement = Future()
    monkeypatch.setattr("scMM.ui.app.submit_preview", lambda _: (replacement, tmp_path / "status"))
    ui._preview_cells()
    ui._close_session(None)
    assert replacement.cancelled() and ui._cell_preview_job is None


def test_failed_render_leaves_project_and_download_unchanged(tmp_path, monkeypatch):
    ui, future, submitted = controlled_ui(tmp_path, monkeypatch)
    ui._preview_cells()
    complete(future, submitted[0], tmp_path)
    snapshot = deepcopy(ui.project.manifest)
    ui.project.dirty = False

    def fail(_result):
        raise ValueError("broken window metadata")

    monkeypatch.setattr("scMM.ui.app.cell_detection_figure", fail)
    ui.poll()
    assert ui.project.manifest == snapshot and not ui.project.dirty
    assert ui.components.cell_download.disabled
    assert "broken window metadata" in ui.preview_status.object
    assert not ui.preview_button.disabled


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
