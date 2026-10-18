"""Offline scientific smoke report for the WIN-01 portable interpreter.

Copy with the runtime; invoke python.exe -I validate_windows_runtime.py --report
<new-file>. Native libraries also require an actually disconnected clean VM.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import struct
import sys
import tempfile
import time
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo


def no_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
        raise RuntimeError("Network disabled by WIN-01 Python audit hook")


def array_checks(directory):
    import anndata
    import numpy as np
    from scipy.linalg import solve

    from scMM.util.normalize import norm_total

    matrix = np.array([[2.0, 1.0], [1.0, 3.0]], dtype=np.float64)
    np.testing.assert_allclose(solve(matrix, matrix @ np.array([2.0, 4.0])), [2.0, 4.0])
    np.testing.assert_allclose(norm_total(matrix, {}).sum(axis=1), 1.0)
    data = anndata.AnnData(matrix)
    data.obs_names = ["细胞 一", "细胞 二"]
    data.var_names = ["100.123456789", "200.987654321"]
    path = directory / "中文 矩阵.h5ad"
    data.write_h5ad(path)
    restored = anndata.read_h5ad(path)
    np.testing.assert_array_equal(restored.X, matrix)
    assert restored.X.dtype == np.float64
    assert restored.obs_names.equals(data.obs_names)


def openms_checks(directory):
    import numpy as np
    import pyopenms

    from scMM.file.io import load_single_file, save_spectra

    spectrum = pyopenms.MSSpectrum()
    spectrum.set_peaks((np.array([100.123456789, 200.987654321]), np.array([10.0, 20.0])))
    spectrum.setRT(1.25)
    experiment = pyopenms.MSExperiment()
    experiment.addSpectrum(spectrum)
    path = str(directory / "中文 谱.mzML")
    save_spectra(spectrum, path)
    restored, _metadata = load_single_file(path)
    for actual, expected in zip(restored[0].get_peaks(), spectrum.get_peaks(), strict=True):
        np.testing.assert_array_equal(actual, expected)
    assert restored[0].getRT() == 1.25
    xml_path = directory / "中文 谱.mzXML"
    # OpenMS's mzXML writer uses 32-bit peaks. Exercise our 64-bit input reader
    # with an explicit synthetic fixture instead of rounding away the error.
    mz, intensity = spectrum.get_peaks()
    encoded = base64.b64encode(np.column_stack([mz, intensity]).astype(">f8").tobytes()).decode(
        "ascii"
    )
    xml_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<mzXML xmlns="http://sashimi.sourceforge.net/schema_revision/mzXML_3.2">'
        '<msRun scanCount="1"><scan num="1" msLevel="1" peaksCount="2" retentionTime="PT1.25S">'
        '<peaks precision="64" byteOrder="network" pairOrder="m/z-int">'
        + encoded
        + "</peaks></scan></msRun></mzXML>",
        encoding="utf-8",
    )
    restored, _metadata = load_single_file(xml_path)
    for actual, expected in zip(restored[0].get_peaks(), spectrum.get_peaks(), strict=True):
        np.testing.assert_array_equal(actual, expected)


def numba_checks(directory):
    import numba
    import numpy as np

    compiled = numba.njit(cache=False)(sum_squares)
    assert compiled(np.arange(10, dtype=np.float64)) == 285.0


def sum_squares(array):
    return (array * array).sum()


def supervised_checks(directory):
    import numpy as np
    import shap
    from imblearn.over_sampling import SMOTE
    from sklearn.tree import DecisionTreeRegressor

    x = np.arange(24, dtype=float).reshape(12, 2)
    y = np.array([0] * 8 + [1] * 4)
    sampled_x, sampled_y = SMOTE(k_neighbors=2, random_state=0).fit_resample(x, y)
    assert sampled_x.shape == (16, 2) and np.bincount(sampled_y).tolist() == [8, 8]
    model = DecisionTreeRegressor(max_depth=2, random_state=0).fit(x, x[:, 0])
    explainer = shap.TreeExplainer(model)
    np.testing.assert_allclose(
        explainer.shap_values(x).sum(axis=1) + explainer.expected_value, model.predict(x)
    )


def cluster_checks(directory):
    import igraph
    import leidenalg
    import numpy as np
    from umap import UMAP

    graph = igraph.Graph(edges=[(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)])
    partition = leidenalg.find_partition(graph, leidenalg.ModularityVertexPartition, seed=0)
    assert sorted(map(len, partition)) == [3, 3]
    x = np.random.default_rng(0).normal(size=(24, 4))
    embedding = UMAP(n_neighbors=5, random_state=0, n_jobs=1).fit_transform(x)
    assert embedding.shape == (24, 2) and np.isfinite(embedding).all()


def resource_checks(directory):
    import importlib.resources

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    figure = Figure()
    figure.subplots().plot([0, 1], [0, 1])
    figure.savefig(directory / "plot.svg")
    static = importlib.resources.files("scMM.api").joinpath("static/index.html")
    assert static.is_file(), "Missing built Vue entry"
    rules = importlib.resources.files("scMM").joinpath("resources/lipid_rules")
    assert any(item.name.endswith(".json") for item in rules.iterdir())
    assert ZoneInfo("Asia/Shanghai").key == "Asia/Shanghai"


def raw_protocol_checks(directory):
    import numpy as np

    from scMM.file.readers.thermo_raw import ThermoRawError, ThermoRawReader

    source = directory / "中文 合成.RAW"
    source.touch()
    text = "合成仪器".encode()
    header = (
        b"SCMMRAW1"
        + struct.pack("<i", 1)
        + struct.pack("<i", 0)
        + struct.pack("<i", len(text))
        + text
    )
    mz = np.array([100.123456789, 200.987654321], dtype="<f8")
    intensity = np.array([10.123456789, 20.987654321], dtype="<f8")
    scan = b"\1" + struct.pack("<iiBdi", 1, 1, 1, 1.25, 2) + mz.tobytes() + intensity.tobytes()
    payload = header + scan + b"\0" + struct.pack("<iq", 1, 2)

    def reader(data, before="", timeout=5):
        code = (
            "import sys,time;"
            + before
            + "sys.stdout.buffer.write("
            + repr(data)
            + ");sys.stdout.buffer.flush()"
        )
        return ThermoRawReader(source, command=[sys.executable, "-c", code], timeout=timeout)

    with reader(
        payload, before="sys.stderr.buffer.write(b'x'*100000);sys.stderr.flush();"
    ) as stream:
        scans = list(stream)
        assert stream.instrument == "合成仪器"
    np.testing.assert_array_equal(scans[0].mz, mz)
    np.testing.assert_array_equal(scans[0].intensity, intensity)
    assert not scans[0].mz.flags.writeable and stream.process.poll() == 0
    assert len(stream._stderr) <= 65536 and not stream._thread.is_alive()
    for data, before, timeout in (
        (payload + b"x", "", 5),
        (header + scan[:-1], "", 5),
        (b"", "time.sleep(5);", 0.2),
    ):
        stream = reader(data, before=before, timeout=timeout)
        try:
            with stream:
                list(stream)
        except ThermoRawError:
            pass
        else:
            raise AssertionError("Invalid or stalled RAW protocol was accepted")
        assert stream.process.poll() is not None
        assert not stream._thread.is_alive()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--source-root", type=Path, help="Explicitly validate the original source checkout"
    )
    parser.add_argument(
        "--allow-non-windows",
        action="store_true",
        help="Tool debugging only; never Windows acceptance",
    )
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error("Report exists; choose a new path to preserve prior evidence")
    root = Path(sys.executable).resolve().parent
    native = sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}
    report = {
        "schema": 1,
        "kind": "WIN-01 synthetic smoke; clean-machine and user acceptance separate",
        "native_windows_x64": native,
        "python": platform.python_version(),
        "os": platform.platform(),
        "isolated": bool(sys.flags.isolated),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "network": "Python audit hook; native DLL traffic requires offline OS",
        "checks": {},
        "execution_mode": "source" if args.source_root else "wheel",
    }
    started = time.monotonic()
    try:
        if not native and not args.allow_non_windows:
            raise RuntimeError("Run with native Windows x64 portable Python")
        if not sys.flags.isolated:
            raise RuntimeError("Invoke the interpreter with -I")
        if native:
            manifest_path = root.parent / "poc.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            report["inputs_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            report["source_commit"] = manifest["git_commit"]
            report["source_dirty"] = manifest["dirty"]
            if platform.python_version() != manifest["runtime"]["python"]:
                raise RuntimeError("Python version differs from PoC manifest")
            if sys.prefix != sys.base_prefix:
                raise RuntimeError("Expected portable base interpreter, not a venv")
            import scMM

            report["scmm_module"] = scMM.__file__
            permitted = [root]
            if args.source_root:
                repository = args.source_root.resolve(strict=True)
                permitted.append(repository)
                if Path(scMM.__file__).resolve() != repository / "scMM/__init__.py":
                    raise RuntimeError("Source validation is loading a different scMM checkout")
            elif not Path(scMM.__file__).resolve().is_relative_to(root):
                raise RuntimeError("Wheel validation is loading scMM outside the runtime")
            if any(
                not any(Path(item).resolve().is_relative_to(base) for base in permitted)
                for item in sys.path
            ):
                raise RuntimeError("Python search path escaped the portable runtime")
            for wheel in manifest["wheels"]:
                if importlib.metadata.version(wheel["name"]) != wheel["version"]:
                    raise RuntimeError(f"Installed package version differs: {wheel['name']}")
        sys.addaudithook(no_network)
        try:
            socket.getaddrinfo("example.com", 443)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Network hook did not reject DNS")
        # All generated scientific data are temporary, never added to the report.
        with tempfile.TemporaryDirectory(prefix="scMM 中文 PoC ") as temporary:
            directory = Path(temporary)
            for name, check in {
                "numpy_scipy_h5ad_scmm": array_checks,
                "pyopenms_mzml": openms_checks,
                "numba_jit": numba_checks,
                "smote_shap": supervised_checks,
                "igraph_leiden_umap": cluster_checks,
                "plot_resources_tzdata": resource_checks,
                "raw_synthetic_protocol": raw_protocol_checks,
            }.items():
                before = time.monotonic()
                try:
                    check(directory)
                    report["checks"][name] = {
                        "status": "passed",
                        "seconds": time.monotonic() - before,
                    }
                except Exception:
                    report["checks"][name] = {"status": "failed", "error": traceback.format_exc()}
        report["packages"] = {
            dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()
        }
        report["status"] = (
            "passed"
            if all(item["status"] == "passed" for item in report["checks"].values())
            else "failed"
        )
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    report["seconds"] = time.monotonic() - started
    if native:
        try:
            import psutil

            report["peak_working_set_bytes"] = psutil.Process(os.getpid()).memory_info().peak_wset
            report["runtime_bytes"] = sum(
                path.stat().st_size for path in root.rglob("*") if path.is_file()
            )
        except Exception:
            report.update(status="failed", metrics_error=traceback.format_exc())
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{report['status']}: {args.report}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
