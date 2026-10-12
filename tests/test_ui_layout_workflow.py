from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pandas as pd
import panel as pn
from anndata import AnnData
from bokeh.document import Document

from scMM.application import StorageRoot
from scMM.application.parameters import load_defaults
from scMM.ui.app import ProjectWorkspace
from scMM.ui.downloads import FileDownload
from scMM.ui.preflight import request_view


def workspace(tmp_path):
    ui = ProjectWorkspace((StorageRoot("data", tmp_path),), project_root=tmp_path)
    ui.name.value = "布局项目"
    ui._create()
    return ui


def scan(index):
    return pd.DataFrame({"mz": [150.0], "intensity": [float(index + 1)]}), {
        "scan_index": index,
        "rt_seconds": index * 2.0,
        "ms_level": 1,
        "native_id": f"scan={index}",
    }


def test_scan_selection_automatically_updates_and_old_results_are_ignored(tmp_path):
    raw = workspace(tmp_path).components
    raw.preview = SimpleNamespace(
        total_ion_chromatogram=lambda **_: pd.DataFrame(
            {
                "scan_index": [0, 2, 4],
                "rt_seconds": [0.0, 4.0, 8.0],
            }
        ),
        single_spectrum=scan,
    )
    raw._scan_catalog()
    assert "Scan 0" in raw.scan_pane.object.layout.title.text
    raw.scan_time.value = 3.9
    assert raw.scan_index.value == 2
    assert raw.scan_slider.value == 4
    assert "scan=2" in raw.scan_pane.object.layout.title.text
    stale = (raw._scan_generation, raw.preview, 2)
    raw._seek_scan(step=1)
    assert raw.scan_index.value == 4 and raw.scan_next.disabled
    raw._display_scan(stale, scan(2))
    assert "Scan 4" in raw.scan_pane.object.layout.title.text

    def fail(_):
        raise OSError("reader failed")

    raw.preview.single_spectrum = fail
    raw.scan_index.value = 2
    assert "reader failed" in raw.scan_status.object
    assert not raw.scan_pane.object.data
    raw.preview.single_spectrum = scan
    raw.scan_index.value = 0
    assert "Scan 0" in raw.scan_pane.object.layout.title.text
    raw._clear_raw_view()
    raw._display_scan(stale, scan(2))
    assert not raw.scan_pane.object.data and raw.scan_index.disabled


def test_scan_background_queue_uses_latest_request_and_survives_failure(tmp_path):
    raw = workspace(tmp_path).components
    preview = SimpleNamespace(single_spectrum=scan)
    raw.preview = preview
    jobs, callbacks = [], []

    class Executor:
        def submit(self, function, index):
            future = Future()
            jobs.append((index, future))
            return future

    raw._scan_executor = Executor()
    raw._scan_doc = SimpleNamespace(add_next_tick_callback=callbacks.append)
    raw._scan_generation = 1
    raw._scan_pending = (1, preview, 0)
    raw._start_scan()
    raw._scan_generation = 3
    raw._scan_pending = (3, preview, 4)
    jobs[0][1].set_exception(OSError("stale failure"))
    callbacks.pop(0)()
    assert [index for index, _ in jobs] == [0, 4]
    assert "stale failure" not in raw.scan_status.object
    jobs[1][1].set_result(scan(4))
    callbacks.pop(0)()
    assert "Scan 4" in raw.scan_pane.object.layout.title.text
    assert raw._scan_future is None


def test_snr_controls_output_names_and_saved_item_confirmation(tmp_path):
    ui = workspace(tmp_path)
    widgets = ui.components.processing.parameter_widgets
    assert widgets["extraction_method"].value == "snr_v1"
    assert not widgets["peak_snr"].visible and widgets["feature_snr_threshold"].visible
    widgets["extraction_method"].value = "legacy"
    assert widgets["peak_snr"].visible and not widgets["feature_snr_threshold"].visible
    ui.project.workspace.replace(AnnData(np.ones((3, 2))))
    ui.analysis.refresh()
    ui.go(6)
    figures = next(
        panel for panel in ui.results_page.select(pn.Accordion) if panel._names == ["当前分析图形"]
    )
    assert not figures[0].objects
    ui.analysis.embedding_plot.object.update_layout(title="latest result")
    figures.active = [0]
    tabs = figures[0][0]
    assert tabs.dynamic
    assert tabs[0] is not ui.analysis.embedding_plot
    assert tabs[0].object.layout.title.text == "latest result"
    ui.go(5)
    ui.analysis.embedding_plot.object.update_layout(title="recomputed result")
    ui.go(6)
    assert figures[0][0][0].object.layout.title.text == "recomputed result"
    assert figures[0][0] is tabs
    figures.active = []
    assert figures[0][0] is tabs
    assert ui.h5ad_download.disabled
    ui._save()
    assert ui.h5ad_download.filename.startswith("布局项目_20")
    ui.h5ad_download_name.value = "自定义.h5ad"
    ui.analysis.export_name.value = "独立导出.h5ad"
    ui._save()
    assert ui.h5ad_download.filename == "自定义.h5ad"
    assert ui.analysis.export_name.value == "独立导出.h5ad"
    ui.h5ad_download_name.value = "../bad.h5ad"
    assert ui.h5ad_download.disabled
    ui.h5ad_download_name.value = "自定义.h5ad"
    ui.analysis.confirm_save.value = True
    ui.analysis._save()
    assert (ui.project.folder / "exports" / "独立导出.h5ad").is_file()
    ui._close_project()
    manager = ui.saved_items
    manager.project.value = str(next(iter(ui.store.list()))["path"])
    manager.plan_project()
    assert manager.move_button.disabled
    manager.confirm.value = True
    assert not manager.move_button.disabled
    manager.move()
    assert not ui.store.list()
    manager.restore()
    assert len(ui.store.list()) == 1


def test_preflight_is_readable_without_mutating_request():
    from copy import deepcopy
    from dataclasses import asdict

    base = asdict(load_defaults().processing)
    request = {
        "feature_strategy": "independent",
        "parameters": base,
        "samples": [
            {"name": "A", "parameters": {**base}, "parameter_source": "project"},
            {
                "name": "B",
                "parameters": {**base, "cell_snr": 8.0},
                "parameter_source": "sample",
            },
        ],
    }
    before = deepcopy(request)
    view = request_view(request, automatic_range=True)
    tables = view.select(pn.pane.DataFrame)
    common = tables[0].object
    assert {"Parameter", "Value", "Unit", "来源"} <= set(common.columns)
    assert "snr_v1" in common.Value.tolist()
    differences = tables[1].object
    assert differences.iloc[0]["与公共参数的差异"] == "一致"
    assert "cell_snr = 8" in differences.iloc[1]["与公共参数的差异"]
    assert differences["参数来源"].tolist() == ["项目默认", "样本覆盖"]
    assert differences["范围来源"].tolist() == ["自动计算", "已配置"]
    assert request == before


def test_mounted_download_can_be_cleared_and_retransferred():
    from io import BytesIO

    payload = [b"first revision"]
    download = FileDownload(filename="result.csv", callback=lambda: BytesIO(payload[0]))
    document = Document()
    model = download.get_root(document)
    document.add_root(model)
    download._transfer()
    first = model.data
    assert first
    download.data = None
    assert download.data is None and model.data == ""
    payload[0] = b"second revision"
    download._transfer()
    assert model.data and model.data != first
    download._cleanup(model)
