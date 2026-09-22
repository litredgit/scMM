import numpy as np
import pandas as pd
import pyopenms as oms
import pytest

from scMM.application import ProcessingParameters, RawPreviewService, StorageCatalog, StorageRoot
from scMM.file._dataset_loading import DatasetState
from scMM.file.data import CyESIData
from scMM.file.io import save_spectra
from scMM.util._cell_snr import find_cell_peaks_snr
from scMM.util.peak import find_cell_peaks


@pytest.mark.parametrize("snr", [False, True])
@pytest.mark.parametrize("cells", [False, True])
def test_block_progress_preserves_results_and_propagates_failure(snr, cells):
    values = np.ones((31, 3))
    if cells:
        values[8] = 20
    data = pd.DataFrame(values, columns=[100.0, 200.0, 300.0])
    function = find_cell_peaks_snr if snr else find_cell_peaks
    kwargs = (
        dict(baseline_window=5, noise_window=5, show_progress=False)
        if snr
        else dict(baseline_filter_size=5, n_jobs=1)
    )
    expected = function(data, 100.0, feature_block_size=2, **kwargs)
    events = []
    actual = function(
        data,
        100.0,
        feature_block_size=2,
        progress_callback=lambda value, message: events.append(value),
        **kwargs,
    )
    pd.testing.assert_frame_equal(expected["cell_df"], actual["cell_df"])
    assert events == [0.0, 2 / 3, 1.0]

    def cancel(value, message):
        if value > 0:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        function(data, 100.0, feature_block_size=2, progress_callback=cancel, **kwargs)


@pytest.mark.parametrize("snr", [False, True])
@pytest.mark.parametrize("full", [False, True])
def test_debug_baseline_is_opt_out_for_compatibility(snr, full):
    values = np.ones((31, 2))
    values[8] = 20
    events = []
    CyESIData._from_raw_state(
        DatasetState(
            pd.DataFrame(values, columns=[100.0, 200.0]),
            pd.DataFrame({"rt": np.arange(31) * 2}),
            {"name": "test"},
            100.0,
        ),
        dict(
            extraction_method="snr_v1" if snr else "legacy",
            baseline_filter_size=5,
            noise_window=5,
            n_jobs=1,
            debug_hook=lambda event, payload: events.append(payload),
            **({} if full else {"debug_full_baseline": False}),
        ),
    )
    assert (events[0]["baseline"] is not None) == full
    assert events[0]["frame_obs"].rt.iloc[8] == 16
    assert events[0]["cell_idx"].tolist() == [8]


@pytest.mark.parametrize(
    "method,mode", [("legacy", "union"), ("snr_v1", "union"), ("snr_v1", "intersection")]
)
def test_cached_preview_matches_real_file_processing(tmp_path, monkeypatch, method, mode):
    spectra = []
    mz = np.array([149.8, 149.9, 150.0, 150.1, 150.2, 199.8, 199.9, 200.0, 200.1, 200.2])
    for i in range(31):
        signal = 20.0 if i in {8, 22} else 1.0
        second = 20.0 if i in {8, 25} else 1.0
        spec = oms.MSSpectrum()
        spec.setMSLevel(1)
        spec.setRT(float(i * 2))
        spec.set_peaks((mz, np.array([0, 0, signal, 0, 0, 0, 0, second, 0, 0])))
        spectra.append(spec)
    path = save_spectra(spectra, tmp_path / "synthetic.mzML")
    params = ProcessingParameters(
        ref_mz=150.0,
        resolution=5000.0,
        resample_points_per_fwhm=2.0,
        ppm_tol=500.0,
        baseline_filter_size=5,
    )
    options = dict(
        extraction_method=method,
        reference_mode=mode,
        reference_ppm_tol=500.0,
        reference_mz=[150.0, 200.0] if method == "snr_v1" else None,
        noise_window=5,
    )
    actual = CyESIData.load_from_file(path, params.ref_mz, **params.load_kwargs(), **options)
    preview = RawPreviewService(StorageCatalog([StorageRoot("Raw", tmp_path)])).open(
        "Raw",
        path,
    )
    metadata_before = dict(preview.metadata)
    peaks_before = [s.get_peaks() for s in preview.experiment]

    def no_reload(*args, **kwargs):
        raise AssertionError("preview must reuse its loaded experiment")

    monkeypatch.setattr("scMM.application.raw_preview.load_single_file", no_reload)
    monkeypatch.setattr("scMM.file._dataset_loading.load_single_file", no_reload)
    result = preview.cell_detection(params, **options)
    again = preview.cell_detection(params, **options)
    assert result.cell_count == len(actual.data)
    np.testing.assert_array_equal(
        result.traces.loc[result.traces.cell_apex, "rt_seconds"],
        actual.peak_meta.rt,
    )
    assert result.traces.rt_seconds.tolist() == list(np.arange(31) * 2)
    pd.testing.assert_frame_equal(result.traces, again.traces)
    assert preview.metadata == metadata_before
    for before, spectrum in zip(peaks_before, preview.experiment, strict=True):
        for expected, values in zip(before, spectrum.get_peaks(), strict=True):
            np.testing.assert_array_equal(expected, values)
