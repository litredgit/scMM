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
