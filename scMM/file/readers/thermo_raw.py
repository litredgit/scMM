"""Strict-profile Thermo reader. Linux binary pipe; no converted intermediate files."""

from __future__ import annotations

import math
import os
import selectors
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from .base import Spectrum


class ThermoRawError(RuntimeError):
    """A missing reader, invalid protocol, non-profile input or vendor failure."""


def reader_command():
    """Resolve an executable, or a DLL plus an explicitly located .NET runtime."""
    configured = os.environ.get("SCMM_THERMO_READER")
    default = Path.home() / ".local/share/scmm/thermo-reader/scmm-thermo-reader.dll"
    program = configured or shutil.which("scmm-thermo-reader") or str(default)
    path = Path(program).expanduser()
    if not path.is_file():
        raise ThermoRawError(
            "Thermo reader not installed; set SCMM_THERMO_READER (see docs/16-thermo-raw.md)"
        )
    if path.suffix.lower() == ".dll":
        runtime = os.environ.get("SCMM_DOTNET") or shutil.which("dotnet")
        runtime = runtime or str(Path.home() / ".local/share/scmm/dotnet/dotnet")
        if not Path(runtime).is_file():
            raise ThermoRawError(".NET 8 runtime not found; set SCMM_DOTNET")
        return [runtime, str(path)]
    return [str(path)]


class ThermoRawReader:
    """Single-use context-managed stream; arrays own immutable byte buffers.

    timeout limits a stalled protocol read, not the whole RAW processing job.
    stderr is continuously drained with only its last 64 KiB retained.
    """

    def __init__(self, path, *, command=None, timeout=120.0, max_points=20_000_000):
        self.path = Path(path).expanduser().resolve()
        self.command = command
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0 or max_points <= 0:
            raise ValueError("timeout and max_points must be positive")
        self.max_points = max_points
        self.process = None
        self._selector = None
        self._thread = None
        self._stderr = bytearray()
        self._used = False
        self._finished = False
        self._iterated = False

    def __enter__(self):
        if self._used:
            raise ThermoRawError("Reader is single-use; create a new context to reread")
        self._used = True
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        try:
            self.process = subprocess.Popen(
                [*(self.command or reader_command()), str(self.path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._thread = threading.Thread(target=self._drain_stderr, daemon=True)
            self._thread.start()
            self._selector = selectors.DefaultSelector()
            self._selector.register(self.process.stdout, selectors.EVENT_READ)
            if self._read(8) != b"SCMMRAW1":
                raise ThermoRawError("Invalid SCMMRAW1 magic/version")
            self.scan_count = self._unpack("<i")[0]
            if self.scan_count <= 0:
                raise ThermoRawError("Invalid or empty scan count")
            self.creation_time = self._text()
            self.instrument = self._text()
            return self
        except BaseException as error:
            self.close()
            if isinstance(error, (ThermoRawError, OSError)):
                raise ThermoRawError(f"{error}; {self.diagnostics}") from error
            raise

    @property
    def diagnostics(self):
        return bytes(self._stderr).decode("utf-8", errors="replace").strip()

    def _drain_stderr(self):
        while chunk := self.process.stderr.read(4096):
            self._stderr.extend(chunk)
            if len(self._stderr) > 65536:
                del self._stderr[:-65536]

    def _read(self, size):
        chunks = bytearray()
        deadline = time.monotonic() + self.timeout
        while len(chunks) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._selector.select(remaining):
                raise ThermoRawError("Thermo reader stalled (read timeout)")
            chunk = os.read(self.process.stdout.fileno(), min(size - len(chunks), 1024 * 1024))
            if not chunk:
                raise ThermoRawError("Truncated Thermo stream (unexpected EOF)")
            chunks.extend(chunk)
        return bytes(chunks)

    def _unpack(self, layout):
        return struct.unpack(layout, self._read(struct.calcsize(layout)))

    def _text(self):
        size = self._unpack("<i")[0]
        if not 0 <= size <= 65536:
            raise ThermoRawError("Invalid text length")
        try:
            return self._read(size).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ThermoRawError("Invalid UTF-8 header") from error

    def __iter__(self):
        if self.process is None or self._finished or self._iterated:
            raise ThermoRawError("Use reader inside a fresh with context")
        self._iterated = True
        scans = points = previous = 0
        try:
            while True:
                tag = self._read(1)
                if tag == b"\0":
                    total_scans, total_points = self._unpack("<iq")
                    if (scans, points) != (total_scans, total_points) or scans != self.scan_count:
                        raise ThermoRawError("Thermo stream count mismatch")
                    if not self._selector.select(self.timeout):
                        raise ThermoRawError("Reader did not close stdout")
                    if os.read(self.process.stdout.fileno(), 1):
                        raise ThermoRawError("Unexpected bytes after stream terminator")
                    try:
                        code = self.process.wait(timeout=self.timeout)
                    except subprocess.TimeoutExpired as error:
                        raise ThermoRawError("Reader did not exit") from error
                    self._thread.join(timeout=2)
                    if code:
                        raise ThermoRawError(f"Thermo reader exited with status {code}")
                    self._finished = True
                    return
                if tag != b"\1":
                    raise ThermoRawError("Unknown Thermo stream record")
                number, level, profile, rt, count = self._unpack("<iiBdi")
                if not (number > previous and level >= 1 and profile == 1):
                    raise ThermoRawError(f"Invalid or non-profile scan {number}")
                if not math.isfinite(rt) or rt < 0 or not 0 <= count <= self.max_points:
                    raise ThermoRawError(f"Invalid RT or point count at scan {number}")
                if scans >= self.scan_count:
                    raise ThermoRawError("Too many scans")
                mz = np.frombuffer(self._read(count * 8), dtype="<f8")
                intensity = np.frombuffer(self._read(count * 8), dtype="<f8")
                if not np.isfinite(mz).all() or not np.isfinite(intensity).all():
                    raise ThermoRawError(f"Non-finite profile values at scan {number}")
                scans += 1
                points += count
                previous = number
                yield Spectrum(number, rt, mz, intensity, level)
        except ThermoRawError as error:
            self.close()
            raise ThermoRawError(f"{error}; {self.diagnostics}") from error

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self._thread is not None:
                self._thread.join(timeout=2)
            self.process.stdout.close()
            self.process.stderr.close()
        if self._selector is not None:
            self._selector.close()
        self._finished = True

    def __exit__(self, *exc):
        self.close()
