"""Boundary behavior for automatic ranges and annotation display sorting."""

import math

import pytest

from scMM.application.lipid_sorting import sorted_rows
from scMM.application.parameters import automatic_mz_range


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ((123, 987), [100, 1000]),
        ((126, 974), [150, 950]),
        ((125, 975), [150, 1000]),
        ((140, 160), [100, 200]),
        ((150, 160), [150, 200]),
        ((140, 150), [100, 150]),
        ((100, 200), [100, 200]),
    ],
)
def test_nearest_range_ties_and_collapsed_bounds(bounds, expected):
    assert automatic_mz_range(*bounds) == expected


@pytest.mark.parametrize("bounds", [(math.nan, 100), (100, math.inf), (100, 100), (101, 100)])
def test_invalid_measured_ranges_are_rejected(bounds):
    with pytest.raises(ValueError):
        automatic_mz_range(*bounds)


def test_sorting_missing_last_and_absolute_errors_preserves_input():
    rows = [{"ppm_error": None}, {"ppm_error": -3.0}, {"ppm_error": 1.0}, {"ppm_error": math.nan}]
    assert sorted_rows(rows, "abs_ppm_error") == [rows[2], rows[1], rows[0], rows[3]]
    assert sorted_rows(rows, "abs_ppm_error", True) == [rows[1], rows[2], rows[0], rows[3]]
    assert rows[0]["ppm_error"] is None and rows[1]["ppm_error"] == -3
