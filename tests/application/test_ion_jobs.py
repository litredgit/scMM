"""Real subprocess termination and persisted state, isolated from experiment workspaces."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest
from anndata import AnnData

from scMM.application.ion_jobs import IonJobs
from scMM.application.job_runner import JobRunner


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
    proc = jobs.processes[task["id"]]
    record = jobs.cancel(task["id"], owner="user", workspace="workspace")
    assert record["status"] == "cancelled" and not record["collectible"]
    assert proc.poll() is not None
    assert jobs.cancel(task["id"], owner="user", workspace="workspace")["status"] == "cancelled"
    task = jobs.submit(data, **{**opts, "request_id": "second"})
    proc = jobs.processes[task["id"]]
    jobs.shutdown()
    assert jobs.get(task["id"], owner="user", workspace="workspace")["status"] == "interrupted"
    assert proc.poll() is not None
    fast = IonJobs(tmp_path / "timeout", timeout=0.05)
    task = fast.submit(data, **opts)
    proc = fast.processes[task["id"]]
    assert wait_for(fast, task)["status"] == "failed"
    proc.wait(timeout=3)
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


def test_result_pin_excludes_expired_job_from_cleanup(tmp_path):
    from scMM.ion.identity import json_identity

    jobs = IonJobs(tmp_path)
    payload = {"grouping": {}}
    entry = {
        "id": "expired",
        "owner": "u",
        "workspace": "w",
        "status": "succeeded",
        "collectible": True,
        "collected": False,
        "finished_at": 1,
        "result_digest": json_identity(payload),
    }
    jobs.jobs["expired"] = entry
    jobs._write(entry)
    (tmp_path / "expired/result.json").write_text(json.dumps(payload))
    with jobs.pin("expired"):
        jobs._prune()
        assert jobs.result("expired", owner="u", workspace="w") == payload
        jobs.mark("expired", collected=True)
    jobs._prune()
    assert not (tmp_path / "expired").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX worker process groups")
@pytest.mark.parametrize("reaped", [True, False])
def test_stop_signals_group_after_leader_exit_and_bounds_second_wait(monkeypatch, reaped):
    signals = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    def wait(timeout):
        if not reaped:
            raise subprocess.TimeoutExpired("worker", timeout)
        return 0

    process = SimpleNamespace(pid=123, poll=lambda: 0 if reaped else None, wait=wait)
    assert JobRunner.stop(process) is reaped
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


@pytest.mark.parametrize("action", ["cancel", "shutdown"])
def test_waiting_to_stop_does_not_hold_job_lock(tmp_path, monkeypatch, action):
    delayed_worker(monkeypatch)
    jobs = IonJobs(tmp_path)
    owner = {"owner": "user", "workspace": "workspace"}
    record = jobs.submit(
        AnnData(np.ones((2, 2))), **owner, binding={}, options={}, request_id="one"
    )
    entered, release = threading.Event(), threading.Event()
    stop = JobRunner.stop

    def slow_stop(process):
        entered.set()
        assert release.wait(5)
        return stop(process)

    monkeypatch.setattr(JobRunner, "stop", slow_stop)
    stop_task = (
        (lambda: jobs.cancel(record["id"], **owner)) if action == "cancel" else jobs.shutdown
    )
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(stop_task)
        try:
            assert entered.wait(5)
            state = pool.submit(jobs.get, record["id"], **owner).result(timeout=2)
            assert state["status"] == {"cancel": "cancelled", "shutdown": "interrupted"}[action]
        finally:
            release.set()
        future.result(timeout=5)
    assert not jobs.processes


def test_post_launch_failure_reaps_worker_and_releases_slot(tmp_path, monkeypatch):
    delayed_worker(monkeypatch)
    jobs = IonJobs(tmp_path)
    opts = {"owner": "user", "workspace": "workspace", "binding": {}, "options": {}}
    data = AnnData(np.ones((2, 2)))
    write = jobs._write
    seen = []

    def fail_running(record):
        if record["status"] == "running":
            seen.append(jobs.processes[record["id"]])
            raise OSError("running state write failed")
        write(record)

    with monkeypatch.context() as patch:
        patch.setattr(jobs, "_write", fail_running)
        with pytest.raises(OSError, match="running state"):
            jobs.submit(data, **opts, request_id="first")
    assert seen[0].poll() is not None and not jobs.processes
    assert next(iter(jobs.jobs.values()))["status"] == "failed"
    assert jobs.submit(data, **opts, request_id="next")["status"] == "running"
    jobs.shutdown()


def test_timeout_records_failure_and_recovers_slot_after_delayed_exit(tmp_path, monkeypatch):
    delayed_worker(monkeypatch)
    jobs = IonJobs(tmp_path, timeout=0.01)
    opts = {"owner": "user", "workspace": "workspace", "binding": {}, "options": {}}
    data = AnnData(np.ones((2, 2)))
    attempted = threading.Event()
    stop = JobRunner.stop

    def delayed_stop(process):
        attempted.set()
        return False

    with monkeypatch.context() as patch:
        patch.setattr(JobRunner, "stop", delayed_stop)
        task = jobs.submit(data, **opts, request_id="first")
        assert attempted.wait(5)
        assert wait_for(jobs, task)["reason"] == "task wall time budget exceeded"
        proc = jobs.processes[task["id"]]
        with pytest.raises(ValueError, match="active"):
            jobs.submit(data, **opts, request_id="early")
    assert stop(proc)
    jobs.timeout = 10
    next_job = jobs.submit(data, **opts, request_id="next")
    assert next_job["id"] != task["id"]
    jobs.shutdown()
