"""Explicit private-data validation; JSON is a report, never a spectrum interchange.

Run with PYTHONPATH=. and the scMM environment (plus psutil for RSS sampling).
No input files are modified. An existing report is never overwritten.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import psutil

from scMM.file.io import load_single_file
from scMM.file.readers import ThermoRawReader


class MemorySampler:
    """Sample simultaneous RSS; sum RSS includes shared pages, not unique PSS."""

    def __init__(self):
        self.peak = {"python_rss_bytes": 0, "children_rss_bytes": 0, "tree_rss_bytes": 0}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        parent = psutil.Process()
        while not self.stop.is_set():
            own = parent.memory_info().rss
            children = 0
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess):
                    children += child.memory_info().rss
            for key, value in zip(self.peak, (own, children, own + children), strict=True):
                self.peak[key] = max(self.peak[key], value)
            self.stop.wait(0.01)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()


def benchmark(path):
    scans = points = 0
    with MemorySampler() as memory:
        start = time.perf_counter()
        with ThermoRawReader(path) as reader:
            for spectrum in reader:
                scans += 1
                points += len(spectrum.mz)
            metadata = {
                "instrument": reader.instrument,
                "creation_time_unspecified": reader.creation_time,
            }
        elapsed = time.perf_counter() - start
    return {
        "file_bytes": path.stat().st_size,
        "scans": scans,
        "profile_points": points,
        "elapsed_seconds_including_startup": elapsed,
        "scans_per_second": scans / elapsed,
        "points_per_second": points / elapsed,
        **memory.peak,
        **metadata,
        "memory_sampling_seconds": 0.01,
        "cache_condition": "uncontrolled OS/filesystem cache; no cache eviction",
    }


def encoding_counts(path):
    counts = {"mz_float32": 0, "mz_float64": 0, "intensity_float32": 0, "intensity_float64": 0}
    in_spectrum = False
    for event, element in ET.iterparse(path, events=("start", "end")):
        tag = element.tag.rsplit("}", 1)[-1]
        if event == "start":
            if tag == "spectrum":
                in_spectrum = True
            continue
        if tag == "binaryDataArray" and in_spectrum:
            accessions = {p.get("accession") for p in element if p.tag.endswith("cvParam")}
            kind = (
                "mz"
                if "MS:1000514" in accessions
                else "intensity"
                if "MS:1000515" in accessions
                else None
            )
            bits = 32 if "MS:1000521" in accessions else 64 if "MS:1000523" in accessions else None
            if kind and bits:
                counts[f"{kind}_float{bits}"] += 1
            element.clear()
        elif tag == "spectrum":
            in_spectrum = False
            element.clear()
    return counts


def compare(raw_path, mzml_path):
    experiment, _ = load_single_file(mzml_path)
    mismatches = dict.fromkeys(
        (
            "scan_number",
            "ms_level",
            "profile",
            "point_count",
            "rt_exact",
            "rt_over_1ns",
            "mz_exact",
            "intensity_exact",
            "mz_float32",
            "intensity_float32",
        ),
        0,
    )
    max_error = dict.fromkeys(("rt_seconds", "mz", "intensity"), 0.0)
    compared = total_points = different_intensity_points = 0
    examples = []
    with ThermoRawReader(raw_path) as reader:
        raw_count = reader.scan_count
        raw_time = reader.creation_time
        for index, spectrum in enumerate(reader):
            if index >= experiment.getNrSpectra():
                raise ValueError("RAW contains more scans than mzML")
            other = experiment[index]
            mz, intensity = other.get_peaks()
            native = re.search(r"(?:^|\s)scan=(\d+)(?:$|\s)", other.getNativeID())
            mismatches["scan_number"] += int(
                native is None or int(native[1]) != spectrum.scan_number
            )
            mismatches["ms_level"] += int(spectrum.ms_level != other.getMSLevel())
            mismatches["profile"] += int(int(other.getType()) != 2)  # OpenMS PROFILE=2
            error = abs(spectrum.retention_time - other.getRT())
            mismatches["rt_exact"] += int(error != 0)
            mismatches["rt_over_1ns"] += int(error > 1e-9)
            max_error["rt_seconds"] = max(max_error["rt_seconds"], error)
            compared += 1
            total_points += len(spectrum.mz)
            if len(mz) != len(spectrum.mz):
                mismatches["point_count"] += 1
                continue
            for key, a, b in (
                ("mz", spectrum.mz, mz),
                ("intensity", spectrum.intensity, intensity),
            ):
                mismatches[key + "_exact"] += int(not np.array_equal(a, b))
                mismatches[key + "_float32"] += int(not np.array_equal(a.astype(np.float32), b))
                if len(a):
                    max_error[key] = max(max_error[key], float(np.max(np.abs(a - b))))
            differences = np.flatnonzero(spectrum.intensity != intensity)
            different_intensity_points += len(differences)
            if len(examples) < 5:
                for k in differences[: 5 - len(examples)]:
                    examples.append(
                        {
                            "scan": spectrum.scan_number,
                            "point_index": int(k),
                            "raw_intensity": float(spectrum.intensity[k]),
                            "mzml_intensity": float(intensity[k]),
                        }
                    )
    return {
        "raw_scans": raw_count,
        "mzml_scans": experiment.getNrSpectra(),
        "compared_scans": compared,
        "raw_profile_points": total_points,
        "mismatch_scan_counts": mismatches,
        "max_absolute_error": max_error,
        "different_intensity_points": different_intensity_points,
        "examples": examples,
        "raw_creation_time_unspecified": raw_time,
        "mzml_creation_time_openms": str(experiment.getDateTime().get()),
        "mzml_array_encoding_counts": encoding_counts(mzml_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("mzml", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("report already exists; choose a new path")
    # Before loading the mzML baseline, so its full in-memory experiment does
    # not contaminate the direct-stream memory measurement.
    report = {
        "raw_path": str(args.raw),
        "mzml_path": str(args.mzml),
        "direct_stream": benchmark(args.raw),
    }
    report["comparison"] = compare(args.raw, args.mzml)
    with args.report.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, ensure_ascii=False)
        out.write("\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
