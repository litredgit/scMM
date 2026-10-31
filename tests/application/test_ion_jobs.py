"""Real subprocess termination and persisted state, isolated from experiment workspaces."""

import json
import subprocess
import sys
import time

import numpy as np
import pytest
from anndata import AnnData

from scMM.application.ion_jobs import IonJobs


def wait_for(jobs, task):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = jobs.get(task["id"], owner="user", workspace="workspace")
        if record["status"] not in {"queued", "running"}:
            return record
        time.sleep(0.02)
    raise AssertionError("task did not terminate")


def delayed_worker(monkeypatch):
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        return original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

    monkeypatch.setattr("scMM.application.ion_jobs.subprocess.Popen", spawn)


def test_cancel_timeout_owner_idempotence_and_shutdown(tmp_path, monkeypatch):
    delayed_worker(monkeypatch)
    jobs = IonJobs(tmp_path, timeout=10)
    data = AnnData(np.ones((2, 2)))
    opts = dict(
        owner="user", workspace="workspace", binding={"revision": 1}, options={}, request_id="one"
    )
    task = jobs.submit(data, **opts)
    assert jobs.submit(data, **opts)["id"] == task["id"]
    with pytest.raises(ValueError, match="not found"):
        jobs.get(task["id"], owner="someone", workspace="workspace")
    with pytest.raises(ValueError, match="different input"):
        jobs.submit(data, **{**opts, "options": {"changed": True}})
    with pytest.raises(ValueError, match="active"):
        jobs.submit(data, **{**opts, "request_id": "two"})
    record = jobs.cancel(task["id"], owner="user", workspace="workspace")
    assert record["status"] == "cancelled" and not record["collectible"]
    assert jobs.processes[task["id"]].poll() is not None
    assert jobs.cancel(task["id"], owner="user", workspace="workspace")["status"] == "cancelled"
    task = jobs.submit(data, **{**opts, "request_id": "second"})
    jobs.shutdown()
    assert jobs.get(task["id"], owner="user", workspace="workspace")["status"] == "interrupted"
    assert jobs.processes[task["id"]].poll() is not None
    fast = IonJobs(tmp_path / "timeout", timeout=0.05)
    task = fast.submit(data, **opts)
    assert wait_for(fast, task)["status"] == "failed"
    assert fast.processes[task["id"]].poll() is not None
    fast.shutdown()


def test_restart_marks_unfinished_interrupted(tmp_path):
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "job.json").write_text(
        json.dumps({"id": "job", "status": "running", "owner": "user", "workspace": "workspace"})
    )
    jobs = IonJobs(tmp_path)
    assert jobs.get("job", owner="user", workspace="workspace")["status"] == "interrupted"
    assert not jobs.get("job", owner="user", workspace="workspace")["collectible"]
