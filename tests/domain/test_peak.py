import numpy as np
import pandas as pd
import pyopenms as oms
import pytest

from scMM.util.peak import filter_spectrum


def test_custom_detector_uses_default_snr_quantifier():
    from scMM.util._cell_snr import find_cell_peaks_snr

    frame = pd.DataFrame({100.0: [1.0, 1.0, 50.0, 1.0, 1.0]})
    result = find_cell_peaks_snr(
        frame,
        100.0,
        detector=lambda _: [(2, 2, 2)],
        baseline_window=3,
        noise_window=2,
        show_progress=False,
    )
    assert result["cell_df"].iloc[0, 0] == 49.0
    assert result["feature_snr"][0, 0] > 3


def make_spectrum(intensity: list[float]) -> oms.MSSpectrum:
    spectrum = oms.MSSpectrum()
    spectrum.setMSLevel(1)
    spectrum.setRT(12.5)
    spectrum.setName("synthetic")
    spectrum.set_peaks(
        (
            np.arange(100.0, 100.0 + len(intensity)),
            np.asarray(intensity, dtype=np.float32),
        )
    )
    return spectrum


def test_filter_spectrum_preserves_identity_and_returns_snr() -> None:
    spectrum = make_spectrum([1.0, 1.0, 10.0, 1.0, 1.0])

    filtered, snr = filter_spectrum(
        spectrum,
        baseline_window=3,
        noise_window=3,
        baseline_stride=1,
        snr_threshold=3.0,
        return_snr=True,
    )

    _, intensity = filtered.get_peaks()
    np.testing.assert_allclose(intensity, [0.0, 0.0, 9.0, 0.0, 0.0])
    assert snr[2] > 3.0
    assert filtered.getRT() == 12.5
    assert filtered.getMSLevel() == 1
    assert filtered.getName() == "synthetic"


def test_filter_spectrum_handles_empty_input() -> None:
    spectrum = make_spectrum([])

    filtered, snr = filter_spectrum(spectrum, return_snr=True)

    assert filtered.size() == 0
    assert snr.size == 0
    assert filtered.getRT() == 12.5


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"baseline_quantile": 1.1}, "baseline_quantile"),
        ({"snr_threshold": -1.0}, "snr_threshold"),
    ],
)
def test_filter_spectrum_validates_thresholds(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        filter_spectrum(make_spectrum([1.0, 2.0, 1.0]), **kwargs)
