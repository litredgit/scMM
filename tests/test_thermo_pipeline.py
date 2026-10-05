"""RAW/XML semantic regression without vendor SDK or private fixtures."""

import base64
import struct
import sys
import weakref
from datetime import UTC, datetime
from zoneinfo import ZoneInfoNotFoundError

import numpy as np
import pandas as pd
import pyopenms as oms
import pytest

from scMM.file import _alignment, _dataset_loading, _spectrum
from scMM.file.data import CyESIData
from scMM.file.io import align_frame, load_single_file, save_spectra, sum_spec
from scMM.file.readers import Spectrum, ThermoRawError, thermo_raw
from scMM.file.readers import source as raw_source


def _text(value):
    data = value.encode()
    return struct.pack("<i", len(data)) + data


@pytest.fixture
def raw_pair(tmp_path, monkeypatch):
    spectra = []
    wire = (
        b"SCMMRAW1"
        + struct.pack("<i", 31)
        + _text("2026-09-22T16:04:29.9770000")
        + _text("Q Exactive")
    )
    mz = np.array([149.8, 149.9, 150.0, 150.1, 150.2, 199.8, 199.9, 200.0, 200.1, 200.2])
    for i in range(31):
        signal = 20.0 if i in {8, 22} else 1.0
        intensity = np.array([0, 0, signal, 0, 0, 0, 0, signal * 0.7, 0, 0], dtype=np.float32)
        s = oms.MSSpectrum()
        s.setMSLevel(1)
        s.setType(oms.SpectrumSettings.SpectrumType.PROFILE)
        s.setRT(float(i))
        s.set_peaks((mz, intensity))
        spectra.append(s)
        wire += b"\1" + struct.pack("<iiBdi", i + 10, 1, 1, float(i), len(mz))
        wire += mz.astype("<f8").tobytes() + intensity.astype("<f8").tobytes()
    wire += b"\0" + struct.pack("<iq", 31, 310)
    script = f"import os,base64; os.write(1,base64.b64decode({base64.b64encode(wire)!r}))"
    monkeypatch.setattr(thermo_raw, "reader_command", lambda: [sys.executable, "-c", script])
    monkeypatch.delenv("SCMM_RAW_TIMEZONE", raising=False)
    raw = tmp_path / "sample.RAW"
    raw.touch()
    xml = save_spectra(spectra, tmp_path / "sample.mzML")
    return raw, xml


OPTIONS = dict(
    ref_mz=150.0,
    resolution=5000.0,
    resample_points_per_fwhm=2.0,
    ppm_tol=500.0,
    extraction_method="snr_v1",
    reference_ppm_tol=500.0,
    baseline_filter_size=5,
    noise_window=5,
    show_progress=False,
)


def test_raw_web_preview_matches_xml(raw_pair):
    from scMM.application import RawPreviewService, StorageCatalog, StorageRoot
    from scMM.file.io import validate_ms_file

    raw, xml = raw_pair
    catalog = StorageCatalog([StorageRoot("data", raw.parent)])
    assert catalog.resolve_raw_file("data", raw) == raw
    assert raw.name in [entry.name for entry in catalog.list_entries("data")]
    validate_ms_file(raw)
    service = RawPreviewService(catalog)
    direct, baseline = (service.open("data", path) for path in (raw, xml))
    assert direct.summary.scan_count == baseline.summary.scan_count
    for operation, kwargs in [
        ("total_ion_chromatogram", {}),
        ("extracted_ion_chromatogram", {"target_mz": 150.0}),
        ("extracted_ion_chromatograms", {"references": [200.0, 150.0, 150.0]}),
        ("binned_spectrum", {"mz_range": (140, 210), "bins": 100}),
        ("summed_spectrum", {"mz_range": (140, 210), "resolution_200": 5000}),
    ]:
        pd.testing.assert_frame_equal(
            getattr(direct, operation)(**kwargs), getattr(baseline, operation)(**kwargs)
        )
    for index in (0, 15, 30):
        actual, meta = direct.single_spectrum(index)
        expected, expected_meta = baseline.single_spectrum(index)
        pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
        assert meta == expected_meta


def test_raw_web_reader_closes_on_early_scan_and_preview_error(raw_pair, monkeypatch):
    from scMM.application import RawPreviewService, StorageCatalog, StorageRoot

    raw, _ = raw_pair
    readers = []
    cls = raw_source.ThermoRawReader

    def factory(*args, **kwargs):
        reader = cls(*args, **kwargs)
        readers.append(reader)
        return reader

    monkeypatch.setattr(raw_source, "ThermoRawReader", factory)
    preview = RawPreviewService(StorageCatalog([StorageRoot("data", raw.parent)])).open("data", raw)
    preview.single_spectrum(0)

    def fail(*args, **kwargs):
        raise ValueError("preview failure")

    monkeypatch.setattr(np, "nansum", fail)
    with pytest.raises(ValueError, match="preview failure"):
        preview.total_ion_chromatogram()
    assert len(readers) == 4
    assert all(r.process.poll() is not None and r.process.stdout.closed for r in readers)


def test_raw_web_project_entry(raw_pair, tmp_path, monkeypatch):
    from scMM.application import StorageRoot
    from scMM.ui.app import ProjectWorkspace

    raw, _ = raw_pair
    ui = ProjectWorkspace((StorageRoot("data", tmp_path),), project_root=tmp_path)
    ui.name.value = "RAW UI"
    ui._create()
    ui.files.value = [str(raw)]
    ui._add_files()
    ui._open_raw()
    assert ui.components.preview.summary.scan_count == 31
    assert not ui.components.tic.empty
    monkeypatch.setattr(thermo_raw, "reader_command", lambda: ["/nonexistent/scmm-reader"])
    with pytest.raises(ValueError, match="原始文件读取失败"):
        ui._open_raw()
    assert ui.components.preview is None
    assert ui.components.tic.empty
    assert ui.components.cell_download.disabled


@pytest.mark.parametrize("strategy", ["shared", "independent"])
def test_raw_project_batch(raw_pair, tmp_path, strategy):
    from dataclasses import asdict

    from scMM.application import StorageCatalog, StorageRoot
    from scMM.application.processing import ProcessingParameters
    from scMM.application.project_batch import preflight, read_batch, reviewed_dataset, run_batch
    from scMM.application.projects import ProjectStore, write_json

    raw, _ = raw_pair
    catalog = StorageCatalog([StorageRoot("data", tmp_path)])
    (tmp_path / "projects").mkdir()
    project = ProjectStore(tmp_path / "projects").create("RAW regression")
    project.add_files(catalog, "data", [raw])
    project.manifest["feature_strategy"] = strategy
    project.manifest["parameters"] = asdict(
        ProcessingParameters(**{k: v for k, v in OPTIONS.items() if k != "show_progress"})
    )
    request = preflight(project, catalog)
    request["created_at"] = "test"
    folder = project.folder / "processing" / "test"
    folder.mkdir()
    write_json(folder / "request.json", request)
    run_batch(folder / "state.json")
    state = read_batch(folder / "state.json")
    assert state["status"] == "completed", state
    assert state["samples"][0]["status"] == "succeeded", state
    result = reviewed_dataset(folder / "state.json", [project.samples[0]["id"]])
    assert result.n_obs > 0


def test_source_reopens_and_preserves_time_and_frame_semantics(raw_pair, monkeypatch):
    raw, _xml = raw_pair
    source, meta = load_single_file(raw)
    assert source.getNrSpectra() == 31
    assert meta["converted_from_raw"] is False
    assert meta["timestamp"] == datetime(2026, 9, 22, 8, 4, 29, 977000, tzinfo=UTC).timestamp()
    assert meta["acquisition_timezone"] == "Asia/Shanghai"
    for _ in range(2):
        frames, obs = align_frame(source, [150.0], ppm=500.0)
        assert frames.index.tolist() == list(range(31))
        assert obs.rt.tolist() == list(range(31))
    monkeypatch.setenv("SCMM_RAW_TIMEZONE", "UTC")
    _, utc = load_single_file(raw)
    assert utc["timestamp"] - meta["timestamp"] == 8 * 3600
    _, override = load_single_file(raw, raw_timezone="Asia/Shanghai")
    assert override["timestamp"] == meta["timestamp"]
    raw.write_bytes(b"changed")
    with pytest.raises(ThermoRawError, match="changed"):
        list(source)


def test_full_raw_and_mzml_processing_equal(raw_pair, tmp_path):
    raw, xml = raw_pair
    direct = CyESIData.load_from_file(raw, **OPTIONS)
    baseline = CyESIData.load_from_file(xml, **OPTIONS)
    pd.testing.assert_frame_equal(direct.data, baseline.data)
    pd.testing.assert_frame_equal(direct.feature_snr, baseline.feature_snr)
    pd.testing.assert_frame_equal(
        direct.peak_meta[["rt", "frame_id", "time"]], baseline.peak_meta[["rt", "frame_id", "time"]]
    )
    path = direct.save_h5ad(tmp_path / "direct.h5ad")
    restored = CyESIData.read_h5ad(path)
    np.testing.assert_array_equal(restored.data, direct.data)
    assert restored.file_meta["reader_backend"] == "thermo_rawfilereader"


@pytest.mark.parametrize("strategy", ["legacy", "shared", "independent"])
def test_raw_directory_processing(raw_pair, tmp_path, strategy):
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "a.RAW").touch()
    (folder / "b.raw").touch()
    (folder / "ignored.raw").mkdir()  # Thermo file support, not other vendors' directories
    (folder / "notes.txt").touch()
    data = CyESIData.load_from_filelist(
        folder, processing_strategy=strategy, raw_timezone="UTC", **OPTIONS
    )
    assert data.data.shape[0] in (2, 4)  # legacy concatenates before cell extraction
    assert len(data.file_meta["per_file_meta"]) == 2
    assert all(m["acquisition_timezone"] == "UTC" for m in data.file_meta["per_file_meta"])
    assert all(
        m["reader_backend"] == "thermo_rawfilereader" for m in data.file_meta["per_file_meta"]
    )
    assert not list(folder.glob("*.mzML"))


@pytest.mark.parametrize("operation", ["sum", "align"])
def test_algorithm_failure_closes_pipe(raw_pair, monkeypatch, operation):
    raw, _ = raw_pair
    created = []
    cls = thermo_raw.ThermoRawReader

    def factory(*args, **kwargs):
        reader = cls(*args, **kwargs)
        created.append(reader)
        return reader

    monkeypatch.setattr(raw_source, "ThermoRawReader", factory)
    source, _ = load_single_file(raw)

    def fail(*a, **k):
        raise ValueError("algorithm failure")

    if operation == "sum":
        monkeypatch.setattr(_spectrum, "_prepare_sorted_unique_peaks", fail)

        def callback():
            return sum_spec(source)
    else:
        monkeypatch.setattr(_alignment, "extract_peaks", fail)

        def callback():
            return align_frame(source, [150.0])

    with pytest.raises(ValueError, match="algorithm failure"):
        callback()
    assert len(created) == 2
    assert all(r.process.poll() is not None and r.process.stdout.closed for r in created)


def test_alignment_does_not_retain_raw_spectra():
    seen = []

    def stream():
        for i in range(30):
            assert sum(r() is not None for r in seen) <= 1
            s = Spectrum(
                i + 1,
                float(i),
                np.array([149.0, 150.0, 151.0]),
                np.array([0.0, 10.0, 0.0]),
                2 if i == 1 else 1,
            )
            seen.append(weakref.ref(s))
            yield s

    frame, obs = align_frame(stream(), [150.0], distance=1)
    assert frame.index.tolist() == [i for i in range(30) if i != 1]
    assert obs.rt.tolist() == [float(i) for i in range(30) if i != 1]


def test_missing_reader_never_calls_converter(tmp_path, monkeypatch):
    from scMM.file import msconvert

    raw = tmp_path / "missing.RAW"
    raw.touch()
    monkeypatch.setenv("SCMM_THERMO_READER", str(tmp_path / "not-installed"))

    def forbidden(*args, **kwargs):
        pytest.fail("implicit conversion")

    monkeypatch.setattr(msconvert, "convert_raw", forbidden)
    with pytest.raises(ThermoRawError, match="not installed"):
        CyESIData.load_from_file(raw, **OPTIONS)


def test_legacy_raw_default_is_serial(raw_pair, tmp_path, monkeypatch):
    jobs = []
    original = _dataset_loading.Parallel

    def parallel(*a, **kw):
        jobs.append(kw["n_jobs"])
        return original(*a, **kw)

    monkeypatch.setattr(_dataset_loading, "Parallel", parallel)
    folder = tmp_path / "raw-only"
    folder.mkdir()
    (folder / "a.raw").touch()
    CyESIData.load_from_filelist(folder, **OPTIONS)
    assert jobs == [1, 1]


def test_invalid_timezone_fails_before_starting_reader(raw_pair, monkeypatch):
    raw, _ = raw_pair

    def forbidden(*args, **kwargs):
        pytest.fail("reader started before timezone validation")

    monkeypatch.setattr(raw_source, "ThermoRawReader", forbidden)
    with pytest.raises(ZoneInfoNotFoundError):
        load_single_file(raw, raw_timezone="Invalid/Timezone")


@pytest.mark.parametrize("created", ["2026-11-01T01:30:00", "2026-03-08T02:30:00"])
def test_dst_ambiguous_and_nonexistent_acquisition_times(tmp_path, monkeypatch, created):
    class HeaderOnly:
        scan_count = 1
        creation_time = created
        instrument = "test"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(raw_source, "ThermoRawReader", lambda *args: HeaderOnly())
    path = tmp_path / "dst.raw"
    path.touch()
    with pytest.raises(ThermoRawError, match="Ambiguous/nonexistent"):
        load_single_file(path, raw_timezone="America/New_York")
