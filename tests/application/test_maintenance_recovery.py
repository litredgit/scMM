"""Restore unsaved state and all four fitted model types without retraining."""

import threading
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.analysis.supervised import SupervisedAnalyzer
from scMM.application.projects import Project
from scMM.application.recovery import RecoveryStore
from scMM.application.state_codec import StateCodec
from scMM.application.web_workspace import BrowserWorkspace


def data():
    rng = np.random.default_rng(42)
    return AnnData(
        rng.normal(size=(80, 6)),
        obs=pd.DataFrame(
            {"label": ["a"] * 40 + ["b"] * 40}, index=[f"cell-{i}" for i in range(80)]
        ),
    )


@pytest.mark.parametrize("method", ["logistic", "lda", "plsda", "random_forest"])
@pytest.mark.parametrize("smote", [False, True])
def test_fitted_pipeline_exact_roundtrip(tmp_path, method, smote):
    model = SupervisedAnalyzer(data(), "label")
    model.evaluate(
        method,
        cv=2,
        smote=smote,
        model_params={"n_estimators": 12, "n_jobs": 1} if method == "random_forest" else {},
    )
    codec = StateCodec(tmp_path)
    state = codec.encode(model)
    result = codec.decode(state)
    np.testing.assert_array_equal(model.probabilities_, result.model_.predict_proba(model.X_test_))
    np.testing.assert_array_equal(model.train_obs_names_, result.train_obs_names_)
    state["versions"]["numpy"] = "invalid"
    with pytest.raises(ValueError, match="version"):
        codec.decode(state)


def test_grouped_multiclass_pls_calibration_recovers_exactly(tmp_path):
    target = data()
    target.obs["label"] = np.tile(["a", "b", "c", "a"], 20)
    target.obs["source"] = np.repeat(np.arange(20).astype(str), 4)
    model = SupervisedAnalyzer(target, "label", group_key="source")
    report = model.evaluate("plsda", cv=2)
    assert report["probability_diagnostics"]["probability_status"] == "grouped_oof_sigmoid"
    assert np.isfinite(report["probability_diagnostics"]["log_loss"])
    np.testing.assert_allclose(model.probabilities_.sum(axis=1), 1)
    np.testing.assert_array_equal(
        model.prediction_, model.classes_[model.probabilities_.argmax(axis=1)]
    )
    codec = StateCodec(tmp_path)
    restored = codec.decode(codec.encode(model))
    np.testing.assert_array_equal(restored.model_.predict(model.X_test_), model.prediction_)
    np.testing.assert_array_equal(
        restored.model_.predict_proba(model.X_test_), model.probabilities_
    )
    pd.testing.assert_frame_equal(restored.latent_scores(), model.latent_scores())


def test_unsaved_full_state_isolated_and_tamper_rejected(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir()
    recovery = RecoveryStore(SimpleNamespace(path=folder / "dev.json"))
    project = Project(tmp_path / "project", {"samples": [], "name": "unsaved"})
    project.workspace.replace(data())
    model = project.workspace.train("label", cv=2)
    project.dirty = True
    first = BrowserWorkspace(owner_id="alice", project=project)
    first.client_state = {"draft": {"seed": 111}, "page": "/analysis"}
    other = BrowserWorkspace(owner_id="bob")

    def manager(workspaces):
        return SimpleNamespace(
            _lock=threading.RLock(), _workspaces=workspaces, publish_ai=lambda w: None
        )

    original = manager({first.id: first, other.id: other})
    recovery.snapshot(original)
    new = manager({})
    assert recovery.restore(new) == 2
    assert new._workspaces[first.id].owner_id == "alice"
    assert new._workspaces[other.id].project is None
    restored = new._workspaces[first.id]
    assert restored.project.unsaved and restored.client_state == first.client_state
    assert restored.project.workspace._result_identities == project.workspace._result_identities
    assert restored.project.workspace._result_identities["supervised"]
    np.testing.assert_array_equal(
        restored.project.workspace.result("supervised").probabilities_, model.probabilities_
    )
    np.testing.assert_array_equal(
        restored.project.workspace._original.X, first.project.workspace._original.X
    )
    recovery.snapshot(original)
    pointer = __import__("json").loads((recovery.root / "current.json").read_text())
    artifact = next((recovery.root / pointer["id"]).glob("*.h5ad"))
    artifact.write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        recovery.restore(manager({}))


def test_failed_restart_restores_configuration_and_checkpoint(tmp_path, monkeypatch):
    import json

    from scMM.application import maintenance_runner as runner

    config = tmp_path / "dev.json"
    original = {"environment": "dev", "port": 5007, "cache_root": "old"}
    config.write_text(json.dumps(original))
    config.chmod(0o600)
    root = tmp_path / "dev.recovery"
    root.mkdir()
    pointer = root / "current.json"
    pointer.write_text('{"id":"verified-checkpoint"}')
    pending = config.with_suffix(".pending.json")
    pending.write_text('{"cache_root":"new"}')

    class Validated:
        def __init__(self, values, path):
            self.values, self.path = values, path

        def validate(self):
            return self

    monkeypatch.setattr(runner, "load_server_config", lambda *a, **k: Validated(original, config))
    monkeypatch.setattr(runner, "ServerConfig", Validated)
    commands = []
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **kwargs: commands.append(args))
    probes = []

    def health(port):
        probes.append(port)
        if len(probes) == 1:
            assert json.loads(config.read_text())["cache_root"] == "new"
            pointer.unlink()
            raise RuntimeError("synthetic failed startup")

    monkeypatch.setattr(runner, "healthy", health)
    with pytest.raises(RuntimeError, match="synthetic failed startup"):
        runner.run(config, "restart")
    assert json.loads(config.read_text()) == original
    assert json.loads(pointer.read_text())["id"] == "verified-checkpoint"
    assert json.loads((root / "last-operation.json").read_text())["status"] == "rolled_back"
    assert commands == [["systemctl", "--user", "restart", "scmm-dev.service"]] * 2


def test_deleted_raw_sample_does_not_discard_recovered_matrix(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir()
    recovery = RecoveryStore(SimpleNamespace(path=folder / "dev.json"))
    project = Project(tmp_path / "project", {"samples": [], "name": "unsaved"})
    original = data()
    project.workspace.replace(original)
    workspace = BrowserWorkspace(owner_id="alice", project=project)
    workspace.raw = {
        "sample_id": "deleted",
        "preview": SimpleNamespace(open_identity={}),
        "frames": [],
    }
    manager = SimpleNamespace(
        _lock=threading.RLock(), _workspaces={workspace.id: workspace}, publish_ai=lambda _: None
    )
    recovery.snapshot(manager)
    manager._workspaces = {}
    assert recovery.restore(manager) == 1
    restored = manager._workspaces[workspace.id]
    assert restored.client_state["raw_unavailable"]
    assert not restored.raw
    np.testing.assert_array_equal(restored.project.workspace.data.X, original.X)


def test_catalogue_inactive_model_formal_report_and_maintenance_model(tmp_path):
    from scMM.application.data_views import (
        DataViewCatalog,
        activate_view,
        freeze_active_branch,
        initialize_catalog,
    )
    from scMM.application.projects import ProjectStore

    projects = tmp_path / "projects"
    projects.mkdir()
    store = ProjectStore(projects)
    project = store.create("multi")
    measured = data()
    measured.X = np.abs(measured.X)
    measured.var["mz"] = np.arange(100.0, 106.0)
    view, original_branch = initialize_catalog(
        project,
        measured,
        source={"kind": "synthetic"},
        origin_kind="extraction",
        linearity="linear_abundance",
    )
    model = project.workspace.train("label", cv=2)
    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    selected_view, branch = catalog.create_feature_view(
        root_id=view["root_id"],
        cell_ids=list(measured.obs_names),
        feature_ids=list(measured.var_names[:3]),
        expected_revision=catalog.revision,
    )
    project.ion_state = catalog.export_state()
    activate_view(
        project, selected_view["id"], branch_id=branch, expected_catalog_revision=catalog.revision
    )
    store.save(project)
    opened = store.open(project.folder)
    inactive = opened.ion_state["branches"][original_branch]
    assert not inactive["workspace"]["results"]
    assert "supervised" in inactive["presentation"]["saved_reports"]
    assert not list(project.folder.rglob("*.skops"))
    private = tmp_path / "private"
    private.mkdir()
    recovery = RecoveryStore(SimpleNamespace(path=private / "dev.json"))
    workspace = BrowserWorkspace(owner_id="owner", project=project)
    manager = SimpleNamespace(
        _lock=threading.RLock(), _workspaces={workspace.id: workspace}, publish_ai=lambda w: None
    )
    recovery.snapshot(manager)
    restored = SimpleNamespace(_lock=threading.RLock(), _workspaces={}, publish_ai=lambda w: None)
    assert recovery.restore(restored) == 1
    restored_project = restored._workspaces[workspace.id].project
    assert restored_project.workspace.data.n_vars == 3
    fitted = restored_project.ion_state["branches"][original_branch]["workspace"]["results"][
        "supervised"
    ][1]
    np.testing.assert_array_equal(fitted.probabilities_, model.probabilities_)


def test_update_runner_delegates_preparation_and_resources_to_the_environment(
    tmp_path, monkeypatch
):
    from scMM.application import deployment_client, maintenance_runner

    config_path = tmp_path / "dev.json"
    configuration = SimpleNamespace(path=config_path, values={"port": 5007, "environment": "dev"})
    configuration.validate = lambda: configuration
    monkeypatch.setattr(maintenance_runner, "load_server_config", lambda *_a, **_k: configuration)
    monkeypatch.setattr(
        deployment_client, "prepare_service", lambda *_: pytest.fail("duplicate prepare")
    )
    commands = []
    monkeypatch.setattr(
        maintenance_runner.subprocess, "run", lambda args, **_: commands.append(args)
    )
    maintenance_runner.run(config_path, "update", "approved", deployment_first=True)
    assert commands[0][2:] == [
        "update",
        "dev",
        "--approved-version",
        "approved",
        "--maintenance-config",
        str(config_path),
        "--deployment-first",
    ]
