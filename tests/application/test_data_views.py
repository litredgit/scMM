"""Source immutability and atomic branch selection without user project writes."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.data_views import DataViewCatalog


def test_branch_isolation_and_atomic_failure():
    data = AnnData(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        obs=pd.DataFrame(index=["c1", "c2"]),
        var=pd.DataFrame({"mz": [100.0, 100.0]}, index=["f1", "f2"]),
    )
    catalog = DataViewCatalog()
    view, original = catalog.add_measurement(
        data,
        source={"kind": "synthetic"},
        origin_kind="extraction",
        value_semantics="linear_abundance",
    )
    _, selected = catalog.create_feature_view(
        root_id=view["root_id"], cell_ids=["c2"], feature_ids=["f2"], expected_revision=1
    )
    catalog.workspace.require_data().X[:] = 77
    catalog.activate(selected, expected_revision=2)
    assert catalog.workspace.require_data().X[0, 0] == 4
    assert catalog.measurement(view["root_id"]).X[0, 0] == 1
    before = catalog.identity()
    with pytest.raises(ValueError, match="stale"):
        catalog.activate(original, expected_revision=2)
    assert catalog.identity() == before
    with pytest.raises(ValueError, match="selection"):
        catalog.create_feature_view(
            root_id=view["root_id"], cell_ids=["missing"], feature_ids=["f1"], expected_revision=3
        )
    assert catalog.identity() == before
    catalog.activate(original, expected_revision=3)
    assert catalog.workspace.require_data().X[0, 0] == 77


def test_internal_project_opt_in_and_storage_guard(tmp_path):
    from scMM.application.data_views import initialize_catalog
    from scMM.application.projects import Project, ProjectStore
    from scMM.ion.semantics import value_states

    project = Project(tmp_path, {"name": "test", "samples": []})
    data = AnnData(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        obs=pd.DataFrame(index=["c1", "c2"]),
        var=pd.DataFrame({"mz": [100.0, 101.0]}, index=["f1", "f2"]),
    )
    initialize_catalog(
        project,
        data,
        source={"kind": "test"},
        origin_kind="extraction",
        linearity="linear_abundance",
    )
    catalog = DataViewCatalog.from_state(project.ion_state)
    assert value_states(catalog.workspace.data)["X"]["space"] == "linear_abundance"
    project.workspace.normalize("log")
    assert value_states(project.workspace.data)["X"]["space"] == "log_abundance"
    assert value_states(project.workspace._original)["X"]["space"] == "linear_abundance"
    with pytest.raises(ValueError, match="snapshot support"):
        ProjectStore.__new__(ProjectStore).save(project)
    corrupted = catalog.export_state()
    next(iter(corrupted["roots"].values()))["data"].X[0, 0] = 123
    with pytest.raises(ValueError, match="identity"):
        DataViewCatalog.from_state(corrupted)


def test_semantics_restore_reset_and_unknown_not_promoted():
    from scMM.application.workbench import AnalysisWorkspace
    from scMM.ion.semantics import unknown_state, value_states, write_value_states

    data = AnnData(np.array([[1.0, 2.0], [3.0, 5.0]]))
    states = {"X": {**unknown_state(), "space": "linear_abundance"}}
    write_value_states(data, states)
    workspace = AnalysisWorkspace()
    workspace.replace(data)
    original = workspace.data.uns["scmm_workbench"]["original_layer"]
    workspace.normalize("log")
    assert value_states(workspace.data)["X"]["space"] == "log_abundance"
    workspace.restore(original)
    assert value_states(workspace.data)["X"]["space"] == "linear_abundance"
    unknown = AnalysisWorkspace()
    unknown.replace(AnnData(np.array([[1.0, 2.0], [3.0, 5.0]])))
    unknown.normalize("total")
    assert value_states(unknown.data)["X"]["space"] == "unknown"
