"""User workflow regressions: reuse, metadata, navigation and display boundaries."""

import json

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.projects import ProjectStore, child_path
from tests.support.project import setup_project


def test_project_list_distinguishes_configuration_saved_and_missing_snapshot(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("states")
    assert store.list()[0]["data_state"] == "configuration"
    project.workspace.replace(AnnData(np.ones((3, 2))))
    store.save(project)
    summary = store.list()[0]
    assert (summary["data_state"], summary["cells"], summary["features"]) == ("saved", 3, 2)
    child_path(project.folder, project.manifest["artifacts"]["current"]).unlink()
    assert store.list()[0]["data_state"] == "unavailable"
    with pytest.raises(ValueError, match="项目数据恢复失败"):
        store.open(project.folder)


def test_metaboanalyst_matrix_csv_labels_order_and_exact_values():
    from io import StringIO

    from scMM.application.matrix_export import matrix_csv

    data = AnnData(
        np.array([[1.2345678901234567, -2.345678901234567], [0, 9.87654321098765]]),
        obs=pd.DataFrame({"group": ["A", "B"]}, index=["c2", "c1"]),
        var=pd.DataFrame(index=["f2", "f1"]),
    )
    frame = pd.read_csv(
        StringIO(matrix_csv(data, features=["f1", "f2"]).decode()), float_precision="round_trip"
    )
    assert list(frame) == ["Sample", "Label", "f1", "f2"]
    assert frame.Sample.tolist() == ["c2", "c1"] and frame.Label.tolist() == ["A", "B"]
    np.testing.assert_array_equal(frame[["f1", "f2"]].to_numpy(), data.X[:, ::-1])
    for invalid in (["A", ""], ["A", None]):
        data.obs["group"] = invalid
        with pytest.raises(ValueError, match="group"):
            matrix_csv(data)
    del data.obs["group"]
    with pytest.raises(ValueError, match="group"):
        matrix_csv(data)


def test_project_roundtrip_reset_and_conflict(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("实验 / A")
    data = AnnData(np.arange(1.0, 25.0).reshape(6, 4), obs=pd.DataFrame(index=list("abcdef")))
    project.workspace.replace(data)
    project.workspace.filter(min_total=30)
    store.save(project)
    assert not project.unsaved
    reopened = store.open(project.folder)
    assert reopened.workspace.data.n_obs < 6
    reopened.workspace.reset()
    assert reopened.workspace.data.shape == (6, 4)
    assert reopened.unsaved
    stale = store.open(project.folder)
    store.save(reopened)
    with pytest.raises(RuntimeError, match="another session"):
        store.save(stale)
    assert len(store.list()) == 1


def test_failed_snapshot_preserves_manifest(tmp_path, monkeypatch):
    store = ProjectStore(tmp_path)
    project = store.create("test")
    before = (project.folder / "project.json").read_bytes()
    project.workspace.replace(AnnData(np.ones((3, 2))))

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(project.workspace, "save_h5ad", fail)
    with pytest.raises(OSError, match="disk full"):
        store.save(project)
    assert (project.folder / "project.json").read_bytes() == before


@pytest.mark.parametrize("baseline", ["raw", "normalized", "transformed"])
def test_project_reset_preserves_separate_baseline_intensity_lineage(tmp_path, baseline):
    from scMM.application.workbench import AnalysisWorkspace
    from scMM.util.intensity import intensity_states, write_intensity_states

    data = AnnData(np.array([[0.0, 2.0], [4.0, 6.0]]))
    write_intensity_states(data, {"X": "raw"})
    prepared = AnalysisWorkspace()
    prepared.replace(data)
    if baseline == "normalized":
        prepared.normalize("total")
    elif baseline == "transformed":
        prepared.impute()
    store = ProjectStore(tmp_path)
    project = store.create("lineage")
    project.workspace.replace(prepared.data)
    baseline_matrix = project.workspace.data.X.copy()
    project.workspace.restore("scmm_input_0")
    assert intensity_states(project.workspace.data)["X"] == "raw"
    store.save(project)
    restored = store.open(project.folder)
    restored.workspace.reset()
    np.testing.assert_array_equal(restored.workspace.data.X, baseline_matrix)
    assert intensity_states(restored.workspace.data)["X"] == baseline


def test_manifest_cannot_escape_project(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("test")
    with pytest.raises(ValueError):
        child_path(project.folder, "../outside")
    (project.folder / "escape").symlink_to(tmp_path)
    with pytest.raises(PermissionError):
        child_path(project.folder, "escape/file.h5ad")
    manifest = project.manifest.copy()
    manifest["schema_version"] = 99
    (project.folder / "project.json").write_text(json.dumps(manifest))
    assert store.list() == []


def test_automatic_ranges_do_not_freeze_project_defaults(tmp_path):
    from scMM.application.projects import sample_parameters

    project, _ = setup_project(tmp_path)
    project.manifest["auto_ranges"] = True
    project.samples[0]["auto_mz_range"] = [140.0, 160.0]
    project.samples[1]["auto_mz_range"] = [130.0, 170.0]
    assert sample_parameters(project, project.samples[0])["mz_min"] == 130.0
    project.manifest["parameters"]["cell_snr"] = 8.0
    assert sample_parameters(project, project.samples[0])["cell_snr"] == 8.0
    project.manifest["feature_strategy"] = "independent"
    assert sample_parameters(project, project.samples[0])["mz_min"] == 140.0
    project.manifest["manual_parameters"] = True
    project.manifest["parameters"]["mz_min"] = 120.0
    assert sample_parameters(project, project.samples[0])["mz_min"] == 120.0


def test_view_only_snapshot_failure_keeps_previous_manifest(tmp_path, monkeypatch):
    from scMM.application import projects

    store = ProjectStore(tmp_path)
    project = store.create("raw views")
    project.views = {"legend_orders": {"raw.tic_pane": ["b", "a"]}}
    store.save(project)
    before = (project.folder / "project.json").read_bytes()
    project.views["legend_orders"]["raw.tic_pane"] = ["a", "b"]
    write = projects.write_json

    def fail_views(path, value):
        if path.name == "views.json":
            raise OSError("view snapshot failed")
        write(path, value)

    monkeypatch.setattr(projects, "write_json", fail_views)
    with pytest.raises(OSError, match="view snapshot"):
        store.save(project)
    assert (project.folder / "project.json").read_bytes() == before
    reopened = store.open(project.folder)
    assert reopened.workspace.data is None
    assert reopened.views["legend_orders"]["raw.tic_pane"] == ["b", "a"]
