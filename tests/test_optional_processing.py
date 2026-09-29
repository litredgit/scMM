from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scMM.file._dataset_loading import DatasetState
from scMM.file._sequential import merge_objects
from scMM.file.data import CyESIData
from scMM.util._cell_snr import find_cell_peaks_snr


def test_multi_reference_and_corrected_intensity():
    values = np.ones((31, 2))
    values[6] = [20, 12]
    values[24] = [1, 20]
    data = pd.DataFrame(values, columns=[100.0, 200.0])
    kwargs = dict(baseline_window=5, noise_window=5, show_progress=False)
    union = find_cell_peaks_snr(data, [100.0, 200.0], **kwargs)
    intersection = find_cell_peaks_snr(
        data, [100.0, 200.0], reference_mode="intersection", **kwargs
    )
    assert len(union["cell_df"]) == 2
    assert len(intersection["cell_df"]) == 1
    np.testing.assert_allclose(intersection["cell_df"].values, [[19, 11]])
    with pytest.raises(ValueError, match="reference_ppm_tol"):
        find_cell_peaks_snr(data, [150.0], **kwargs)
    obj = CyESIData._from_raw_state(
        DatasetState(data, pd.DataFrame({"rt": np.arange(31)}), {"name": "sample"}, 100.0),
        dict(
            extraction_method="snr_v1",
            reference_mz=[100.0, 200.0],
            baseline_filter_size=5,
            noise_window=5,
            show_progress=False,
        ),
    )
    assert obj.feature_snr.shape == obj.data.shape
    assert "reference_intensity_100" in obj.peak_meta
    assert obj.file_meta["processing"]["extraction_method"] == "snr_v1"


def test_independent_merge_preserves_collisions_and_snr():
    objects = []
    for name, columns, values in [
        ("a", [100.0, 100.0002, 200.0], [[1.0, 3.0, 9.0]]),
        ("b", [100.0004, 300.0], [[5.0, 7.0]]),
    ]:
        data = pd.DataFrame(values, columns=columns)
        objects.append(
            SimpleNamespace(
                data=data,
                feature_snr=data * 2,
                peak_meta=pd.DataFrame({"source_file": [name]}),
                file_meta={"name": name},
                ref_mz=100.0,
            )
        )
    obj = merge_objects(CyESIData, objects, 10.0)
    np.testing.assert_allclose(obj.data, [[3, 9, 0], [5, 0, 7]])
    np.testing.assert_allclose(obj.feature_snr, obj.data * 2)
    assert obj.feature_meta["source_file_count"].tolist() == [2, 1, 1]


@pytest.mark.parametrize("strategy", ["shared", "independent"])
def test_sequential_file_boundaries_with_real_mzml(tmp_path, monkeypatch, strategy):
    import pyopenms as oms

    from scMM.file import _dataset_loading, _sequential
    from scMM.file.io import save_spectra

    for name, signals in [("a", [1, 1, 10, 20]), ("b", [20, 10, 1, 1])]:
        spectra = []
        for i, signal in enumerate(signals):
            spec = oms.MSSpectrum()
            spec.setMSLevel(1)
            spec.setRT(float(i))
            spec.set_peaks((np.array([149.9, 150.0, 150.1]), np.array([0.0, signal, 0.0])))
            spectra.append(spec)
        save_spectra(spectra, tmp_path / f"{name}.mzML")

    def summed(*args, **kwargs):
        spec = oms.MSSpectrum()
        spec.set_peaks((np.array([149.9, 150.0, 150.1]), np.array([0.0, 100.0, 0.0])))
        return spec

    monkeypatch.setattr(_sequential, "sum_spec", summed)
    monkeypatch.setattr(_sequential, "filter_spectrum", lambda spec, **kw: spec)
    monkeypatch.setattr(
        _dataset_loading, "_pick_common_targets", lambda *a, **kw: np.array([150.0])
    )
    progress = []
    obj = CyESIData.load_from_filelist(
        tmp_path,
        150.0,
        processing_strategy=strategy,
        baseline_filter=lambda values, **kw: np.ones_like(values),
        progress_callback=lambda value, message: progress.append(value),
        n_jobs=1,
    )
    assert obj.data.shape == (2, 1)
    np.testing.assert_allclose(obj.data, [[20.0], [20.0]])
    assert obj.peak_meta.source_file.tolist() == ["a.mzML", "b.mzML"]
    assert progress[-1] == 1.0
    assert progress == sorted(progress)
    assert all(0 <= value <= 1 for value in progress)
    assert obj.file_meta["processing"]["feature_strategy"] == strategy


def test_msconvert_rejects_stale_or_unrelated_output(tmp_path, monkeypatch):
    from scMM.file import msconvert

    raw = tmp_path / "a.raw"
    raw.touch()
    executable = tmp_path / "msconvert"
    executable.touch()
    out = tmp_path / "out"
    out.mkdir()
    (out / "unrelated.mzML").touch()
    monkeypatch.setattr(
        msconvert.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="", stderr="")
    )
    with pytest.raises(msconvert.MSConvertError, match="produced no"):
        msconvert.convert_raw(raw, out, executable=executable)
    (out / "a.mzML").touch()
    with pytest.raises(FileExistsError):
        msconvert.convert_raw(raw, out, executable=executable)


def test_full_synthetic_processing_and_h5ad(tmp_path):
    import pyopenms as oms

    from scMM.file.io import save_spectra

    spectra = []
    mz = np.array([149.8, 149.9, 150.0, 150.1, 150.2, 199.8, 199.9, 200.0, 200.1, 200.2])
    for i in range(31):
        signal = 20.0 if i in {8, 22} else 1.0
        spec = oms.MSSpectrum()
        spec.setMSLevel(1)
        spec.setRT(float(i))
        spec.set_peaks((mz, np.array([0, 0, signal, 0, 0, 0, 0, signal * 0.7, 0, 0])))
        spectra.append(spec)
    path = save_spectra(spectra, tmp_path / "synthetic.mzML")
    data = CyESIData.load_from_file(
        path,
        150.0,
        resolution=5000.0,
        resample_points_per_fwhm=2.0,
        ppm_tol=500.0,
        extraction_method="snr_v1",
        reference_ppm_tol=500.0,
        baseline_filter_size=5,
        noise_window=5,
        show_progress=False,
    )
    assert len(data.data) == 2
    assert np.isfinite(data.data.to_numpy()).all()
    exported = data.save_h5ad(tmp_path / "synthetic.h5ad")
    restored = CyESIData.read_h5ad(exported)
    np.testing.assert_array_equal(restored.data, data.data)
    np.testing.assert_array_equal(restored.feature_snr, data.feature_snr)


@pytest.mark.parametrize("valid", [True, False])
def test_explicit_raw_conversion_keeps_xml_validation(tmp_path, monkeypatch, valid):
    from pathlib import Path

    import pyopenms as oms

    from scMM.file import msconvert
    from scMM.file.io import InvalidMSFileError, load_single_file, save_spectra

    raw = tmp_path / "source with spaces.raw"
    raw.mkdir()
    executable = tmp_path / "msconvert"
    executable.touch()
    converted = []

    def run(command, **options):
        assert command[1] == str(raw.resolve())
        assert options["timeout"] == 3600
        target = Path(command[command.index("--outdir") + 1]) / f"{raw.stem}.mzML"
        converted.append(target)
        if valid:
            spectrum = oms.MSSpectrum()
            spectrum.setMSLevel(1)
            spectrum.set_peaks((np.array([100.0]), np.array([20.0])))
            save_spectra(spectrum, target)
        else:
            target.write_text("<mzML>")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(msconvert.subprocess, "run", run)
    # Conversion remains a standalone explicit utility, never an automatic reader path.
    result = msconvert.convert_raw(raw, tmp_path / "converted", executable=executable)
    if valid:
        exp, metadata = load_single_file(result)
        assert exp.getNrSpectra() == 1
        assert metadata["name"] == raw.stem
    else:
        with pytest.raises(InvalidMSFileError, match="XML"):
            load_single_file(result)
    assert converted and converted[0].exists()
    with pytest.raises(ValueError, match="convert explicitly"):
        load_single_file(raw, msconvert_path=executable)
