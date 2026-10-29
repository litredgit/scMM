"""Read-only comparison of the existing rank-one and sparse-peak utilities."""

# ruff: noqa: RUF001

import numpy as np
import pandas as pd
from scipy.ndimage import median_filter

from scMM.util.denoise import peak_recon, r1_decomposition

from .preprocessing import integer, real


def signal_diagnostics(
    signal,
    *,
    baseline,
    window=None,
    lam=0.5,
    tau=2.0,
    sigma_min=1e-3,
    max_iter=50,
    rank_tol=1e-6,
    rank_max_iter=100,
):
    signal = np.asarray(signal, dtype=np.float64)
    if signal.ndim != 2 or not 2 <= signal.shape[0] <= 20000 or not 1 <= signal.shape[1] <= 8:
        raise ValueError("诊断需要 2–20000 个扫描、1–8 个通道；请缩小 RT 范围。")
    if not np.isfinite(signal).all():
        raise ValueError("诊断信号必须全部有限。")
    if not isinstance(baseline, str) or baseline not in {"zero", "median"}:
        raise ValueError("请明确选择零基线或逐通道扫描中位基线。")
    if baseline == "median":
        window = integer("window", window, 3, min(1001, len(signal)))
        if window % 2 == 0:
            raise ValueError("中位基线窗口须为奇数扫描数。")
    elif window is not None:
        raise ValueError("零基线不使用窗口。")
    lam, tau = real("lam", lam, inclusive=True), real("tau", tau, inclusive=True)
    sigma_min = real("sigma_min", sigma_min)
    rank_tol = real("rank_tol", rank_tol)
    max_iter = integer("max_iter", max_iter, 1, 1000)
    rank_max_iter = integer("rank_max_iter", rank_max_iter, 1, 1000)
    # Use original intensity units. Bound squares/sums used by the legacy routines.
    if max(float(np.max(np.abs(signal))), sigma_min) > 1e70:
        raise ValueError("信号或噪声下限过大，无法安全计算现有重构公式。")
    background = (
        np.zeros_like(signal)
        if baseline == "zero"
        else median_filter(signal, size=(window, 1), mode="reflect")
    )
    corrected = signal - background
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            peaks, noise = peak_recon(
                signal,
                background,
                lam=lam,
                tau=tau,
                sigma_min=sigma_min,
                max_iter=max_iter,
                n_jobs=1,
                dtype=np.float64,
            )
            a, b = r1_decomposition(
                corrected, tol=rank_tol, max_iter=rank_max_iter, dtype=np.float64
            )
            rank_one = a @ b.T
            residual = corrected - peaks
            rank_residual = corrected - rank_one
    except FloatingPointError as exc:
        raise ValueError("诊断参数导致数值溢出，请调整输入或重构参数。") from exc
    for values in (background, peaks, noise, rank_one, residual, rank_residual):
        if not np.isfinite(values).all():
            raise ValueError("重构产生非有限数值，请调整诊断输入和参数。")
    return {
        "signal": signal.copy(),
        "baseline": background,
        "corrected": corrected,
        "peaks": peaks,
        "reconstructed": background + peaks,
        "residual": residual,
        "rank_one": rank_one,
        "rank_residual": rank_residual,
        "noise": noise,
        "parameters": {
            "baseline": baseline,
            "window": window,
            "lam": lam,
            "tau": tau,
            "sigma_min": sigma_min,
            "max_iter": max_iter,
            "rank_tol": rank_tol,
            "rank_max_iter": rank_max_iter,
            "n_jobs": 1,
            "peak_tol": 1e-4,
            "rank_initialization": "ones",
            "dtype": "float64",
            "median_edge_mode": "reflect" if baseline == "median" else None,
        },
    }


def diagnostic_figure(result, scan_index, times, channels, *, provenance):
    from plotly.subplots import make_subplots

    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=(
            "Raw signals, baselines and reconstruction",
            "Baseline-corrected signals and rank-one approximation",
            "Peak reconstruction residuals and channel noise",
        ),
    )
    tables, summaries = [], []
    for index, channel in enumerate(channels):
        frame = pd.DataFrame(
            {
                "scan_index": scan_index,
                "rt_seconds": times,
                "channel": channel,
                **{
                    key: result[key][:, index]
                    for key in (
                        "signal",
                        "baseline",
                        "corrected",
                        "peaks",
                        "reconstructed",
                        "residual",
                        "rank_one",
                        "rank_residual",
                    )
                },
                "estimated_sigma": result["noise"][index],
            }
        )
        tables.append(frame)
        summaries.append(
            {
                "channel": channel,
                "estimated_sigma": float(result["noise"][index]),
                "residual_std_ddof0": float(np.std(frame.residual)),
                "rank_residual_rmse": float(np.sqrt(np.mean(frame.rank_residual**2))),
            }
        )
        # Plot all bounded input scans; the export retains all original values.
        for row, keys in (
            (1, ("signal", "baseline", "reconstructed")),
            (2, ("corrected", "rank_one")),
            (3, ("residual", "estimated_sigma")),
        ):
            for key in keys:
                figure.add_scattergl(
                    x=times, y=frame[key], mode="lines", row=row, col=1, name=f"{channel} · {key}"
                )
    full = pd.concat(tables, ignore_index=True)
    summary = pd.DataFrame(summaries)
    figure.update_layout(
        height=900,
        title="Independent raw signal diagnostics",
        meta={
            "parameters": result["parameters"],
            "provenance": provenance,
            "sample_id": provenance.get("sample_id"),
            "input_identity": provenance.get("input_identity"),
            "definitions": {
                "rank_one": "Existing alternating rank-one approximation of S-B; not an SVD or global-optimum certificate; one channel is trivial.",
                "residual": "S-B-C; reconstructed=B+C; rank_residual=S-B-a@b.T",
                "estimated_sigma": "Existing peak_recon per-channel iterative noise estimate, not extraction SNR, blank control or confidence interval.",
                "residual_std_ddof0": "Empirical population standard deviation of S-B-C; distinct from estimated_sigma.",
                "scan_axis": "Input scan order; RT seconds retained, not resampled to an equal time grid.",
            },
            "export_tables": {
                "diagnostic.csv": full.to_csv(index=False),
                "noise.csv": summary.to_csv(index=False),
            },
        },
    )
    figure.update_xaxes(title_text="RT (s; computed in scan order)", row=3, col=1)
    return figure, full
