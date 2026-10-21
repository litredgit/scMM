"""Raw diagnostic selection preserves axis order and closes bounded readers."""

from types import SimpleNamespace

import numpy as np
import pytest

from scMM.application.raw_diagnostics import diagnostic_input
from scMM.file.readers.base import Spectrum


def selection(source, **options):
    return diagnostic_input(
        SimpleNamespace(experiment=source),
        **{
            "signal": "eic",
            "references": [151.0, 150.0],
            "ppm": 10.0,
            "ms_level": 1,
            "rt_range": None,
            **options,
        },
    )


def test_selection_preserves_requested_channels_and_original_scan_ids():
    source = [
        Spectrum(
            i, float(i), np.array([150.0, 151.0]), np.array([2.0, 3.0]), ms_level=2 if i == 1 else 1
        )
        for i in range(4)
    ]
    values, indices, times, channels = selection(source, rt_range=[1.0, 3.0])
    np.testing.assert_array_equal(values, [[3.0, 2.0], [3.0, 2.0]])
    assert indices == [2, 3] and times == [2.0, 3.0]
    assert channels == ["EIC 151.0", "EIC 150.0"]


def test_oversized_scan_selection_closes_generator_without_truncation():
    closed = []

    def scans():
        try:
            for index in range(20001):
                yield Spectrum(index, float(index), np.array([150.0]), np.array([1.0]))
        finally:
            closed.append(True)

    with pytest.raises(ValueError, match="20000"):
        selection(scans(), signal="tic", references=[])
    assert closed == [True]


def test_nonfinite_raw_and_reference_conflicts_reject():
    source = [Spectrum(0, 0.0, np.array([150.0]), np.array([np.nan]))]
    with pytest.raises(ValueError):
        selection(source)
    with pytest.raises(ValueError):
        selection([], references=[150.0, 150.0])
    with pytest.raises(ValueError):
        selection([], signal="tic")
