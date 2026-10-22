"""Shared numerical display formatting without a web framework dependency."""

# ruff: noqa: RUF001
import math
from pathlib import PureWindowsPath

import numpy as np
import pandas as pd


def ordinary_number(value):
    number = float(value)
    if 0 < abs(number) < 0.001:
        # Keep small nonzero values visible without scientific notation.
        return np.format_float_positional(
            number, precision=3, unique=False, fractional=False, trim="-"
        )
    return np.format_float_positional(number, precision=3, unique=False, trim="-")


def count_number(value):
    return np.format_float_positional(float(value), precision=1, unique=False, trim="-")


def probability_number(value):
    number = float(value)
    if not math.isfinite(number):
        return "—"
    return "0" if number == 0 else f"{number:.2e}"


def mass_label(value):
    try:
        return f"{float(value):.4f}"
    except (ValueError, TypeError):
        return str(value)


def feature_label(identity, mz=None):
    try:
        return (
            mass_label(mz) if mz is not None and math.isfinite(float(mz)) else mass_label(identity)
        )
    except (ValueError, TypeError):
        return mass_label(identity)


def qc_file_table(frame):
    """Build a display copy; sample identity and numerical precision stay intact."""
    rows, paths = [], []
    for source, values in frame.iterrows():
        references = [
            float(str(metric).removeprefix("reference_intensity_"))
            for metric in frame.columns.get_level_values(0).unique()
            if str(metric).startswith("reference_intensity_") and values[metric]["count"] > 0
        ]
        reference_text = ", ".join(mass_label(mz) for mz in references) or "—"
        cell_count = int(values["total_intensity"]["count"])
        for metric in frame.columns.get_level_values(0).unique():
            stats = values[metric]
            reference = str(metric).startswith("reference_intensity_")
            if reference and stats["count"] == 0:
                continue
            label = {"total_intensity": "总强度", "detected_features": "检出特征数"}.get(
                metric, metric
            )
            if reference:
                mz = float(str(metric).removeprefix("reference_intensity_"))
                label = f"参考强度（m/z {mass_label(mz)}）"
            rows.append(
                {
                    "source_file": PureWindowsPath(str(source)).name,
                    "reference_mz": reference_text,
                    "cell_count": cell_count,
                    "metric": label,
                    **{key: stats[key] for key in ("mean", "median", "std", "min", "max")},
                }
            )
            paths.append(str(source))
    result = pd.DataFrame(
        rows,
        columns=[
            "source_file",
            "reference_mz",
            "cell_count",
            "metric",
            "mean",
            "median",
            "std",
            "min",
            "max",
        ],
    )
    result.attrs["source_paths"] = paths
    return result


PLOT_COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]


def style_figure(figure):
    if figure is None or not hasattr(figure, "update_layout"):
        return figure
    figure.update_layout(
        colorway=PLOT_COLORS,
        font={"family": "Arial, Helvetica, sans-serif", "size": 13, "color": "#111111"},
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="closest",
    )
    figure.update_xaxes(showspikes=False, showgrid=False, zeroline=False, showline=True)
    figure.update_yaxes(showspikes=False, showgrid=False, zeroline=False, showline=True)
    for axis_name in figure.layout:
        if axis_name.startswith(("xaxis", "yaxis")):
            axis = figure.layout[axis_name]
            title = (axis.title.text or "").lower()
            if any(word in title for word in ("intensity", "强度", "abundance")):
                axis.tickformat = axis.hoverformat = ".1e"
            elif "m/z" in title or title == "mz":
                axis.tickformat = axis.hoverformat = ".4f"
            elif any(word in title for word in ("features", "cells", "特征数", "细胞数")):
                axis.tickformat = axis.hoverformat = "d"
            else:
                axis.tickformat = axis.hoverformat = ".3~f"
    return figure
