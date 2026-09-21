"""Opt-in baseline-corrected cell extraction; independent of legacy thresholds."""

import numpy as np
import pandas as pd
from scipy.ndimage import label, median_filter, uniform_filter1d
from tqdm.auto import tqdm

from .peak import _filter


def find_cell_peaks_snr(
    data: pd.DataFrame,
    reference_mz,
    *,
    reference_mode: str = "union",
    baseline_filter=median_filter,
    baseline_window: int = 51,
    cell_signal_threshold: float = 5.0,
    feature_snr_threshold: float = 3.0,
    noise_window: int = 51,
    max_zero_fraction: float = 0.9,
    dtype=np.float32,
    n_jobs: int = 1,
    feature_block_size: int = 256,
    return_full_baseline: bool = False,
    show_progress: bool = True,
    reference_ppm_tol: float = 10.0,
    **filter_kwargs,
):
    """Extract cells using reference EICs and quantify features with true SNR.

    Cell windows are detected from one or more reference EICs using a
    signal-to-baseline ratio. reference_mode combines their masks by union or
    intersection. Feature detection is deliberately different: local noise is
    estimated from frames outside every detected cell, and a feature is retained
    in a cell only when its baseline-corrected apex divided by that noise standard
    deviation exceeds feature_snr_threshold.
    """
    del n_jobs
    if data.empty or data.shape[1] == 0:
        raise ValueError("data must be non-empty")
    if not np.isfinite(data.to_numpy()).all() or (data.to_numpy() < 0).any():
        raise ValueError("SNR extraction requires finite nonnegative intensities")
    for value in (cell_signal_threshold, feature_snr_threshold, reference_ppm_tol):
        if not np.isfinite(value) or value < 0:
            raise ValueError("thresholds must be finite and nonnegative")
    output_dtype = np.dtype(dtype)
    if output_dtype.kind != "f":
        raise TypeError("dtype must be a floating-point dtype")
    if reference_mode not in {"union", "intersection"}:
        raise ValueError("reference_mode must be 'union' or 'intersection'")
    if feature_block_size < 1 or baseline_window < 1 or noise_window < 2:
        raise ValueError("window and block sizes must be positive")
    if not 0 <= max_zero_fraction <= 1:
        raise ValueError("max_zero_fraction must be between 0 and 1")

    references = np.atleast_1d(reference_mz).astype(np.float64)
    if references.size == 0 or not np.all(np.isfinite(references) & (references > 0)):
        raise ValueError("reference_mz must contain at least one finite value")

    X = data.to_numpy(dtype=output_dtype, copy=False)
    mz_values = np.asarray(data.columns, dtype=np.float64)
    reference_indices = np.asarray(
        [int(np.abs(mz_values - value).argmin()) for value in references],
        dtype=np.int64,
    )
    errors = np.abs(mz_values[reference_indices] - references) / references * 1e6
    if np.any(errors > reference_ppm_tol):
        raise ValueError("reference m/z not detected within reference_ppm_tol")
    reference_indices = np.unique(reference_indices)
    matched_reference_mz = mz_values[reference_indices]

    reference_signal = X[:, reference_indices]
    reference_baseline = _filter(
        reference_signal,
        size=baseline_window,
        filter=baseline_filter,
        **filter_kwargs,
    )
    eps = np.finfo(output_dtype).eps
    reference_ratio = reference_signal / np.maximum(reference_baseline, eps)
    reference_masks = reference_ratio > float(cell_signal_threshold)
    cell_mask = (
        np.any(reference_masks, axis=1)
        if reference_mode == "union"
        else np.all(reference_masks, axis=1)
    )

    labeled_mask, n_cells = label(cell_mask.astype(np.int8))
    padded = np.concatenate(([False], cell_mask, [False]))
    transitions = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    stops = np.flatnonzero(transitions == -1)
    window_slices = [
        slice(int(start), int(stop)) for start, stop in zip(starts, stops, strict=True)
    ]
    if len(window_slices) != n_cells:
        raise RuntimeError("cell-window labeling produced inconsistent results")

    reference_score = np.mean(reference_ratio, axis=1)
    peak_frames = np.asarray(
        [slc.start + int(np.argmax(reference_score[slc])) for slc in window_slices],
        dtype=np.int64,
    )
    window_ranges = [(slc.start, slc.stop - 1) for slc in window_slices]

    _, n_features = X.shape
    baseline_full = np.empty_like(X) if return_full_baseline else None
    cell_matrix = np.zeros((n_cells, n_features), dtype=output_dtype)
    feature_snr = np.zeros((n_cells, n_features), dtype=output_dtype)
    background_mask = ~np.any(reference_masks, axis=1)
    non_cell = background_mask.astype(np.float64)[:, None]

    progress = tqdm(
        range(0, n_features, feature_block_size),
        total=(n_features + feature_block_size - 1) // feature_block_size,
        desc="Cell feature extraction",
        unit="block",
        disable=not show_progress,
    )
    for col_start in progress:
        col_stop = min(col_start + feature_block_size, n_features)
        X_block = X[:, col_start:col_stop]
        baseline = _filter(
            X_block,
            size=baseline_window,
            filter=baseline_filter,
            **filter_kwargs,
        )
        residual = X_block - baseline
        if baseline_full is not None:
            baseline_full[:, col_start:col_stop] = baseline

        count = (
            uniform_filter1d(non_cell, size=noise_window, axis=0, mode="constant", cval=0.0)
            * noise_window
        )
        sum_ = (
            uniform_filter1d(
                residual * non_cell,
                size=noise_window,
                axis=0,
                mode="constant",
                cval=0.0,
            )
            * noise_window
        )
        sum_sq = (
            uniform_filter1d(
                residual * residual * non_cell,
                size=noise_window,
                axis=0,
                mode="constant",
                cval=0.0,
            )
            * noise_window
        )
        mean = np.divide(sum_, count, out=np.zeros_like(sum_), where=count > 0)
        variance = (
            np.divide(sum_sq, count, out=np.zeros_like(sum_sq), where=count > 1) - mean * mean
        )
        noise = np.sqrt(np.maximum(variance, 0.0))

        background = residual[background_mask]
        if background.shape[0] > 1:
            global_noise = np.nanstd(background, axis=0, ddof=1)
        else:
            global_noise = np.nanstd(residual, axis=0)
        global_noise = np.maximum(global_noise, eps)
        noise = np.where((count > 1) & (noise > eps), noise, global_noise[None, :])

        for cell_i, slc in enumerate(window_slices):
            corrected_window = residual[slc]
            apex_local = np.argmax(corrected_window, axis=0)
            feature_index = np.arange(col_stop - col_start)
            corrected_apex = np.maximum(corrected_window[apex_local, feature_index], 0.0)
            absolute_apex = slc.start + apex_local
            local_noise = noise[absolute_apex, feature_index]
            snr = corrected_apex / np.maximum(local_noise, eps)
            detected = snr >= float(feature_snr_threshold)
            cell_matrix[cell_i, col_start:col_stop] = np.where(
                detected, corrected_apex, 0.0
            ).astype(output_dtype, copy=False)
            feature_snr[cell_i, col_start:col_stop] = snr.astype(output_dtype, copy=False)

    if n_cells:
        zero_fraction_values = np.mean(cell_matrix == 0, axis=0)
    else:
        zero_fraction_values = np.ones(n_features, dtype=np.float64)
    keep_mask = zero_fraction_values <= max_zero_fraction
    cell_df = pd.DataFrame(
        cell_matrix[:, keep_mask],
        index=pd.RangeIndex(n_cells, name="cell"),
        columns=data.columns[keep_mask],
        copy=False,
    )

    return {
        "cell_df": cell_df,
        "cell_mask": cell_mask,
        "labeled_mask": labeled_mask,
        "baseline": baseline_full,
        "reference_baseline": reference_baseline,
        "reference_signal": reference_signal,
        "reference_ratio": reference_ratio,
        "reference_indices": reference_indices,
        "reference_mz_matched": matched_reference_mz,
        "peak_frames": peak_frames,
        "window_ranges": window_ranges,
        "feature_snr": feature_snr[:, keep_mask],
        "zero_fraction": pd.Series(zero_fraction_values, index=data.columns),
        "kept_columns": pd.Series(keep_mask, index=data.columns),
    }
