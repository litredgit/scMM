"""Formula-specific natural isotope evidence, without modifying measured peaks."""
# ruff: noqa: RUF001

import hashlib
import json
import re
from functools import lru_cache

import numpy as np

ELECTRON = 0.000548579909065
ADDUCTS = {
    "[M+H-H2O]+": {"polarity": "pos", "add": "H", "remove": "H2O", "charge": 1},
    "[M+H]+": {"polarity": "pos", "add": "H", "remove": "", "charge": 1},
    "[M+Na]+": {"polarity": "pos", "add": "Na", "remove": "", "charge": 1},
    "[M+K]+": {"polarity": "pos", "add": "K", "remove": "", "charge": 1},
    "[M+NH4]+": {"polarity": "pos", "add": "NH4", "remove": "", "charge": 1},
    "[M-H]-": {"polarity": "neg", "add": "", "remove": "H", "charge": -1},
    "[M+Cl]-": {"polarity": "neg", "add": "Cl", "remove": "", "charge": -1},
    "[M+HCOO]-": {"polarity": "neg", "add": "CHO2", "remove": "", "charge": -1},
    "[M+OAc]-": {"polarity": "neg", "add": "C2H3O2", "remove": "", "charge": -1},
}


@lru_cache(maxsize=16)
def adduct_shift(name):
    from pyopenms import EmpiricalFormula

    spec = ADDUCTS[name]
    return (
        EmpiricalFormula(spec["add"]).getMonoWeight()
        - EmpiricalFormula(spec["remove"]).getMonoWeight()
        - spec["charge"] * ELECTRON
    )


@lru_cache(maxsize=4096)
def fine_distribution(formula, adduct, max_order):
    from pyopenms import EmpiricalFormula, FineIsotopePatternGenerator

    try:
        molecule = EmpiricalFormula(formula)
        spec = ADDUCTS[adduct]
        # Formula isotope labels belong to tracer models and are outside this workflow.
        if (
            not formula
            or "(" in formula
            or ")" in formula
            or molecule.getCharge()
            or re.search(r"(?:D|T)(?![a-z])", formula)
        ):
            raise ValueError("需使用不带同位素标签的中性分子式。")
        ion = molecule + EmpiricalFormula(spec["add"]) - EmpiricalFormula(spec["remove"])
        if any(count < 0 for count in ion.getElementalComposition().values()):
            raise ValueError("加合物移除的元素数超过分子式。")
        mass = ion.getMonoWeight()
        values = ion.getIsotopeDistribution(FineIsotopePatternGenerator(1e-6)).getContainer()
        peaks = [(float(v.getMZ()) - mass, float(v.getIntensity())) for v in values]
        p0 = sum(p for delta, p in peaks if abs(delta) < 1e-5)
        if p0 <= 0:
            raise ValueError("无法获得有效单同位素概率。")
        return [
            (delta, p / p0, round(delta)) for delta, p in peaks if 1 <= round(delta) <= max_order
        ]
    except (RuntimeError, OverflowError) as exc:
        raise ValueError(f"无法计算天然同位素分布：{formula}") from exc


def resolved_distribution(formula, adduct, max_order, parent_mz, resolution):
    """Merge fine isotope components only within one nominal order and one FWHM.

    Resolution is R at m/z 200 for the extraction's Orbitrap-style scaling.
    The probability-weighted centroid is an approximation, not signal deconvolution.
    """
    clusters = []
    for delta, ratio, order in sorted(fine_distribution(formula, adduct, max_order)):
        mz = parent_mz + delta
        width = mz / (resolution * np.sqrt(200 / mz))
        if clusters and clusters[-1]["order"] == order and mz - clusters[-1]["first_mz"] <= width:
            group = clusters[-1]
            group["mz"] = (group["mz"] * group["ratio"] + mz * ratio) / (group["ratio"] + ratio)
            group["ratio"] += ratio
            group["components"] += 1
        else:
            clusters.append(
                {"mz": mz, "ratio": ratio, "order": order, "first_mz": mz, "components": 1}
            )
    return clusters


def isotope_evidence(rows, mz, feature_ids, values, samples, parameters):
    relations, diagnostics = [], []
    sorted_indices = np.argsort(mz, kind="stable")
    sorted_mz = mz[sorted_indices]
    indices = {name: index for index, name in enumerate(feature_ids)}
    groups = [(sample, np.flatnonzero(samples == sample)) for sample in dict.fromkeys(samples)]
    distributions = {}
    for row in rows:
        key = row["feature_id"], row["formula"], row["adduct"]
        if key not in distributions:
            try:
                distributions[key] = resolved_distribution(
                    row["formula"],
                    row["adduct"],
                    parameters["max_isotope_order"],
                    row["query_mz"],
                    parameters["resolution"],
                )
            except ValueError as exc:
                distributions[key] = []
                diagnostics.append(
                    {
                        "feature_id": row["feature_id"],
                        "formula": row["formula"],
                        "adduct": row["adduct"],
                        "message": str(exc),
                    }
                )
        parent = indices[row["feature_id"]]
        for peak_index, peak in enumerate(distributions[key]):
            target = peak["mz"]
            width = target * parameters["isotope_ppm"] * 1e-6
            start, end = np.searchsorted(
                sorted_mz,
                [np.nextafter(target - width, -np.inf), np.nextafter(target + width, np.inf)],
            )
            for child in sorted_indices[start:end]:
                if child == parent:
                    continue
                error = (mz[child] - target) / target * 1e6
                if abs(error) > np.nextafter(parameters["isotope_ppm"], np.inf):
                    continue
                for sample, cell_indices in groups:
                    x, y = values[cell_indices, parent], values[cell_indices, child]
                    valid = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y >= 0)
                    count = int(valid.sum())
                    observed = float(y[valid].sum() / x[valid].sum()) if count else None
                    deviation = abs(observed / peak["ratio"] - 1) if observed is not None else None
                    tolerance = parameters["isotope_tolerance"]
                    at_boundary = deviation is not None and np.isclose(
                        deviation, tolerance, rtol=64 * np.finfo(float).eps, atol=0
                    )
                    matched = bool(
                        count >= parameters["min_valid_cells"]
                        and deviation is not None
                        and (deviation <= tolerance or at_boundary)
                    )
                    identity = json.dumps(
                        [row["candidate_id"], feature_ids[child], peak_index, str(sample)]
                    )
                    relations.append(
                        {
                            "relation_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                            "parent_candidate_id": row["candidate_id"],
                            "parent_feature_id": row["feature_id"],
                            "isotope_feature_id": feature_ids[child],
                            "name": row["name"],
                            "database_id": row["database_id"],
                            "formula": row["formula"],
                            "adduct": row["adduct"],
                            "sample": str(sample),
                            "order": peak["order"],
                            "parent_mz": float(mz[parent]),
                            "isotope_mz": float(mz[child]),
                            "predicted_mz": target,
                            "ppm_error": float(error),
                            "theoretical_ratio": peak["ratio"],
                            "observed_ratio": observed,
                            "relative_deviation": deviation,
                            "valid_cells": count,
                            "matched": matched,
                            "components": peak["components"],
                            "review": "pending",
                            "parent_absent_child_present": int(((x <= 0) & (y > 0)).sum()),
                        }
                    )
    return relations, diagnostics
