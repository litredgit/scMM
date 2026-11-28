"""Alignment of centroided spectrum peaks to a shared target m/z axis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyopenms as oms

from ._spectrum import extract_peaks
from .readers.base import spectrum_iterator


def align_frame(
    exp: oms.MSExperiment,
    mz_list,
    ppm: float = 10.0,
    ms_level: int = 1,
    aggregate: str = "max",
    dtype=None,
    out=None,
    rt_range=None,
    frame_range=None,
    reference=None,
    **kwargs,
):
    """Align scan peaks, optionally returning a separately matched reference frame."""
    _validate_alignment_options(ppm, aggregate)
    targets = np.asarray(mz_list, dtype=np.float64)
    if targets.ndim != 1 or targets.size == 0:
        raise ValueError("mz_list must be a non-empty 1D array-like.")
    sorted_targets, restore_order = _sorted_targets(targets)
    original_columns = np.argsort(restore_order)
    peak_dtype = np.float64 if dtype is None else dtype
    if out is not None and (
        not isinstance(out, np.ndarray)
        or out.dtype not in (np.dtype("float32"), np.dtype("float64"))
    ):
        raise TypeError("out must be a float32 or float64 numpy array")
    dtype = np.dtype(
        out.dtype if dtype is None and out is not None else np.float64 if dtype is None else dtype
    )
    if dtype not in (np.dtype("float32"), np.dtype("float64")):
        raise TypeError("dtype must be float32 or float64")
    if out is not None:
        if out.dtype != dtype:
            raise TypeError("out and dtype must agree")
        if out.ndim != 2 or out.shape[1] != len(targets) or not out.flags.writeable:
            raise ValueError("out must be writable with shape (selected scans, targets)")
    frame_ids, retention_times = [], []
    reference_targets = np.unique(reference[0]) if reference is not None else np.empty(0)
    width = len(targets) + len(reference_targets)
    buffer_size = len(out) if out is not None else 256
    block = np.empty((buffer_size, width), dtype=dtype)
    blocks = []
    peak_options = _peak_options(kwargs)
    from .selection import selected_frames

    with spectrum_iterator(
        selected_frames(exp, ms_level=ms_level, rt_range=rt_range, frame_range=frame_range)
    ) as spectra:
        for frame_id, spectrum in spectra:
            row_index = len(frame_ids)
            if out is not None and row_index >= buffer_size:
                raise ValueError("out must match the number of selected scans")
            slot = row_index % buffer_size
            if slot == 0 and row_index:
                blocks.append(block)
                block = np.empty_like(block)
            combined = block[slot]
            combined.fill(0)
            row = combined[: len(targets)]
            reference_row = combined[len(targets) :]
            mz, intensity = extract_peaks(spectrum, dtype=peak_dtype, **peak_options)
            if mz.size:
                mz, intensity = _sort_extracted_peaks(mz, intensity)
                target_indices, matched_intensity = _match_target_peaks(
                    sorted_targets,
                    mz,
                    intensity,
                    ppm,
                )
                _aggregate_target_intensity(
                    row, original_columns[target_indices], matched_intensity, aggregate
                )
                if reference is not None:
                    indices, values = _match_target_peaks(
                        reference_targets, mz, intensity, reference[1]
                    )
                    _aggregate_target_intensity(reference_row, indices, values, aggregate)
            frame_ids.append(frame_id)
            retention_times.append(spectrum.getRT())
            del spectrum
    if not frame_ids:
        raise ValueError("No spectra found.")
    used = (len(frame_ids) - 1) % buffer_size + 1
    if out is not None and len(out) != len(frame_ids):
        raise ValueError("out must match the number of selected scans")
    if blocks:
        aligned = np.concatenate([*blocks, block[:used]])
    else:
        aligned = block[:used].copy() if used < buffer_size else block
    values = aligned[:, : len(targets)]
    if out is not None:
        out[:] = values
        values = out
    frame = pd.DataFrame(values, index=frame_ids, columns=targets, copy=False)
    frame.index.name = "frame"
    metadata = pd.DataFrame({"rt": retention_times}, index=frame_ids)
    if reference is not None:
        reference_frame = pd.DataFrame(
            aligned[:, len(targets) :], index=frame.index, columns=reference_targets, copy=False
        )
        return frame, metadata, reference_frame
    return frame, metadata


def _validate_alignment_options(ppm: float, aggregate: str) -> None:
    if ppm < 0:
        raise ValueError("ppm must be non-negative")
    if aggregate not in {"sum", "max"}:
        raise ValueError("aggregate must be 'sum' or 'max'")


def _sorted_targets(targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(targets)
    restore_order = np.empty_like(order)
    restore_order[order] = np.arange(order.size)
    return targets[order], restore_order


def _peak_options(kwargs: dict) -> dict:
    return {
        "prominence_ratio": kwargs.get("prominence_ratio"),
        "distance": kwargs.get("distance", 3),
        "method": kwargs.get("method", "centroid"),
        "resolution_200": kwargs.get("resolution_200", 70000.0),
        "window_fwhm_factor": kwargs.get("window_fwhm_factor", 1.0),
        "centroid_intensity_mode": kwargs.get("centroid_intensity_mode", "apex"),
    }


def _sort_extracted_peaks(mz, intensity) -> tuple[np.ndarray, np.ndarray]:
    mz = np.asarray(mz, dtype=np.float64)
    intensity = np.asarray(intensity, dtype=np.float64)
    if mz.size >= 2 and np.any(np.diff(mz) < 0):
        order = np.argsort(mz)
        return mz[order], intensity[order]
    return mz, intensity


def _match_target_peaks(
    targets: np.ndarray,
    mz: np.ndarray,
    intensity: np.ndarray,
    ppm: float,
) -> tuple[np.ndarray, np.ndarray]:
    positions = np.searchsorted(targets, mz)
    left_indices, right_indices = positions - 1, positions
    left_ppm = _candidate_ppm(targets, mz, left_indices)
    right_ppm = _candidate_ppm(targets, mz, right_indices)
    choose_left = left_ppm <= right_ppm
    best_indices = np.where(choose_left, left_indices, right_indices)
    best_ppm = np.where(choose_left, left_ppm, right_ppm)
    matched = (best_indices >= 0) & (best_indices < len(targets)) & (best_ppm <= ppm)
    return best_indices[matched], intensity[matched]


def _candidate_ppm(targets: np.ndarray, mz: np.ndarray, indices: np.ndarray) -> np.ndarray:
    valid = (indices >= 0) & (indices < len(targets))
    errors = np.full(mz.shape, np.inf, dtype=np.float64)
    if np.any(valid):
        candidate_targets = targets[indices[valid]]
        errors[valid] = np.abs(mz[valid] - candidate_targets) / candidate_targets * 1e6
    return errors


def _aggregate_target_intensity(
    output: np.ndarray,
    target_indices: np.ndarray,
    intensity: np.ndarray,
    aggregate: str,
) -> None:
    if target_indices.size == 0:
        return
    if aggregate == "sum":
        np.add.at(output, target_indices, intensity)
        return
    order = np.argsort(target_indices)
    sorted_targets, sorted_intensity = target_indices[order], intensity[order]
    unique_targets, starts = np.unique(sorted_targets, return_index=True)
    output[unique_targets] = np.maximum(
        output[unique_targets],
        np.maximum.reduceat(sorted_intensity, starts),
    )
