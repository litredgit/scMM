"""Start and stop isolated scientific worker processes with bounded native threads."""

import os
import signal
import subprocess
import sys
from contextlib import suppress


class JobRunner:
    @staticmethod
    def start(module, *args, stdout, stderr=subprocess.STDOUT, environment=None, **options):
        env = {
            **os.environ,
            **(environment or {}),
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        return subprocess.Popen(
            [sys.executable, "-m", module, *map(str, args)],
            stdout=stdout,
            stderr=stderr,
            start_new_session=os.name == "posix",
            env=env,
            **options,
        )

    @staticmethod
    def stop(process):
        """Request group shutdown and report whether the worker was reaped."""
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            if process.poll() is not None:
                return True
            process.terminate()
        try:
            process.wait(timeout=3)
            reaped = True
        except subprocess.TimeoutExpired:
            reaped = False
        if os.name == "posix":
            # The group can still have descendants after its leader has exited.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        elif not reaped:
            process.kill()
        if reaped:
            return True
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return False
        return True
