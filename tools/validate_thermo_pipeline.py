"""Isolated end-to-end RAW/XML regression and performance report.

Diagnostic float32 mode is ONLY for attributing mzML quantization differences;
production RAW remains float64. Temporary NPZs contain validation results, not
raw-spectrum interchange. Each mode runs in a fresh Python process for RSS.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import numpy as np

from scMM.file import _dataset_loading
from scMM.file.data import CyESIData
from scMM.file.readers import Spectrum
from scMM.file.readers.base import spectrum_iterator
from tools.validate_thermo_raw import MemorySampler


def worker(args):
    if args.mode == "xml-prior":
        # Trusted repository baseline, not code from the input data.
        code = subprocess.check_output(
            ["git", "show", "9d07a2e:scMM/file/_alignment.py"], text=True
        )
        module = types.ModuleType("scMM.file._prior_alignment")
        module.__package__ = "scMM.file"
        exec(compile(code, "prior_alignment", "exec"), module.__dict__)
        _dataset_loading.align_frame = module.align_frame
    if args.mode == "raw-float32-diagnostic":
        original = _dataset_loading.load_single_file

        class QuantizedSource:
            def __init__(self, source):
                self.source = source

            def __iter__(self):
                with spectrum_iterator(self.source) as spectra:
                    for s in spectra:
                        yield Spectrum(
                            s.scan_number,
                            s.retention_time,
                            s.mz.astype(np.float32).astype(np.float64),
                            s.intensity.astype(np.float32).astype(np.float64),
                            s.ms_level,
                        )

        def load(*a, **kw):
            source, meta = original(*a, **kw)
            return QuantizedSource(source), meta

        _dataset_loading.load_single_file = load

    arrays = {}

    def capture(event, values):
        arrays["aligned"] = values["signal"].to_numpy(copy=True)
        arrays["targets"] = values["signal"].columns.to_numpy(dtype=float)
        arrays["frame_rt"] = values["frame_obs"].rt.to_numpy(copy=True)

    path = args.raw if args.mode.startswith("raw") else args.mzml
    with MemorySampler() as memory:
        start = time.perf_counter()
        data = CyESIData.load_from_file(
            path,
            ref_mz=args.ref_mz,
            raw_timezone="Asia/Shanghai",
            debug_hook=capture,
            debug_full_baseline=False,
        )
        elapsed = time.perf_counter() - start
    arrays.update(
        cells=data.data.to_numpy(),
        cell_targets=data.data.columns.to_numpy(dtype=float),
        cell_frames=data.peak_meta.frame_id.to_numpy(),
        cell_rt=data.peak_meta.rt.to_numpy(),
    )
    np.savez(args.artifact.with_suffix(".npz"), **arrays)
    metrics = {
        "mode": args.mode,
        "input": str(path),
        "elapsed_seconds": elapsed,
        "aligned_shape": list(arrays["aligned"].shape),
        "cell_shape": list(data.data.shape),
        "file_metadata": data.file_meta,
        **memory.peak,
        "memory_notes": "10ms sampled RSS includes shared pages, mapped RAW and debug matrix copy",
    }
    args.artifact.with_suffix(".json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def comparisons(left, right):
    report = {}
    for key in left.files:
        a, b = left[key], right[key]
        same_shape = a.shape == b.shape
        report[key] = {
            "left_shape": list(a.shape),
            "right_shape": list(b.shape),
            "exact": same_shape and np.array_equal(a, b),
        }
        if same_shape and a.size:
            report[key]["different_elements"] = int(np.count_nonzero(a != b))
            report[key]["max_absolute_difference_by_position"] = float(np.max(np.abs(a - b)))
    # Compare only common cell frames and mutual-nearest cell feature masses.
    a, b = left["cell_targets"], right["cell_targets"]
    pairs = []
    if len(a) and len(b):
        for i, value in enumerate(a):
            j = int(np.argmin(np.abs(b - value)))
            if abs(b[j] - value) / value * 1e6 <= 1 and int(np.argmin(np.abs(a - b[j]))) == i:
                pairs.append((i, j))
    _, rows_a, rows_b = np.intersect1d(
        left["cell_frames"], right["cell_frames"], return_indices=True
    )
    matched = {
        "mutual_feature_tolerance_ppm": 1.0,
        "matched_features": len(pairs),
        "common_cell_frames": len(rows_a),
    }
    if pairs and len(rows_a):
        ia, ib = np.array(pairs).T
        x = left["cells"][np.ix_(rows_a, ia)]
        y = right["cells"][np.ix_(rows_b, ib)]
        matched.update(
            exact=np.array_equal(x, y),
            different_elements=int(np.count_nonzero(x != y)),
            max_absolute_difference=float(np.max(np.abs(x - y))),
        )
    report["matched_cells"] = matched
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("mzml", type=Path)
    parser.add_argument("--ref-mz", type=float, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--mode", choices=["raw", "xml", "raw-float32-diagnostic", "xml-prior"])
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    if args.mode:
        if args.artifact is None:
            parser.error("worker requires --artifact")
        worker(args)
        return
    if args.report is None or args.report.exists():
        parser.error("--report must be a new path")
    report = {
        "parameters": {
            "ref_mz": args.ref_mz,
            "raw_timezone": "Asia/Shanghai",
            "other_processing_parameters": "CyESIData defaults; no scientific interpretation",
        },
        "prior_revision": "9d07a2e",
        "runs": {},
        "comparisons": {},
    }
    modes = ["raw", "xml", "raw-float32-diagnostic", "xml-prior"]
    with tempfile.TemporaryDirectory(prefix="scmm-thermo-validation-") as directory:
        folder = Path(directory)
        for mode in modes:
            print(f"Validating {mode}", flush=True)
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                str(args.raw),
                str(args.mzml),
                "--ref-mz",
                str(args.ref_mz),
                "--mode",
                mode,
                "--artifact",
                str(folder / mode),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
            if result.returncode:
                raise RuntimeError(f"{mode} failed: {result.stderr}\n{result.stdout}")
            report["runs"][mode] = json.loads((folder / mode).with_suffix(".json").read_text())
        for a, b in [("xml", "xml-prior"), ("raw-float32-diagnostic", "xml"), ("raw", "xml")]:
            with (
                np.load((folder / a).with_suffix(".npz")) as left,
                np.load((folder / b).with_suffix(".npz")) as right,
            ):
                report["comparisons"][a + "_vs_" + b] = comparisons(left, right)
    with args.report.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, ensure_ascii=False)
        out.write("\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # Exact numerical assertions, excluding documented RT serialization noise.
    for pair in ["xml_vs_xml-prior", "raw-float32-diagnostic_vs_xml"]:
        for key in ["aligned", "targets", "cells", "cell_targets", "cell_frames"]:
            if not report["comparisons"][pair][key]["exact"]:
                raise AssertionError(f"Unexpected semantic difference: {pair}/{key}")


if __name__ == "__main__":
    main()
