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
