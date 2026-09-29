import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from bokeh.document import Document

from scMM.application import StorageRoot
from scMM.ui.app import ProjectWorkspace


def workspace(tmp_path):
    ui = ProjectWorkspace((StorageRoot("data", tmp_path),), project_root=tmp_path)
    ui.name.value = "项目"
    ui._create()
    return ui


def test_project_steps_preflight_persistence_and_reset(tmp_path):
    ui = workspace(tmp_path)
    with pytest.raises(ValueError, match="先审核"):
        ui.go(4)
    data = AnnData(
        np.arange(1.0, 25.0).reshape(6, 4),
        obs=pd.DataFrame({"sample": ["a"] * 3 + ["b"] * 3}, index=list("abcdef")),
    )
    ui.project.workspace.replace(data)
    ui.analysis.refresh()
    ui.go(4)
    ui.analysis.min_total.value = 30.0
    ui._preview_operation()
    assert ui.project.workspace.data.n_obs == 6
    ui.apply_confirm.value = True
    ui.analysis.min_total.value = 50.0
    with pytest.raises(ValueError, match="重新检查"):
        ui._apply_operation()
    ui._preview_operation()
    ui.apply_confirm.value = True
    ui._apply_operation()
    assert ui.project.workspace.data.n_obs < 6
    ui._save()
    restored = ui.store.open(ui.project.folder)
    ui.activate(restored)
    ui.reset_confirm.value = True
    ui._reset()
    assert ui.project.workspace.data.n_obs == 6
    with pytest.raises(ValueError, match="保存项目"):
        ui._create()


def test_project_pages_serialize(tmp_path):
    ui = workspace(tmp_path)
    ui.project.workspace.replace(AnnData(np.ones((4, 3))))
    ui.analysis.refresh()
    doc = Document()
    root = ui.panel.get_root(doc)
    doc.add_root(root)
    for index in (0, 1, 4, 5, 6):
        ui.go(index)
        doc.validate()
        assert doc.to_json()
    # Raw and task layouts should serialize even before sample files exist.
    for page in (ui.raw_page, ui.batch_page):
        separate = Document()
        model = page.get_root(separate)
        separate.add_root(model)
        assert separate.to_json()
        page._cleanup(model)
    ui.panel._cleanup(root)


def test_saved_reports_figures_and_parameter_invalidation(tmp_path):
    ui = workspace(tmp_path)
    ui.project.workspace.replace(
        AnnData(
            np.arange(1.0, 49.0).reshape(12, 4),
            obs=pd.DataFrame({"group": ["a"] * 6 + ["b"] * 6}, index=[f"c{i}" for i in range(12)]),
        )
    )
    ui.analysis.refresh()
    ui.analysis.run(ui.analysis._differentiate)
    assert "differential" in ui.project.workspace.results
    ui._save()
    assert "differential" in ui.project.saved_reports
    reopened = ui.store.open(ui.project.folder)
    assert "volcano" in reopened.views["figures"]
    ui.activate(reopened)
    assert "differential" in ui.project.saved_reports
    assert not ui.project.workspace.results
    ui.analysis.diff_method.value = "welch"
    assert "differential" not in ui.project.saved_reports
    assert "volcano" not in ui.project.views["figures"]
    ui._save()
    assert "differential" not in ui.store.open(ui.project.folder).saved_reports


def test_additive_embedding_keeps_unrelated_results(tmp_path):
    ui = workspace(tmp_path)
    ui.project.workspace.replace(
        AnnData(
            np.arange(1.0, 49.0).reshape(12, 4),
            obs=pd.DataFrame({"group": ["a"] * 6 + ["b"] * 6}, index=[f"c{i}" for i in range(12)]),
        )
    )
    ui.project.workspace.differential("group", "a", "b")
    ui.project.workspace.reduce("pca", store_key="X_pca")
    assert "differential" in ui.project.workspace.results
    assert not ui.project.workspace.result("differential")["table"].empty


def test_task_dock_preserves_errors_and_is_not_in_page_flow(tmp_path):
    ui = workspace(tmp_path)

    def fail():
        raise ValueError("test failure")

    ui.run(fail)
    assert ui.error_notice.visible
    ui.run(lambda: None)
    assert "test failure" in ui.error_notice.object
    assert "test failure" in ui.event_log.value
    assert ui.message not in ui.panel.objects
    assert ui.task_status not in ui.panel.objects
    ui._clear_error()
    assert not ui.error_notice.visible
    assert "test failure" in ui.event_log.value
    doc = Document()
    root = ui.task_dock.get_root(doc)
    doc.add_root(root)
    assert doc.to_json()
    ui.task_dock._cleanup(root)


def test_plot_ratios_and_analysis_errors(tmp_path):
    ui = workspace(tmp_path)
    assert ui.components.tic_pane.aspect_ratio == 2
    assert ui.analysis.embedding_plot.aspect_ratio == 1
    assert ui.analysis.volcano.aspect_ratio == 4 / 3
    assert ui.analysis.volcano.height is None
    ui.analysis.status.object = "❌ 测试报错"
    assert "测试报错" in ui.error_notice.object
    assert ui.error_notice.visible
