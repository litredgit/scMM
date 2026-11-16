"""Spectrum denoising and cell-event peak extraction."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

import numpy as np
import pyopenms as oms
from scipy.ndimage import median_filter


@dataclass(frozen=True)
class _SpectrumFilterConfig:
    baseline_window: int
    noise_window: int
    baseline_quantile: float
    snr_threshold: float
    keep_negative: bool
    baseline_stride: int


def filter_spectrum(
    spec: oms.MSSpectrum,
    baseline_window: int = 101,
    noise_window: int = 101,
    baseline_quantile: float = 0.1,
    snr_threshold: float = 3.0,
    keep_negative: bool = False,
    return_snr: bool = False,
    baseline_stride: int = 10,
):
    """Remove a local quantile baseline and suppress low-SNR intensities."""
    config = _spectrum_filter_config(
        baseline_window,
        noise_window,
        baseline_quantile,
        snr_threshold,
        keep_negative,
        baseline_stride,
    )
    mz, intensity = (np.asarray(array, dtype=np.float64) for array in spec.get_peaks())
    if intensity.size == 0:
        output = _new_spectrum(spec, mz, intensity, copy_optional_metadata=False)
        return (output, np.array([], dtype=np.float64)) if return_snr else output

    baseline = _local_quantile_baseline(
        intensity,
        config.baseline_window,
        config.baseline_quantile,
        config.baseline_stride,
    )
    signal = intensity - baseline
    noise = _local_mad_noise(signal, config.noise_window)
    if not config.keep_negative:
        signal[signal < 0] = 0.0
    snr = signal / noise
    filtered = signal.copy()
    filtered[snr < config.snr_threshold] = 0.0
    output = _new_spectrum(spec, mz, filtered, copy_optional_metadata=True)
    return (output, snr) if return_snr else output


def _spectrum_filter_config(
    baseline_window,
    noise_window,
    baseline_quantile,
    snr_threshold,
    keep_negative,
    baseline_stride,
) -> _SpectrumFilterConfig:
    if not 0 <= baseline_quantile <= 1:
        raise ValueError("baseline_quantile must be between 0 and 1")
    if snr_threshold < 0:
        raise ValueError("snr_threshold must be non-negative")
    return _SpectrumFilterConfig(
        baseline_window=_odd_window(baseline_window),
        noise_window=_odd_window(noise_window),
        baseline_quantile=baseline_quantile,
        snr_threshold=snr_threshold,
        keep_negative=keep_negative,
        baseline_stride=max(1, int(baseline_stride)),
    )


def _odd_window(value: int) -> int:
    value = max(1, int(value))
    return value if value % 2 == 1 else value + 1


def _local_quantile_baseline(
    intensity: np.ndarray,
    window: int,
    quantile: float,
    stride: int,
) -> np.ndarray:
    if stride == 1:
        return _quantiles_at_indices(intensity, np.arange(len(intensity)), window, quantile)
    anchors = np.arange(0, len(intensity), stride, dtype=np.int64)
    if anchors[-1] != len(intensity) - 1:
        anchors = np.append(anchors, len(intensity) - 1)
    anchor_values = _quantiles_at_indices(intensity, anchors, window, quantile)
    return np.interp(np.arange(len(intensity), dtype=float), anchors.astype(float), anchor_values)


def _quantiles_at_indices(
    values: np.ndarray,
    indices: np.ndarray,
    window: int,
    quantile: float,
) -> np.ndarray:
    half_window = window // 2
    result = np.empty(len(indices), dtype=np.float64)
    for output_index, value_index in enumerate(indices):
        left = max(0, value_index - half_window)
        right = min(len(values), value_index + half_window + 1)
        result[output_index] = np.quantile(values[left:right], quantile)
    return result


def _local_mad_noise(residual: np.ndarray, window: int) -> np.ndarray:
    half_window = window // 2
    noise = np.empty(len(residual), dtype=np.float64)
    for index in range(len(residual)):
        local = residual[max(0, index - half_window) : min(len(residual), index + half_window + 1)]
        median = np.median(local)
        mad = np.median(np.abs(local - median))
        noise[index] = max(1.4826 * mad, 1e-12)
    return noise


def _new_spectrum(
    source: oms.MSSpectrum,
    mz: np.ndarray,
    intensity: np.ndarray,
    *,
    copy_optional_metadata: bool,
) -> oms.MSSpectrum:
    output = oms.MSSpectrum()
    output.set_peaks((mz, intensity))
    output.setRT(source.getRT())
    output.setMSLevel(source.getMSLevel())
    if copy_optional_metadata:
        with suppress(Exception):
            output.setName(source.getName())
        with suppress(Exception):
            output.setDriftTime(source.getDriftTime())
    return output


def _filter(data: np.ndarray, size: int = 10, filter=median_filter, **filter_kwargs):
    """Apply a 1D frame-axis filter independently to every feature."""
    return filter(data, size=(size, 1), **filter_kwargs)
