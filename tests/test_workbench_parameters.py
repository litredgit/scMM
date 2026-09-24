import json

import numpy as np
import pyopenms as oms
import pytest

from scMM.application.parameters import load_defaults
from scMM.application.processing import ProcessingParameters
from scMM.application.raw_preview import RawFilePreview
from scMM.file.data import CyESIData
from scMM.file.io import load_single_file, save_spectra


def test_json_defaults_are_validated_and_isolated(tmp_path, monkeypatch):
    config = tmp_path / "参数.json"
    config.write_text(
        json.dumps({"processing": {"mz_min": 500, "mz_max": 900}, "analysis": {"cv": 3}})
    )
    monkeypatch.setenv("SCMM_UI_CONFIG", str(config))
    first = load_defaults()
    assert first.processing.mz_min == 500
    assert first.analysis["cv"] == 3
    first.analysis["cv"] = 99
    assert load_defaults().analysis["cv"] == 3
    for override in [
        {"unknown": {}},
        {"analysis": {"oops": 1}},
        {"analysis": {"cv": True}},
        {"analysis": {"test_size": float("nan")}},
        {"processing": {"noise_window": 2.5}},
        {"processing": {"mz_max": 400}},
        {"processing": {"reference_mz": ["760"]}},
    ]:
        config.write_text(json.dumps(override))
        with pytest.raises(ValueError):
            load_defaults()


def _spectra(path):
    values = []
    for i in range(31):
        signal = 20.0 if i in {8, 22} else 1.0
        spec = oms.MSSpectrum()
        spec.setMSLevel(1)
        spec.setRT(float(i))
        spec.set_peaks(
            (
                np.array([149.9, 150, 150.1, 199.9, 200, 200.1]),
                np.array([0, signal, 0, 0, signal, 0]),
            )
        )
        values.append(spec)
    return save_spectra(values, path)


@pytest.mark.parametrize("strategy", ["single", "legacy", "shared", "independent"])
def test_extraction_range_reaches_all_loaders(tmp_path, strategy):
    path = _spectra(tmp_path / "sample.mzML")
    kwargs = dict(
        ref_mz=150.0,
        mz_range=(140.0, 160.0),
        resolution=5000.0,
        resample_points_per_fwhm=2.0,
        ppm_tol=500.0,
        baseline_filter_size=5,
        n_jobs=1,
    )
    if strategy == "single":
        result = CyESIData.load_from_file(path, **kwargs)
    else:
        result = CyESIData.load_from_filelist(tmp_path, processing_strategy=strategy, **kwargs)
    assert len(result.data) == 2
    assert len(result.data.columns) >= 1
    assert all(140 <= float(mz) <= 160 for mz in result.data.columns)
    metadata = result.file_meta.get(
        "mz_range", result.file_meta.get("processing", {}).get("mz_range")
    )
    assert metadata == [140.0, 160.0]


def test_preview_range_single_scan_and_multiple_eics(tmp_path):
    path = _spectra(tmp_path / "sample.mzML")
    experiment, metadata = load_single_file(path)
    raw = RawFilePreview(path, experiment, metadata)
    frame, meta = raw.single_spectrum(8)
    assert meta == {"scan_index": 8, "rt_seconds": 8.0, "ms_level": 1}
    assert frame.intensity.max() == 20
    for index in [-1, 31, True, 1.5]:
        with pytest.raises(ValueError):
            raw.single_spectrum(index)
    frame = raw.extracted_ion_chromatograms([150.0, 200.0])
    assert len(frame) == 62
    assert set(frame.reference_mz) == {150.0, 200.0}
    params = ProcessingParameters(
        ref_mz=150.0,
        mz_min=140.0,
        mz_max=160.0,
        resolution=5000.0,
        resample_points_per_fwhm=2.0,
        ppm_tol=500.0,
        baseline_filter_size=5,
    )
    preview = raw.cell_detection(params)
    assert preview.cell_count == 2
    assert all(140 <= mz <= 160 for mz in preview.reference_mz)
    with pytest.raises(ValueError, match="mz_range"):
        ProcessingParameters(ref_mz=150.0, mz_min=200.0)
