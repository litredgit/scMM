"""Raw preview plots and display-only downsampling."""

# ruff: noqa: RUF001
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .presentation import style_figure


def cell_detection_figure(result):
    """Render full cell windows with linear shape construction and unchanged traces."""
    frame = result.traces
    figure = go.Figure()
    peaks = frame.loc[frame.cell_apex]
    for i, mass in enumerate(result.reference_mz):
        display = _peak_preserving_downsample(frame, 30_000, f"reference_{i}")
        figure.add_scattergl(
            x=display.rt_seconds,
            y=display[f"reference_{i}"],
            name=f"m/z {mass:.4f}",
            mode="lines",
        )
        figure.add_scatter(
            x=peaks.rt_seconds,
            y=peaks[f"reference_{i}"],
            mode="markers",
            name=f"峰顶 {mass:.4f}",
        )
    times = frame.rt_seconds.to_numpy()
    figure.update_layout(
        title="细胞窗口与参考峰顶",
        xaxis_title="RT（秒）",
        yaxis_title="强度",
        shapes=[
            dict(
                type="rect",
                xref="x",
                yref="y domain",
                x0=times[start],
                x1=times[stop],
                y0=0,
                y1=1,
                fillcolor="green",
                opacity=0.12,
                line_width=0,
            )
            for start, stop in result.window_ranges
        ],
    )
    return style_figure(figure)


def _peak_preserving_downsample(
    frame: pd.DataFrame,
    max_points: int,
    intensity_column: str,
) -> pd.DataFrame:
    if len(frame) <= max_points:
        return frame
    groups = np.arange(len(frame)) * max_points // len(frame)
    positions = frame.groupby(groups, sort=True)[intensity_column].idxmax()
    return frame.loc[positions].sort_index()
