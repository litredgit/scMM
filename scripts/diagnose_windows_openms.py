"""Diagnose native OpenMS path handling using an existing WIN-01 interpreter.

Does not alter the runtime, experimental files, dependencies or system locale.
All spectra are tiny synthetic data; only a new JSON diagnostic is retained.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import locale
import platform
import sys
import tempfile
import traceback
from pathlib import Path


def probes(directory):
    import numpy as np
    import pyopenms as oms

    spectrum = oms.MSSpectrum()
    spectrum.set_peaks((np.array([100.123456789, 200.987654321]), np.array([10.0, 20.0])))
    spectrum.setRT(1.25)
    experiment = oms.MSExperiment()
    experiment.addSpectrum(spectrum)
    output = oms.String()
    oms.MzMLFile().storeBuffer(output, experiment)
    xml = output.c_str()
    result = {}

    def record(name, function):
        try:
            result[name] = {"status": "passed", "details": function()}
        except Exception:
            result[name] = {
                "status": "failed",
                "error": traceback.format_exc().replace(str(directory), "<synthetic-probe>"),
            }

    def verify(actual):
        assert actual.getNrSpectra() == 1
        for observed, expected in zip(actual[0].get_peaks(), spectrum.get_peaks(), strict=True):
            np.testing.assert_array_equal(observed, expected)
        assert actual[0].getRT() == 1.25

    for case, parent, filename in (
        ("ascii", directory / "ascii", "spectrum.mzML"),
        ("unicode_filename", directory / "ascii", "中文 谱.mzML"),
        ("unicode_parent", directory / "中文 folder", "spectrum.mzML"),
        ("unicode_both", directory / "中文 folder", "中文 谱.mzML"),
    ):
        parent.mkdir(exist_ok=True)
        original = parent / ("python-" + filename)

        def python_buffer_roundtrip(path=original):
            path.write_bytes(xml)
            restored = oms.MSExperiment()
            oms.MzMLFile().loadBuffer(path.read_bytes(), restored)
            verify(restored)
            return {"bytes": path.stat().st_size}

        record(case + "/python_io_openms_buffer", python_buffer_roundtrip)
        for encoding in ("str", "utf8_bytes", "mbcs_bytes"):
            if encoding == "mbcs_bytes" and sys.platform != "win32":
                continue

            def argument(path, method=encoding):
                value = str(path)
                if method == "utf8_bytes":
                    return value.encode("utf-8")
                if method == "mbcs_bytes":
                    return value.encode("mbcs", errors="strict")
                return value

            def store(path=parent / (encoding + "-" + filename), convert=argument):
                oms.MzMLFile().store(convert(path), experiment)
                assert path.is_file(), (
                    "OpenMS returned success but did not create the requested path"
                )
                restored = oms.MSExperiment()
                oms.MzMLFile().loadBuffer(path.read_bytes(), restored)
                verify(restored)
                return {"requested_file_exists": True}

            def load(path=original, convert=argument):
                restored = oms.MSExperiment()
                oms.MzMLFile().load(convert(path), restored)
                verify(restored)

            record(f"{case}/{encoding}/store", store)
            record(f"{case}/{encoding}/load_python_created_file", load)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--allow-non-windows", action="store_true", help="Diagnostic tool debugging only"
    )
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error("Report exists; use a new name to preserve prior evidence")
    report = {
        "schema": 1,
        "kind": "OpenMS synthetic path diagnosis; does not grant Windows acceptance",
        "native_windows": sys.platform == "win32",
        "python": platform.python_version(),
        "os": platform.platform(),
        "filesystem_encoding": sys.getfilesystemencoding(),
        "preferred_encoding": locale.getpreferredencoding(False),
        "python_utf8_mode": sys.flags.utf8_mode,
    }
    try:
        if sys.platform != "win32" and not args.allow_non_windows:
            raise RuntimeError("Run with the existing Windows private interpreter")
        if not sys.flags.isolated:
            raise RuntimeError("Invoke Python with -I")
        if sys.platform == "win32":
            report["windows_ansi_codepage"] = ctypes.windll.kernel32.GetACP()
        import pyopenms

        report["pyopenms"] = pyopenms.__version__
        # Do not add Chinese to the base: measure ASCII and Unicode separately.
        with tempfile.TemporaryDirectory(prefix="scmm-openms-probe-") as temporary:
            report["base_path_ascii"] = str(temporary).isascii()
            report["checks"] = probes(Path(temporary))
        report["status"] = "diagnosis_completed"
    except Exception:
        report.update(status="diagnosis_failed", error=traceback.format_exc())
    # Exclusive creation also protects against a report created after the initial check.
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"{report['status']}: {args.report}")
    return 0 if report["status"] == "diagnosis_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
