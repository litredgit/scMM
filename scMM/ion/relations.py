"""Database-independent candidate relations and sample-scoped measured evidence."""

from itertools import combinations

import numpy as np

from .identity import axis_identity, dataset_identity, json_identity
from .species import CARBON13_SHIFT


def validate_input(data, polarity, ppm):
    if polarity not in {"pos", "neg"} or not np.isfinite(ppm) or not 0 <= ppm < 1e6:
        raise ValueError("explicit polarity and finite mass tolerance required")
    axis_identity(data.obs_names)
    axis_identity(data.var_names)
    mz = np.asarray(data.var["mz"], dtype=float)
    if not np.isfinite(mz).all() or (mz <= 0).any():
        raise ValueError("finite positive measured m/z required")
    if "polarity" in data.obs and not set(data.obs["polarity"].astype(str)).issubset({polarity}):
        raise ValueError("separate acquisition polarities before ion grouping")
    if "polarity" in data.var:
        declared = set(data.var["polarity"].dropna().astype(str)) - {"unknown", ""}
        if not declared.issubset({polarity}):
            raise ValueError("separate feature polarities before ion grouping")
    return mz


def find_relations(
    data,
    specs,
    *,
    polarity,
    ppm=5.0,
    max_isotope_order=3,
    charge_magnitudes=(1, 2),
    loss_formulas=("H2O",),
):
    """Retain every matching role alternative; never collapse connected components."""
    mz = validate_input(data, polarity, ppm)
    if type(max_isotope_order) is not int or not 1 <= max_isotope_order <= 10:
        raise ValueError("invalid isotope order")
    if any(type(z) is not int or z <= 0 for z in charge_magnitudes):
        raise ValueError("charge magnitudes must be positive integers")
    specs = sorted(specs, key=lambda s: s.id)
    if len({s.id for s in specs}) != len(specs) or any(s.polarity != polarity for s in specs):
        raise ValueError("duplicate or incompatible ion species")
    ids = list(data.var_names)
    order = np.argsort(mz, kind="stable")
    sorted_mz = mz[order]
    rows = {}

    def emit(i, j, kind, **details):
        if i == j:
            return
        if kind in {"adduct", "charge", "multimer", "fragment_form"} and ids[i] > ids[j]:
            return  # reciprocal descriptions are the same measured evidence source
        item = {
            "left_feature_id": ids[i],
            "right_feature_id": ids[j],
            "kind": kind,
            "polarity": polarity,
            "left_mz": float(mz[i]),
            "right_mz": float(mz[j]),
            **details,
        }
        key = json_identity(item)
        rows[key] = {"relation_id": key, **item, "review": "pending"}

    def matches(target):
        if target <= 0:
            return []
        low, high = target * (1 - ppm * 1e-6), target * (1 + ppm * 1e-6)
        a, b = np.searchsorted(sorted_mz, [np.nextafter(low, -np.inf), np.nextafter(high, np.inf)])
        return order[a:b]

    for i in range(len(ids)):
        for charge in sorted(set(charge_magnitudes)):
            for isotope_order in range(1, max_isotope_order + 1):
                target = mz[i] + CARBON13_SHIFT * isotope_order / charge
                for j in matches(target):
                    emit(
                        i,
                        j,
                        "isotope",
                        charge_magnitude=charge,
                        order=isotope_order,
                        predicted_mz=float(target),
                        ppm_error=float((mz[j] - target) / target * 1e6),
                        isotope_model="carbon13_ladder_candidate",
                        theoretical_ratio=None,
                    )
        for left_spec, right_spec in combinations(specs, 2):
            for a, b in ((left_spec, right_spec), (right_spec, left_spec)):
                neutral = a.neutral_mass(mz[i])
                if neutral <= 0:
                    continue
                if b.oligomer * neutral + b.shift <= 0:
                    continue
                target = b.mz(neutral)
                left_interval = a.neutral_interval(mz[i], ppm)
                lower_neutral = max(left_interval[0], np.finfo(float).tiny)
                if b.oligomer * lower_neutral + b.shift <= 0:
                    continue
                low = b.mz(lower_neutral) * (1 - ppm * 1e-6)
                high = b.mz(left_interval[1]) * (1 + ppm * 1e-6)
                first, last = np.searchsorted(
                    sorted_mz, [np.nextafter(low, -np.inf), np.nextafter(high, np.inf)]
                )
                for j in order[first:last]:
                    if a.fragment_form or b.fragment_form:
                        kind = "fragment_form"
                    elif a.oligomer != b.oligomer:
                        kind = "multimer"
                    elif abs(a.charge) != abs(b.charge):
                        kind = "charge"
                    else:
                        kind = "adduct"
                    emit(
                        i,
                        j,
                        kind,
                        left_species=a.id,
                        right_species=b.id,
                        neutral_mass=float(neutral),
                        predicted_mz=float(target),
                        ppm_error=float((mz[j] - target) / target * 1e6),
                        left_interval=list(a.neutral_interval(mz[i], ppm)),
                        right_interval=list(b.neutral_interval(mz[j], ppm)),
                    )
    from pyopenms import EmpiricalFormula

    for loss in loss_formulas:
        mass = EmpiricalFormula(loss).getMonoWeight()
        if mass <= 0 or not np.isfinite(mass):
            raise ValueError("invalid neutral loss")
        for i in range(len(ids)):
            for charge in sorted(set(charge_magnitudes)):
                target = mz[i] - mass / charge
                for j in matches(target):
                    emit(
                        i,
                        j,
                        "neutral_loss",
                        loss_formula=loss,
                        charge_magnitude=charge,
                        predicted_mz=float(target),
                        ppm_error=float((mz[j] - target) / target * 1e6),
                    )
    return {
        "schema_version": 1,
        "input_identity": dataset_identity(data),
        "parameters": {
            "ppm": ppm,
            "polarity": polarity,
            "max_isotope_order": max_isotope_order,
            "charge_magnitudes": list(charge_magnitudes),
            "loss_formulas": list(loss_formulas),
        },
        "relations": [rows[key] for key in sorted(rows)],
    }


def measure_evidence(data, relations, *, sample_field="sample_id", min_valid_cells=20):
    """Keep zeros in totals; constants and insufficient overlap are not counterevidence."""

    from scMM.util.intensity import intensity_states

    from .semantics import value_states

    if intensity_states(data)["X"] != "raw":
        raise ValueError("relation evidence requires unnormalized measurement provenance")

    if value_states(data)["X"]["space"] != "linear_abundance" or value_states(data)["X"]["imputed"]:
        raise ValueError("relation intensity evidence requires explicit unimputed linear input")
    if type(min_valid_cells) is not int or min_valid_cells < 2:
        raise ValueError("at least two valid cells required")
    values = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("nonnegative finite intensities required")
    if sample_field in data.obs and data.obs[sample_field].isna().any():
        raise ValueError("sample IDs must be explicit for every cell")
    samples = (
        data.obs[sample_field].astype(str).to_numpy()
        if sample_field in data.obs
        else np.repeat("single_sample", data.n_obs)
    )
    positions = {str(key): i for i, key in enumerate(data.var_names)}
    evidence = []
    for relation in relations:
        x, y = (
            values[:, positions[relation["left_feature_id"]]],
            values[:, positions[relation["right_feature_id"]]],
        )
        for sample in sorted(set(samples)):
            mask = samples == sample
            a, b = x[mask], y[mask]
            valid = a > 0
            joint = valid & (b > 0)
            ratios = b[valid] / a[valid]
            correlation = None
            if joint.sum() >= min_valid_cells and np.ptp(a[joint]) > 0 and np.ptp(b[joint]) > 0:
                correlation = float(np.corrcoef(a[joint], b[joint])[0, 1])
            evidence.append(
                {
                    "relation_id": relation["relation_id"],
                    "sample_id": sample,
                    "valid_cells": int(valid.sum()),
                    "joint_cells": int(joint.sum()),
                    "parent_absent_child_present": int(((a <= 0) & (b > 0)).sum()),
                    "observed_ratio": float(b[valid].sum() / a[valid].sum())
                    if valid.any()
                    else None,
                    "ratio_quantiles": np.quantile(ratios, [0.25, 0.5, 0.75]).tolist()
                    if len(ratios)
                    else [],
                    "joint_pearson": correlation,
                    "status": "measured" if valid.sum() >= min_valid_cells else "not_evaluable",
                    "ratio_definition": "independent_event_peak_heights",
                }
            )
    return evidence


def formula_relations(data, hypotheses, *, polarity, ppm=5.0, resolution_200, max_isotope_order=3):
    """Conditional isotope evidence; formula alternatives remain separate records."""
    from .species import ION_SPECS, resolved_isotopes

    mz = validate_input(data, polarity, ppm)
    if not np.isfinite(resolution_200) or resolution_200 <= 0:
        raise ValueError("positive acquisition resolution at m/z 200 required")
    if type(max_isotope_order) is not int or not 1 <= max_isotope_order <= 10:
        raise ValueError("invalid isotope order")
    positions = {str(key): i for i, key in enumerate(data.var_names)}
    result = {}
    for hypothesis in hypotheses:
        parent_id = hypothesis["feature_id"]
        parent = positions[parent_id]
        spec = ION_SPECS[hypothesis["species_id"]]
        if spec.polarity != polarity:
            raise ValueError("formula hypothesis polarity mismatch")
        peaks = resolved_isotopes(
            hypothesis["formula"],
            spec,
            parent_mz=mz[parent],
            resolution_200=resolution_200,
            max_order=max_isotope_order,
        )
        for peak in peaks:
            for child in np.flatnonzero(abs(mz - peak["mz"]) / peak["mz"] * 1e6 <= ppm):
                if child == parent:
                    continue
                record = {
                    "left_feature_id": parent_id,
                    "right_feature_id": str(data.var_names[child]),
                    "kind": "isotope",
                    "polarity": polarity,
                    "formula": hypothesis["formula"],
                    "left_species": spec.id,
                    "right_species": spec.id,
                    "charge_magnitude": abs(spec.charge),
                    "order": peak["order"],
                    "predicted_mz": peak["mz"],
                    "theoretical_ratio": peak["ratio"],
                    "ppm_error": float((mz[child] - peak["mz"]) / peak["mz"] * 1e6),
                    "isotope_model": "formula_conditioned_natural_fine_structure",
                    "resolution_200": resolution_200,
                }
                identity = json_identity(record)
                result[identity] = {"relation_id": identity, **record, "review": "pending"}
    return [result[key] for key in sorted(result)]


def assess_isotope_ratios(relations, evidence, *, relative_tolerance=0.2, min_valid_cells=20):
    """Uncalibrated rule states, retaining failure separately from missing information."""
    if not np.isfinite(relative_tolerance) or not 0 <= relative_tolerance <= 1:
        raise ValueError("invalid isotope ratio tolerance")
    if type(min_valid_cells) is not int or min_valid_cells < 2:
        raise ValueError("at least two valid cells required")
    by_id = {row["relation_id"]: row for row in relations}
    rows = []
    for observed in evidence:
        relation = by_id[observed["relation_id"]]
        expected = relation.get("theoretical_ratio")
        status = "not_evaluable"
        deviation = None
        if (
            expected is not None
            and expected > 0
            and observed["observed_ratio"] is not None
            and observed["valid_cells"] >= min_valid_cells
        ):
            deviation = abs(observed["observed_ratio"] / expected - 1)
            status = "pass" if deviation <= np.nextafter(relative_tolerance, np.inf) else "fail"
        rows.append(
            {
                **observed,
                "ratio_status": status,
                "relative_deviation": deviation,
                "relative_tolerance": relative_tolerance,
            }
        )
    return rows


def same_scan_window_evidence(parent, child, *, frame_ids, source_identity):
    """Audit already baseline-corrected simultaneous scans, never alter event peaks."""
    a, b = np.asarray(parent, dtype=float), np.asarray(child, dtype=float)
    if (
        a.ndim != 1
        or a.shape != b.shape
        or len(frame_ids) != len(a)
        or len(set(frame_ids)) != len(frame_ids)
        or not source_identity
        or not np.isfinite(a).all()
        or not np.isfinite(b).all()
        or (a < 0).any()
        or (b < 0).any()
    ):
        raise ValueError("invalid same-scan window evidence")
    valid = a > 0
    return {
        "source_identity": source_identity,
        "frame_ids": list(frame_ids),
        "definition": "same_scan_baseline_corrected_sum_ratio",
        "valid_frames": int(valid.sum()),
        "observed_ratio": float(b[valid].sum() / a[valid].sum()) if valid.any() else None,
        "parent": a.tolist(),
        "child": b.tolist(),
    }
