import json

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.projects import ProjectStore, child_path


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
