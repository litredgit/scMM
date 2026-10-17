"""Protocol and lifetime tests: no Thermo runtime or private data required."""

import base64
import struct
import sys

import numpy as np
import pytest

from scMM.file.readers import ThermoRawError, ThermoRawReader


def text_record(value):
    value = value.encode("utf-8")
    return struct.pack("<i", len(value)) + value


def header(count=1):
    return (
        b"SCMMRAW1"
        + struct.pack("<i", count)
        + text_record("2026-09-22T16:04:29")
        + text_record("仪器")
    )


def scan(number=7, level=1, profile=1, rt=1.5, mz=(101.0, 100.0, 100.0), intensity=(0.0, 2.0, 3.0)):
    return (
        b"\1"
        + struct.pack("<iiBdi", number, level, profile, rt, len(mz))
        + np.asarray(mz, dtype="<f8").tobytes()
        + np.asarray(intensity, dtype="<f8").tobytes()
    )


def end(scans=1, points=3):
    return b"\0" + struct.pack("<iq", scans, points)


def make_reader(tmp_path, payload, *, before="", after="", **kwargs):
    source = tmp_path / "中文 sample.RAW"
    source.touch()
    script = (
        "import os,base64,time,sys;"
        + before
        + f"data=base64.b64decode({base64.b64encode(payload)!r});"
        # Exercise short reads, not one write of the entire stream.
        + "[os.write(1,data[i:i+7]) for i in range(0,len(data),7)];"
        + after
    )
    return ThermoRawReader(source, command=[sys.executable, "-c", script], **kwargs)


def test_preserves_arrays_units_and_buffer_lifetime(tmp_path):
    with make_reader(tmp_path, header() + scan() + end()) as reader:
        assert reader.instrument == "仪器"
        items = list(reader)
    item = items[0]
    assert item.scan_number == 7 and item.getRT() == 1.5 and item.getMSLevel() == 1
    np.testing.assert_array_equal(item.mz, [101.0, 100.0, 100.0])
    np.testing.assert_array_equal(item.intensity, [0.0, 2.0, 3.0])
    assert not item.mz.flags.writeable
    assert reader.process.poll() == 0


@pytest.mark.parametrize(
    "payload,match",
    [
        (b"INVALID!", "magic"),
        (header(0), "scan count"),
        (header() + scan()[:-1], "Truncated"),
        (header() + scan(), "Truncated"),
        (header() + scan(profile=0), "non-profile"),
        (header() + scan(level=0), "non-profile"),
        (header() + scan(rt=float("nan")), "Invalid RT"),
        (header() + scan(mz=(float("nan"),), intensity=(1.0,)), "Non-finite"),
        (header() + scan() + end(points=4), "count mismatch"),
        (header() + scan() + end() + b"x", "Unexpected bytes"),
        (header() + b"\2", "Unknown"),
        (header() + b"\1" + struct.pack("<iiBdi", 1, 1, 1, 0.0, -1), "point count"),
        (header(2) + scan() + scan() + end(2, 6), "scan 7"),
    ],
)
def test_invalid_stream(tmp_path, payload, match):
    reader = make_reader(tmp_path, payload)
    with pytest.raises(ThermoRawError, match=match), reader:
        list(reader)
    assert reader.process.poll() is not None


def test_empty_profile_scan_and_ms_level(tmp_path):
    with make_reader(
        tmp_path, header() + scan(level=2, mz=(), intensity=()) + end(points=0)
    ) as reader:
        (item,) = list(reader)
        assert item.ms_level == 2 and item.mz.size == 0


def test_nonzero_exit_after_complete_stream(tmp_path):
    reader = make_reader(tmp_path, header() + scan() + end(), after="sys.exit(9)")
    with pytest.raises(ThermoRawError, match="status 9"), reader:
        list(reader)


def test_large_stderr_is_drained_and_bounded(tmp_path):
    reader = make_reader(tmp_path, header(), before="os.write(2,b'x'*200000+b'BROKEN RAW');")
    with pytest.raises(ThermoRawError, match="BROKEN RAW"), reader:
        list(reader)
    assert len(reader._stderr) <= 65536


def test_early_exit_reaps_process(tmp_path):
    reader = make_reader(tmp_path, header() + scan(), after="time.sleep(30)")
    with reader:
        item = next(iter(reader))
        assert item.scan_number == 7
    assert reader.process.poll() is not None
    with pytest.raises(ThermoRawError, match="single-use"), reader:
        pass


def test_stall_times_out_and_reaps(tmp_path):
    reader = make_reader(tmp_path, b"", before="time.sleep(30);", timeout=0.2)
    with pytest.raises(ThermoRawError, match="timeout"), reader:
        pass
    assert reader.process.poll() is not None


def test_missing_file_and_missing_runtime(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError), ThermoRawReader(tmp_path / "absent.raw"):
        pass
    source = tmp_path / "a.raw"
    source.touch()
    monkeypatch.setenv("SCMM_THERMO_READER", str(tmp_path / "absent-reader"))
    with pytest.raises(ThermoRawError, match="not installed"), ThermoRawReader(source):
        pass
