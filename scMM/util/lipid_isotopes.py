"""Formula-specific natural isotope evidence, without modifying measured peaks."""
# ruff: noqa: RUF001

import hashlib
import json
import re
from functools import lru_cache

import numpy as np

from ._adducts import ELECTRON_MASS, fine_isotope_ratios, formula_mass_shift, resolve_isotope_ratios
from ._adducts import FORMULA_ADDUCTS as ADDUCTS

ELECTRON = ELECTRON_MASS


@lru_cache(maxsize=16)
def adduct_shift(name):
    spec = ADDUCTS[name]
    return formula_mass_shift(spec["add"], spec["remove"], spec["charge"])


def ion_composition(formula, adduct):
    from pyopenms import EmpiricalFormula

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
        return ion
    except (RuntimeError, OverflowError) as exc:
        raise ValueError(f"无法计算离子组成：{formula}") from exc


@lru_cache(maxsize=4096)
def fine_distribution(formula, adduct, max_order):
    ion = ion_composition(formula, adduct)
    try:
        return fine_isotope_ratios(ion, max_order)
    except (RuntimeError, OverflowError) as exc:
        raise ValueError(f"无法计算天然同位素分布：{formula}") from exc


def resolved_distribution(formula, adduct, max_order, parent_mz, resolution):
    """Merge fine isotope components only within one nominal order and one FWHM."""
    fine = fine_distribution(formula, adduct, max_order)
    return resolve_isotope_ratios(fine, parent_mz, ADDUCTS[adduct]["charge"], resolution)


def isotope_evidence(rows, mz, feature_ids, values, samples, parameters):
    relations, diagnostics = [], []
    sorted_indices = np.argsort(mz, kind="stable")
    sorted_mz = mz[sorted_indices]
    indices = {name: index for index, name in enumerate(feature_ids)}
    groups = [(sample, np.flatnonzero(samples == sample)) for sample in dict.fromkeys(samples)]
    distributions = {}
    for row in rows:
        if row.get("source_formula_conflict"):
            diagnostics.append(
                {
                    "feature_id": row["feature_id"],
                    "formula": row["formula"],
                    "adduct": row["adduct"],
                    "message": "原表理论 m/z 与分子式及加合物不一致，跳过天然同位素计算。",
                }
            )
            continue
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
