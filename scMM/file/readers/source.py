"""Reopenable RAW source for multi-pass algorithms, without retaining scans."""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .thermo_raw import ThermoRawError, ThermoRawReader


class ThermoRawSource:
    def __init__(self, path, *, timezone=None):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Thermo RAW must be a file: {self.path}")
        self.timezone = (
            timezone
            if timezone is not None
            else os.environ.get("SCMM_RAW_TIMEZONE", "Asia/Shanghai")
        )
        zone = ZoneInfo(self.timezone)  # Invalid configuration must not silently fall back.
        self._signature = self._stat()
        with ThermoRawReader(self.path) as reader:
            self.scan_count = reader.scan_count
            self.creation_time = reader.creation_time
            self.instrument = reader.instrument
        timestamp = datetime.fromisoformat(self.creation_time)
        if timestamp.tzinfo is None:
            # Do not silently choose a fold or normalize a nonexistent local time.
            first, second = (
                timestamp.replace(tzinfo=zone, fold=0),
                timestamp.replace(tzinfo=zone, fold=1),
            )
            if first.utcoffset() != second.utcoffset():
                raise ThermoRawError(
                    "Ambiguous/nonexistent RAW acquisition time in configured timezone"
                )
            timestamp = first
        self.metadata = {
            "name": self.path.stem,
            "timestamp": timestamp.timestamp(),
            "instrument": self.instrument,
            "source_file": self.path.name,
            "path": str(self.path),
            "converted_from_raw": False,
            "reader_backend": "thermo_rawfilereader",
            "reader_protocol": "SCMMRAW1",
            "acquisition_time_original": self.creation_time,
            "acquisition_timezone": self.timezone,
            "include_reference_and_exception_data": True,
        }

    def _stat(self):
        stat = self.path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def __iter__(self):
        if self._stat() != self._signature:
            raise ThermoRawError("RAW changed between processing passes")
        with ThermoRawReader(self.path) as reader:
            if (reader.scan_count, reader.creation_time, reader.instrument) != (
                self.scan_count,
                self.creation_time,
                self.instrument,
            ):
                raise ThermoRawError("RAW header changed between processing passes")
            yield from reader
        if self._stat() != self._signature:
            raise ThermoRawError("RAW changed during processing")

    def getNrSpectra(self):
        return self.scan_count
