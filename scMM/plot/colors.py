"""Palettes and numeric transformations shared by interactive views."""

import numpy as np
from plotly.colors import qualitative

from .presentation import PLOT_COLORS

CONTINUOUS_SCALES = ("Viridis", "Cividis", "Plasma", "Inferno", "Turbo", "RdBu", "PuOr")
PALETTES = {
    "scMM": PLOT_COLORS,
    "Plotly": qualitative.Plotly,
    "Safe": qualitative.Safe,
    "Dark24": qualitative.Dark24,
}


def color_values(values, transform="linear", linthresh=1.0):
    """Calculate display coordinates while retaining the caller's raw values."""
    values = np.asarray(values, dtype=float)
    display = np.full(values.shape, np.nan)
    valid = np.isfinite(values)
    if transform == "linear":
        display[valid] = values[valid]
    elif transform == "log1p":
        valid &= values >= 0
        display[valid] = np.log1p(values[valid])
    elif transform == "symlog" and np.isfinite(linthresh) and linthresh > 0:
        selected = values[valid]
        with np.errstate(divide="ignore"):
            magnitude = np.logaddexp(0, np.log(np.abs(selected)) - np.log(linthresh))
        display[valid] = np.sign(selected) * magnitude / np.log(10)
    else:
        raise ValueError("Invalid color transformation or symmetric log threshold")
    return display


def color_title(label, transform):
    return f"{label} ({transform})" if transform != "linear" else label
