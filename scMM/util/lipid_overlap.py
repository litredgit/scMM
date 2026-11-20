"""Conditional comparison of two MS1 explanations on one profile scan."""
# ruff: noqa: RUF001

import numpy as np
from scipy.optimize import nnls

from .lipid_isotopes import ADDUCTS, ELECTRON, fine_distribution, ion_composition


def _profile_width(mz, intensity, center, ppm):
    margin = min(center * ppm * 1e-6, 0.25)
    start = mz.searchsorted(center - margin)
    end = mz.searchsorted(center + margin, side="right")
    if start == end:
        return None
    apex = start + np.argmax(intensity[start:end])
    if not 0 < apex < len(mz) - 1 or intensity[apex] <= max(
        intensity[apex - 1], intensity[apex + 1]
    ):
        return None
    # Limit the width measurement to the parent region, away from nominal isotopes.
    lo, hi = mz.searchsorted([center - 0.25, center + 0.25])
    baseline = min(float(intensity[lo:hi].min()), intensity[apex])
    half = (intensity[apex] + baseline) / 2
    left = np.flatnonzero(intensity[lo:apex] <= half)
    right = np.flatnonzero(intensity[apex + 1 : hi] <= half)
    if not len(left) or not len(right):
        return None
    left = lo + left[-1]
    right = apex + 1 + right[0]
    lower = np.interp(half, intensity[left : left + 2], mz[left : left + 2])
    upper = np.interp(half, intensity[right - 1 : right + 1][::-1], mz[right - 1 : right + 1][::-1])
    return float(upper - lower)


def _envelope(candidate, orders):
    formula, adduct = candidate["formula"], candidate["adduct"]
    charge = ADDUCTS[adduct]["charge"]
    composition = ion_composition(formula, adduct)
    mono = float(composition.getMonoWeight()) - charge * ELECTRON
    lines = [(0.0, 1.0, 0), *fine_distribution(formula, adduct, orders)]
    return mono, np.asarray(lines), charge


def compare_profile(mz, intensity, candidates, *, max_order, ppm, fwhm=None, offset_ppm=0.0):
    """Fit parent-only and two-ion models over independently sampled peak regions."""
    mz, intensity = (np.asarray(values, dtype=float) for values in (mz, intensity))
    if (
        mz.ndim != 1
        or intensity.shape != mz.shape
        or not np.isfinite(mz).all()
        or not np.isfinite(intensity).all()
        or (mz <= 0).any()
        or (intensity < 0).any()
        or (np.diff(mz) <= 0).any()
    ):
        raise ValueError("连续谱需有递增且唯一的 m/z 和有限非负强度。")
    if len(candidates) != 2 or any(
        not row.get("formula")
        or row.get("source_formula_conflict")
        or row.get("adduct") not in ADDUCTS
        for row in candidates
    ):
        raise ValueError("请选择两个具有一致分子式和有效加合物的查库候选。")
    pairs = sorted(
        ((_envelope(row, max_order), row) for row in candidates),
        key=lambda pair: pair[0][0],
    )
    (low, parent, charge), (high, competitor, other_charge) = [pair[0] for pair in pairs]
    if charge != other_charge:
        raise ValueError("请选择相同极性的候选。")
    if len(parent) <= 1:
        raise ValueError("候选母峰没有可用于复核的天然同位素组分。")
    _, _, order = min(parent[1:], key=lambda line: abs(low + line[0] - high))
    components = parent[parent[:, 2] == order]
    delta = components[int(np.argmax(components[:, 1])), 0]
    shift = 1 + offset_ppm * 1e-6
    target = (low + delta) * shift
    result = {
        "method": "gaussian_profile_nnls_v1",
        "max_isotope_order": max_order,
        "parent_search_ppm": ppm,
        "candidates": [{**row, "mono_mz": info[0], "charge": info[2]} for info, row in pairs],
        "isotope_order": int(order),
        "isotope_mz": float(low + delta),
        "separation_da": float(abs(low + delta - high)),
        "offset_ppm": offset_ppm,
        "fwhm_source": "entered" if fwhm is not None else "same_scan_parent",
    }
    width = fwhm if fwhm is not None else _profile_width(mz, intensity, low * shift, ppm)
    result["fwhm_da"] = width
    result["status"] = "unresolved"
    if width is None or width <= 0:
        return {**result, "reason": "无法测得母峰半高宽。请核对扫描、质量偏移或填入已测半高宽。"}
    if abs(target - high * shift) > width:
        return {**result, "reason": "理论同位素峰与竞争单同位素峰相隔超过一个半高宽。"}
    centers = np.array([low, high]) * shift
    masks = [np.abs(mz - center) <= 3 * width for center in centers]
    if (masks[0] & masks[1]).any():
        return {**result, "reason": "母峰和重叠区未提供独立采样。"}
    for center, mask in zip(centers, masks, strict=True):
        points = mz[mask]
        if (
            len(points) < 5
            or points[0] >= center - width / 2
            or points[-1] <= center + width / 2
            or np.count_nonzero(abs(points - center) <= width / 2) < 3
        ):
            return {**result, "reason": "扫描未覆盖母峰和重叠区所需的连续谱点。"}
    covered = masks[0] | masks[1]
    if covered.sum() > 6000:
        raise ValueError("局部连续谱点超过上限，请核对半高宽。")
    x, y = mz[covered], intensity[covered]
    maximum = float(y.max())
    if maximum <= 0:
        return {**result, "reason": "所选范围没有正强度信号。"}
    regions = np.column_stack([mask[covered] for mask in masks])
    normalized = y / maximum

    def fit(ppm_delta, width_scale, *, mixed):
        columns = []
        for mono, lines in ((low, parent), (high, competitor))[: (2 if mixed else 1)]:
            line_mz = (mono + lines[:, 0]) * (shift + ppm_delta * 1e-6)
            use = (line_mz >= x[0] - width) & (line_mz <= x[-1] + width)
            distances = (x[:, None] - line_mz[use]) / (width * width_scale)
            columns.append(np.exp(-4 * np.log(2) * distances**2) @ lines[use, 1])
        matrix = np.column_stack([*columns, regions])
        if np.linalg.cond(matrix) > 1e6:
            raise ValueError("当前扫描无法稳定区分模型组分。")
        amplitudes, _ = nnls(matrix, normalized)
        return amplitudes * maximum, (matrix @ amplitudes) * maximum

    try:
        _, parent_only = fit(0.0, 1.0, mixed=False)
        amplitudes, fitted = fit(0.0, 1.0, mixed=True)
        sensitivity = [
            fit(delta_ppm, scale, mixed=True)[0][1]
            for delta_ppm, scale in [(-1.0, 1.0), (1.0, 1.0), (0.0, 0.9), (0.0, 1.1)]
        ]
    except (ValueError, RuntimeError):
        return {**result, "reason": "当前扫描的组分拟合无法稳定求解。"}
    residual = y - fitted
    parent_error = float(np.sqrt(np.mean((residual[regions[:, 0]] / maximum) ** 2)))
    if amplitudes[0] / maximum <= max(3 * parent_error, 1e-6):
        return {**result, "reason": "母峰信号不足以约束天然同位素贡献。"}
    return {
        **result,
        "status": "compared",
        "parent_height": float(amplitudes[0]),
        "competing_height": float(amplitudes[1]),
        "competing_height_sensitivity": [
            float(min(amplitudes[1], *sensitivity)),
            float(max(amplitudes[1], *sensitivity)),
        ],
        "parent_only_relative_rmse": float(np.sqrt(np.mean(((y - parent_only) / maximum) ** 2))),
        "mixed_relative_rmse": float(np.sqrt(np.mean((residual / maximum) ** 2))),
        "profile": {
            "mz": x.tolist(),
            "observed": y.tolist(),
            "parent_only": parent_only.tolist(),
            "mixed": fitted.tolist(),
            "residual": residual.tolist(),
            "region": np.where(regions[:, 0], "parent", "overlap").tolist(),
        },
    }
