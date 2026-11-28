"""Local, persisted ion-only jobs; no scientific workspace locks in the worker."""

import json
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager, suppress
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psutil

from scMM.ion.identity import json_identity

from .job_runner import JobRunner

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
JOB_RETENTION_SECONDS = 7 * 86400


class IonJobs:
    def __init__(self, directory, *, timeout=300):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.timeout = timeout
        self.lock = threading.RLock()
        self.jobs = {}
        self.processes = {}
        self.stopping = {}
        self.readers = {}
        self.closed = False
        for path in self.directory.glob("*/job.json"):
            record = json.loads(path.read_text())
            if record["id"] != path.parent.name or path.parent.is_symlink():
                raise ValueError("Invalid ion job directory")
            if record["status"] not in TERMINAL:
                record.update(status="interrupted", collectible=False, reason="service restarted")
                self._write(record)
            self.jobs[record["id"]] = record
        self._prune()

    def _prune(self):
        cutoff = time.time() - JOB_RETENTION_SECONDS
        expired = [
            key
            for key, record in self.jobs.items()
            if record["status"] in TERMINAL
            and key not in self.processes
            and not self.readers.get(key)
            and record.get("finished_at", record.get("submitted_at", cutoff)) < cutoff
        ]
        for key in expired:
            folder = self.directory / key
            if folder.is_dir() and not folder.is_symlink():
                shutil.rmtree(folder)
                del self.jobs[key]

    def _write(self, record):
        folder = self.directory / record["id"]
        folder.mkdir(exist_ok=True, mode=0o700)
        temporary = folder / "job.tmp"
        temporary.write_text(json.dumps(record, allow_nan=False))
        temporary.replace(folder / "job.json")

    def submit(self, data, *, owner, workspace, binding, options, request_id):
        digest = json_identity({"binding": binding, "options": options})
        with self.lock:
            exited = [
                (job_id, proc)
                for job_id, proc in self.processes.items()
                if self.jobs[job_id]["status"] in TERMINAL and proc.poll() is not None
            ]
        for job_id, proc in exited:
            self._stop(job_id, proc)
        proc = None
        job_id = None
        try:
            with self.lock:
                if self.closed:
                    raise ValueError("ion jobs are shut down for maintenance")
                self._prune()
                for record in self.jobs.values():
                    if (
                        record["owner"] == owner
                        and record["workspace"] == workspace
                        and record["request_id"] == request_id
                    ):
                        if record["request_digest"] != digest:
                            raise ValueError("request ID reused with different input")
                        return deepcopy(record)
                if self.processes:
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
                self.jobs[job_id] = record
                folder = self.directory / job_id
                data.copy().write_h5ad(folder / "input.h5ad")
                (folder / "options.json").write_text(json.dumps(options, allow_nan=False))
                with (folder / "worker.log").open("wb") as log:
                    proc = JobRunner.start("scMM.application.ion_worker", folder, stdout=log)
                    self.processes[job_id] = proc
                record.update(status="running", pid=proc.pid, started_at=time.time())
                with suppress(psutil.NoSuchProcess):
                    record["process_created_at"] = psutil.Process(proc.pid).create_time()
                self._write(record)
                threading.Thread(target=self._watch, args=(job_id, proc), daemon=True).start()
                return deepcopy(record)
        except Exception:
            if proc is not None:
                self._fail_and_stop(job_id, proc, "worker submission failed")
            elif job_id is not None and job_id in self.jobs:
                with self.lock:
                    self._finish(job_id, "failed", "worker submission failed")
            raise

    def _finish(self, job_id, status, reason=None):
        record = self.jobs[job_id]
        if record["status"] not in TERMINAL:
            record.update(
                status=status,
                reason=reason,
                collectible=status == "succeeded",
                finished_at=time.time(),
            )
            self._write(record)
        return record

    def _stop(self, job_id, proc):
        with self.lock:
            if self.processes.get(job_id) is not proc:
                return True
            in_progress = self.stopping.get(job_id)
            if in_progress is None:
                completed = self.stopping[job_id] = threading.Event()
        if in_progress is not None:
            in_progress.wait(timeout=7)
            with self.lock:
                return self.processes.get(job_id) is not proc
        stopped = False
        try:
            stopped = JobRunner.stop(proc)
            return stopped
        finally:
            with self.lock:
                if stopped:
                    self.processes.pop(job_id, None)
                del self.stopping[job_id]
                completed.set()

    def _fail_and_stop(self, job_id, proc, reason):
        try:
            with self.lock:
                self._finish(job_id, "failed", reason)
        finally:
            self._stop(job_id, proc)

    def _watch(self, job_id, proc):
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self._fail_and_stop(job_id, proc, "task wall time budget exceeded")
            return
        except Exception:
            self._fail_and_stop(job_id, proc, "worker wait failed")
            return
        try:
            path = self.directory / job_id / "result.json"
            digest = None
            if proc.returncode == 0 and path.stat().st_size <= 50_000_000:
                digest = json_identity(json.loads(path.read_text()))
        except Exception:
            self._fail_and_stop(job_id, proc, "worker failed; inspect task log")
            return
        try:
            with self.lock:
                if self.jobs[job_id]["status"] != "running":
                    return
                if digest is not None:
                    self.jobs[job_id]["result_digest"] = digest
                    self._finish(job_id, "succeeded")
                else:
                    self._finish(job_id, "failed", "worker failed; inspect task log")
        finally:
            self._stop(job_id, proc)

    def get(self, job_id, *, owner, workspace):
        with self.lock:
            record = self.jobs.get(job_id)
            if record is None or record["owner"] != owner or record["workspace"] != workspace:
                raise ValueError("ion task not found in this workspace")
            return deepcopy(record)

    @contextmanager
    def pin(self, job_id):
        with self.lock:
            self.readers[job_id] = self.readers.get(job_id, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                remaining = self.readers[job_id] - 1
                if remaining:
                    self.readers[job_id] = remaining
                else:
                    del self.readers[job_id]

    def result(self, job_id, *, owner, workspace):
        with self.pin(job_id):
            record = self.get(job_id, owner=owner, workspace=workspace)
            if record["status"] != "succeeded" or not record["collectible"] or record["collected"]:
                raise ValueError("task result is unavailable or already collected")
            path = self.directory / job_id / "result.json"
            try:
                if path.stat().st_size > 50_000_000:
                    raise ValueError("worker output budget exceeded")
                result = json.loads(path.read_text())
            except OSError:
                raise ValueError("task result is unavailable") from None
            if json_identity(result) != record["result_digest"]:
                raise ValueError("task result checksum mismatch")
            return result

    def mark(self, job_id, *, collected=False, reason=None):
        with self.lock:
            self.jobs[job_id].update(collected=collected, collectible=False, reason=reason)
            self._write(self.jobs[job_id])

    def cancel(self, job_id, *, owner, workspace):
        proc = None
        try:
            with self.lock:
                record = self.get(job_id, owner=owner, workspace=workspace)
                if record["status"] in TERMINAL:
                    return record
                proc = self.processes[job_id]
                return deepcopy(self._finish(job_id, "cancelled", "cancelled by user"))
        finally:
            if proc is not None:
                self._stop(job_id, proc)

    def shutdown(self):
        with self.lock:
            self.closed = True
            active = list(self.processes.items())
        for job_id, proc in active:
            try:
                with self.lock:
                    self._finish(job_id, "interrupted", "service maintenance")
            finally:
                if not self._stop(job_id, proc):
                    raise ValueError("离子任务进程尚未退出。请稍后重试维护。")
