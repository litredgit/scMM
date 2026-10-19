"""Raw preview plots and display-only downsampling."""

# ruff: noqa: RUF001
import numpy as np
import pandas as pd
from plotly.subplots import make_subplots

from .presentation import style_figure


def cell_detection_figure(result):
    """Render full cell windows with linear shape construction and unchanged traces."""
    frame = result.traces
    has_net = "net_0" in frame
    figure = make_subplots(
        rows=2 if has_net else 1,
        cols=1,
        shared_xaxes=True,
        subplot_titles=["参考信号与细胞窗口", "净信号与判定门槛"] if has_net else None,
    )
    peaks = frame.loc[frame.cell_apex]
    for i, mass in enumerate(result.reference_mz):
        display = _peak_preserving_downsample(frame, 30_000, f"reference_{i}")
        figure.add_scattergl(
            x=display.rt_seconds,
            y=display[f"reference_{i}"],
            name=f"m/z {mass:.4f}",
            mode="lines",
            row=1,
            col=1,
        )
        figure.add_scatter(
            x=peaks.rt_seconds,
            y=peaks[f"reference_{i}"],
            mode="markers",
            name=f"峰顶 {mass:.4f}",
            text=[f"细胞 {index + 1}" for index in range(len(peaks))],
            row=1,
            col=1,
        )
        if has_net:
            figure.add_scattergl(
                x=display.rt_seconds,
                y=display[f"net_{i}"],
                name=f"净信号 {mass:.4f}",
                mode="lines",
                row=2,
                col=1,
            )
            figure.add_scattergl(
                x=display.rt_seconds,
                y=display[f"threshold_{i}"],
                name=f"门槛 {mass:.4f}",
                line={"dash": "dash"},
                mode="lines",
                row=2,
                col=1,
            )
    times = frame.rt_seconds.to_numpy()
    figure.update_layout(
        title="细胞窗口与参考峰顶",
        xaxis_title="RT（秒）",
        yaxis_title="强度",
        meta={
            "reference_mz": list(result.reference_mz),
            "window_ranges": result.window_ranges,
            "export_tables": {"traces": frame.to_csv(index=False)},
        },
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
    if has_net:
        figure.update_yaxes(title_text="净强度", row=2, col=1)
        figure.update_xaxes(title_text="时间（秒）", row=2, col=1)
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
