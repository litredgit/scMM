from pathlib import Path

import numpy as np
import pyopenms as oms
import pytest

from scMM.application import RawPreviewService, StorageCatalog, StorageRoot
from scMM.application.raw_preview import RawFilePreview


def _make_experiment() -> oms.MSExperiment:
    experiment = oms.MSExperiment()
    for retention_time, scale in [(10.0, 1.0), (20.0, 2.0)]:
        spectrum = oms.MSSpectrum()
        spectrum.setMSLevel(1)
        spectrum.setRT(retention_time)
        spectrum.set_peaks(
            (
                np.asarray([99.9, 100.0, 100.1]),
                np.asarray([1.0, 10.0 * scale, 2.0], dtype=np.float32),
            )
        )
        experiment.addSpectrum(spectrum)
    return experiment


def _write_mzml(path: Path) -> None:
    oms.MzMLFile().store(str(path), _make_experiment())


def test_multi_eic_reads_once_and_matches_individual_eics(tmp_path):
    import pandas as pd

    path = tmp_path / "sample.mzML"
    _write_mzml(path)
    preview = RawFilePreview(path, _make_experiment(), {})
    references = [100.1, 100.0, 100.1]
    expected = pd.concat(
        [
            preview.extracted_ion_chromatogram(ref).assign(reference_mz=ref)
            for ref in sorted(set(references))
        ],
        ignore_index=True,
    )

    class CountingSource:
        passes = 0

        def __iter__(self):
            self.passes += 1
            yield from _make_experiment()

    source = CountingSource()
    preview.experiment = source
    pd.testing.assert_frame_equal(preview.extracted_ion_chromatograms(references), expected)
    assert source.passes == 1
    empty = preview.extracted_ion_chromatograms(references, rt_range=(30, 40))
    assert empty.empty
    assert list(empty.columns) == list(expected.columns)
    for invalid in ([100, float("nan")], [0], []):
        with pytest.raises(ValueError):
            preview.extracted_ion_chromatograms(invalid)
    assert source.passes == 2  # Invalid input must fail before opening a stream.


def test_storage_catalog_lists_only_directories_and_raw_files(tmp_path) -> None:
    (tmp_path / "batch").mkdir()
    _write_mzml(tmp_path / "sample.mzML")
    (tmp_path / "notes.txt").write_text("not raw data")
    catalog = StorageCatalog([StorageRoot("Raw", tmp_path)])

    entries = catalog.list_entries("Raw")

    assert [(entry.name, entry.is_directory) for entry in entries] == [
        ("batch", True),
        ("sample.mzML", False),
    ]


def test_storage_catalog_rejects_paths_outside_root_and_symlink_escape(tmp_path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.mzML"
    _write_mzml(outside)
    (storage / "escape.mzML").symlink_to(outside)
    catalog = StorageCatalog([StorageRoot("Raw", storage)])

    with pytest.raises(PermissionError, match="outside storage root"):
        catalog.resolve_raw_file("Raw", outside)
    with pytest.raises(PermissionError, match="outside storage root"):
        catalog.resolve_raw_file("Raw", "escape.mzML")
    assert catalog.list_entries("Raw") == ()


def test_storage_catalog_validates_root_labels_and_file_types(tmp_path) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("notes")

    with pytest.raises(ValueError, match="label"):
        StorageRoot(" ", tmp_path)
    with pytest.raises(ValueError, match="Duplicate"):
        StorageCatalog([StorageRoot("Raw", tmp_path), StorageRoot("Raw", tmp_path)])

    catalog = StorageCatalog([StorageRoot("Raw", tmp_path)])
    with pytest.raises(ValueError, match="mzML and mzXML"):
        catalog.resolve_raw_file("Raw", text_file)


def test_storage_catalog_resolves_safe_output_directories(tmp_path) -> None:
    storage = tmp_path / "storage"
    outside = tmp_path / "outside"
    storage.mkdir()
    outside.mkdir()
    catalog = StorageCatalog([StorageRoot("Raw", storage)])

    assert catalog.resolve_output_directory("Raw", "results") == storage / "results"
    with pytest.raises(PermissionError, match="outside storage root"):
        catalog.resolve_output_directory("Raw", outside)

    (storage / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError, match="symbolic link"):
        catalog.resolve_output_directory("Raw", "escape")


def test_raw_preview_calculates_summary_tic_eic_and_spectrum(tmp_path) -> None:
    raw_path = tmp_path / "sample.mzML"
    _write_mzml(raw_path)
    service = RawPreviewService(StorageCatalog([StorageRoot("Raw", tmp_path)]))

    preview = service.open("Raw", "sample.mzML")
    tic = preview.total_ion_chromatogram()
    eic = preview.extracted_ion_chromatogram(100.0, ppm_tolerance=10)
    spectrum = preview.summed_spectrum(
        mz_range=(99.8, 100.2),
        resolution_200=1_000,
        points_per_fwhm=2,
    )
    binned = preview.binned_spectrum(mz_range=(99.8, 100.2), bins=20)

    assert preview.summary.path == raw_path.resolve()
    assert preview.summary.scan_count == 2
    assert preview.summary.scans_by_ms_level == ((1, 2),)
    assert preview.summary.rt_min_seconds == 10.0
    assert preview.summary.rt_max_seconds == 20.0
    np.testing.assert_allclose(tic["intensity"], [13.0, 23.0])
    np.testing.assert_allclose(eic["intensity"], [10.0, 20.0])
    assert list(spectrum) == ["mz", "intensity"]
    assert not spectrum.empty
    assert len(binned) == 20
    assert binned["intensity"].sum() == pytest.approx(36.0)


def test_raw_preview_applies_retention_time_range(tmp_path) -> None:
    raw_path = tmp_path / "sample.mzML"
    _write_mzml(raw_path)
    preview = RawPreviewService(StorageCatalog([StorageRoot("Raw", tmp_path)])).open(
        "Raw", raw_path
    )

    tic = preview.total_ion_chromatogram(rt_range=(15.0, 25.0))

    assert tic["scan_index"].tolist() == [1]
    assert tic["rt_seconds"].tolist() == [20.0]


@pytest.mark.parametrize(
    ("method", "kwargs", "message"),
    [
        ("total_ion_chromatogram", {"ms_level": 0}, "ms_level"),
        ("total_ion_chromatogram", {"rt_range": (2.0, 1.0)}, "rt_range"),
        ("extracted_ion_chromatogram", {"target_mz": 0.0}, "target_mz"),
        (
            "extracted_ion_chromatogram",
            {"target_mz": 100.0, "ppm_tolerance": 0.0},
            "ppm_tolerance",
        ),
        ("binned_spectrum", {"mz_range": (100.0, 100.0)}, "mz_range"),
        ("binned_spectrum", {"mz_range": (99.0, 101.0), "bins": 1}, "bins"),
    ],
)
def test_raw_preview_validates_preview_parameters(tmp_path, method, kwargs, message) -> None:
    raw_path = tmp_path / "sample.mzML"
    _write_mzml(raw_path)
    preview = RawPreviewService(StorageCatalog([StorageRoot("Raw", tmp_path)])).open(
        "Raw", raw_path
    )

    with pytest.raises(ValueError, match=message):
        getattr(preview, method)(**kwargs)
