"""Bounded raw scan selection for independent signal diagnostics."""
# ruff: noqa: RUF001

import numpy as np

from scMM.file.readers.base import spectrum_iterator

from .raw_preview import _selected_spectra


def diagnostic_input(preview, *, signal, references, ppm, ms_level, rt_range):
    if rt_range is not None and (
        len(rt_range) != 2 or not np.isfinite(rt_range).all() or rt_range[1] <= rt_range[0]
    ):
        raise ValueError("RT 范围须有限且递增。")
    references = np.asarray(references, dtype=np.float64)
    if signal not in {"tic", "eic"}:
        raise ValueError("请明确选择 TIC 或 EIC 信号。")
    if signal == "eic":
        if (
            references.ndim != 1
            or not 1 <= len(references) <= 8
            or not np.isfinite(references).all()
            or (references <= 0).any()
            or len(np.unique(references)) != len(references)
        ):
            raise ValueError("EIC 须明确选择 1–8 个不同的正数参考 m/z。")
        widths = references * ppm * 1e-6
        lower, upper = references - widths, references + widths
        channels = [f"EIC {v!r}" for v in references.tolist()]
    else:
        if len(references):
            raise ValueError("TIC 不使用参考离子列表。")
        channels = ["TIC"]
    values, times, indices = [], [], []
    with spectrum_iterator(_selected_spectra(preview.experiment, ms_level, rt_range)) as scans:
        for scan_index, spectrum in scans:
            if len(indices) >= 20000:
                raise ValueError("诊断最多 20000 个扫描，请缩小 RT 范围。")
            mz, intensity = (np.asarray(a, dtype=np.float64) for a in spectrum.get_peaks())
            if not np.isfinite(intensity).all() or not np.isfinite(mz).all():
                raise ValueError("原始扫描包含非有限值，不能用于诊断。")
            if intensity.size and np.max(np.abs(intensity)) > 1e70:
                raise ValueError("原始强度过大，无法安全执行诊断重构。")
            row = (
                [float(intensity.sum())]
                if signal == "tic"
                else [
                    float(intensity[(mz >= low) & (mz <= high)].sum())
                    for low, high in zip(lower, upper, strict=True)
                ]
            )
            times.append(float(spectrum.getRT()))
            indices.append(scan_index)
            values.append(row)
    if not np.isfinite(times).all():
        raise ValueError("扫描 RT 包含非有限值。")
    return np.asarray(values, dtype=np.float64), indices, times, channels
