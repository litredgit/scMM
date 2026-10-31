"""Local, persisted ion-only jobs; no scientific workspace locks in the worker."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from scMM.ion.identity import json_identity

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class IonJobs:
    def __init__(self, directory, *, timeout=300):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.timeout = timeout
        self.lock = threading.RLock()
        self.jobs = {}
        self.processes = {}
        self.closed = False
        for path in self.directory.glob("*/job.json"):
            record = json.loads(path.read_text())
            if record["status"] not in TERMINAL:
                record.update(status="interrupted", collectible=False, reason="service restarted")
                self._write(record)
            self.jobs[record["id"]] = record

    def _write(self, record):
        folder = self.directory / record["id"]
        folder.mkdir(exist_ok=True, mode=0o700)
        temporary = folder / "job.tmp"
        temporary.write_text(json.dumps(record, allow_nan=False))
        temporary.replace(folder / "job.json")

    def submit(self, data, *, owner, workspace, binding, options, request_id):
        digest = json_identity({"binding": binding, "options": options})
        with self.lock:
            if self.closed:
                raise ValueError("ion jobs are shut down for maintenance")
            for record in self.jobs.values():
                if (
                    record["owner"] == owner
                    and record["workspace"] == workspace
                    and record["request_id"] == request_id
                ):
                    if record["request_digest"] != digest:
                        raise ValueError("request ID reused with different input")
                    return deepcopy(record)
            if any(r["status"] not in TERMINAL for r in self.jobs.values()):
                raise ValueError("another ion job is active; retry when it finishes")
            job_id = uuid4().hex
            record = {
                "id": job_id,
                "owner": owner,
                "workspace": workspace,
                "binding": binding,
                "options": options,
                "request_id": request_id,
                "request_digest": digest,
                "status": "queued",
                "collectible": False,
                "reason": None,
                "submitted_at": time.time(),
                "collected": False,
            }
            self._write(record)
            folder = self.directory / job_id
            try:
                data.write_h5ad(folder / "input.h5ad")
                (folder / "options.json").write_text(json.dumps(options, allow_nan=False))
                with (folder / "worker.log").open("wb") as log:
                    env = {
                        **os.environ,
                        "OMP_NUM_THREADS": "1",
                        "OPENBLAS_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1",
                    }
                    proc = subprocess.Popen(
                        [sys.executable, "-m", "scMM.application.ion_worker", str(folder)],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        env=env,
                    )
                self.processes[job_id] = proc
                record.update(status="running", pid=proc.pid, started_at=time.time())
                self.jobs[job_id] = record
                self._write(record)
                threading.Thread(target=self._watch, args=(job_id,), daemon=True).start()
            except Exception:
                record.update(status="failed", reason="worker submission failed")
                self.jobs[job_id] = record
                self._write(record)
                raise
            return deepcopy(record)

    def _watch(self, job_id):
        proc = self.processes[job_id]
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self._stop(proc)
            with self.lock:
                record = self.jobs[job_id]
                if record["status"] == "running":
                    record.update(
                        status="failed", reason="task wall time budget exceeded", collectible=False
                    )
                    self._write(record)
            return
        with self.lock:
            record = self.jobs[job_id]
            if record["status"] != "running":
                return
            path = self.directory / job_id / "result.json"
            success = proc.returncode == 0 and path.exists() and path.stat().st_size <= 50_000_000
            if success:
                try:
                    result = json.loads(path.read_text())
                    record["result_digest"] = json_identity(result)
                except (ValueError, OSError):
                    success = False
            record.update(
                status="succeeded" if success else "failed",
                collectible=success,
                reason=None if success else "worker failed; inspect task log",
                finished_at=time.time(),
            )
            self._write(record)

    @staticmethod
    def _stop(proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                proc.wait(timeout=3)
                return
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)
        if proc.poll() is None:
            raise RuntimeError("ion worker did not exit")

    def get(self, job_id, *, owner, workspace):
        with self.lock:
            record = self.jobs.get(job_id)
            if record is None or record["owner"] != owner or record["workspace"] != workspace:
                raise ValueError("ion task not found in this workspace")
            return deepcopy(record)

    def result(self, job_id, *, owner, workspace):
        record = self.get(job_id, owner=owner, workspace=workspace)
        if record["status"] != "succeeded" or not record["collectible"] or record["collected"]:
            raise ValueError("task result is unavailable or already collected")
        path = self.directory / job_id / "result.json"
        if path.stat().st_size > 50_000_000:
            raise ValueError("worker output budget exceeded")
        result = json.loads(path.read_text())
        if json_identity(result) != record["result_digest"]:
            raise ValueError("task result checksum mismatch")
        return result

    def mark(self, job_id, *, collected=False, reason=None):
        with self.lock:
            self.jobs[job_id].update(collected=collected, collectible=False, reason=reason)
            self._write(self.jobs[job_id])

    def cancel(self, job_id, *, owner, workspace):
        with self.lock:
            record = self.get(job_id, owner=owner, workspace=workspace)
            if record["status"] in TERMINAL:
                return record
            proc = self.processes[job_id]
            self._stop(proc)
            record.update(
                status="cancelled",
                collectible=False,
                reason="cancelled by user",
                finished_at=time.time(),
            )
            self.jobs[job_id] = record
            self._write(record)
            return deepcopy(record)

    def shutdown(self):
        with self.lock:
            self.closed = True
            for job_id, proc in self.processes.items():
                self._stop(proc)
                if self.jobs[job_id]["status"] not in TERMINAL:
                    self.jobs[job_id].update(
                        status="interrupted", collectible=False, reason="service maintenance"
                    )
                    self._write(self.jobs[job_id])
