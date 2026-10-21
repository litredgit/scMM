"""Numeric identities and read-only semantics for independent raw tools."""

import numpy as np
import pandas as pd
import pytest
from scipy.ndimage import median_filter

from scMM.analysis.signal_diagnostics import diagnostic_figure, signal_diagnostics
from scMM.util.denoise import peak_recon, r1_decomposition


def test_existing_tools_match_and_identities_hold():
    signal = np.outer(np.array([1.0, 2.0, 7.0, 3.0, 1.0]), [2.0, 4.0])
    before = signal.copy()
    output = signal_diagnostics(signal, baseline="median", window=3)
    baseline = median_filter(signal, size=(3, 1), mode="reflect")
    expected, sigma = peak_recon(signal, baseline, n_jobs=1)
    a, b = r1_decomposition(signal - baseline)
    np.testing.assert_array_equal(signal, before)
    np.testing.assert_allclose(output["peaks"], expected)
    np.testing.assert_allclose(output["noise"], sigma)
    np.testing.assert_allclose(output["rank_one"], a @ b.T)
    np.testing.assert_allclose(output["reconstructed"] + output["residual"], signal)
    np.testing.assert_allclose(output["rank_one"] + output["rank_residual"], signal - baseline)
    assert (output["peaks"] >= 0).all()
    figure, frame = diagnostic_figure(
        output,
        range(5),
        [0.0, 0.1, 0.2, 0.6, 0.9],
        ["one", "two"],
        provenance={"source": "synthetic"},
    )
    assert len(frame) == 10
    exports = figure.layout.meta["export_tables"]
    from io import StringIO

    pd.testing.assert_frame_equal(
        pd.read_csv(StringIO(exports["diagnostic.csv"])), frame, check_dtype=False
    )
    assert figure.layout.meta["parameters"]["n_jobs"] == 1


def test_zero_constant_signed_and_single_channel():
    for signal in [
        np.zeros((5, 1)),
        np.full((5, 2), 4.0),
        np.array([[-1.0, 1.0], [2.0, -2.0], [0.0, 0.0]]),
    ]:
        output = signal_diagnostics(signal, baseline="zero")
        assert np.isfinite(output["rank_one"]).all()
        assert (output["noise"] >= 0.001).all()
        np.testing.assert_allclose(output["residual"] + output["reconstructed"], signal)


@pytest.mark.parametrize(
    "signal,options",
    [
        (np.ones((1, 2)), {"baseline": "zero"}),
        (np.ones((3, 9)), {"baseline": "zero"}),
        (np.ones((3, 2)), {"baseline": ""}),
        (np.ones((3, 2)), {"baseline": "median"}),
        (np.ones((3, 2)), {"baseline": "median", "window": 4}),
        (np.ones((3, 2)), {"baseline": "zero", "window": 3}),
        (np.array([[np.nan], [1.0]]), {"baseline": "zero"}),
        (np.ones((3, 2)), {"baseline": "zero", "lam": -1}),
        (np.ones((3, 2)), {"baseline": "zero", "tau": True}),
        (np.ones((3, 2)), {"baseline": "zero", "max_iter": 0}),
        (np.full((3, 2), 1e100), {"baseline": "zero"}),
    ],
)
def test_invalid_inputs_do_not_mutate(signal, options):
    before = signal.copy()
    with pytest.raises(ValueError):
        signal_diagnostics(signal, **options)
    np.testing.assert_array_equal(signal, before)


def test_closed_form_positive_part_and_constant_baseline():
    signal = np.array([[0.0, -2.0], [3.0, 4.0], [2.0, 1.0]])
    output = signal_diagnostics(signal, baseline="zero", lam=0, tau=0, max_iter=1)
    np.testing.assert_array_equal(output["peaks"], np.maximum(signal, 0))
    np.testing.assert_array_equal(output["residual"], np.minimum(signal, 0))
    output = signal_diagnostics(np.full((5, 2), 4.0), baseline="median", window=3)
    np.testing.assert_array_equal(output["baseline"], 4.0)
    np.testing.assert_array_equal(output["peaks"], 0.0)
    np.testing.assert_array_equal(output["noise"], 0.001)


def test_nonnegative_rank_one_exact_reconstruction():
    signal = np.outer([1.0, 3.0, 5.0, 2.0], [2.0, 4.0])
    result = signal_diagnostics(signal, baseline="zero")
    np.testing.assert_allclose(result["rank_one"], signal, rtol=1e-6)


def test_numeric_overflow_is_clear_validation_failure():
    with pytest.raises(ValueError, match="数值溢出"):
        signal_diagnostics(np.ones((3, 2)), baseline="zero", lam=1e308, sigma_min=1e70)
