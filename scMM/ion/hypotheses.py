"""Bounded, auditable role assignments with whole-group mass consistency."""

from copy import deepcopy
from time import monotonic

import numpy as np

from .identity import dataset_identity, json_identity
from .species import CARBON13_SHIFT, IonSpec


def infer_groups(
    data,
    relations,
    specs,
    *,
    ppm=5.0,
    max_states=100000,
    timeout_seconds=30.0,
    max_hypotheses=10000,
):
    """Enumerate compatible local assignments; unchosen splits remain soft alternatives."""
    if (
        type(max_states) is not int
        or max_states < 1
        or not np.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("positive search budgets required")
    if min(data.shape) < 1:
        raise ValueError("nonempty measurement input required")
    if type(max_hypotheses) is not int or max_hypotheses < 1:
        raise ValueError("positive hypothesis budget required")
    specs = list(specs)
    input_identity = dataset_identity(data)
    ids = list(data.var_names)
    masses = dict(zip(ids, np.asarray(data.var["mz"], dtype=float), strict=True))
    by_spec = {s.id: s for s in specs}
    if len(by_spec) != len(specs):
        raise ValueError("duplicate ion species IDs")
    graph = {key: set() for key in ids}
    roles = {key: {} for key in ids}
    for row in relations:
        left, right = row["left_feature_id"], row["right_feature_id"]
        if left not in masses or right not in masses:
            raise ValueError("relation references unknown feature")
        if row["kind"] in {"neutral_loss", "fragment_form"}:
            continue
        pairs = []
        if row["kind"] == "isotope":
            available = [
                s for s in specs if abs(s.charge) == row["charge_magnitude"] and not s.fragment_form
            ]
            if row.get("left_species"):
                available = [by_spec[row["left_species"]]]
            if not available:
                if row.get("polarity") not in {"pos", "neg"}:
                    raise ValueError("unknown envelope requires explicit acquisition polarity")
                charge = row["charge_magnitude"] * (1 if row["polarity"] == "pos" else -1)
                available = [IonSpec(f"_unknown_ion:{charge}", charge)]
            shift = (
                (row["predicted_mz"] - masses[left]) * row["charge_magnitude"]
                if row.get("formula")
                else row["order"] * CARBON13_SHIFT
            )
            # Unknown monoisotopic start is explicitly retained as a mass alternative.
            starts = (0,) if row.get("formula") else range(4)
            pairs = [
                (s, s, start * CARBON13_SHIFT, start * CARBON13_SHIFT + shift)
                for s in available
                for start in starts
            ]
        elif row.get("left_species") in by_spec and row.get("right_species") in by_spec:
            pairs = [(by_spec[row["left_species"]], by_spec[row["right_species"]], 0.0, 0.0)]
        for a, b, offset_a, offset_b in pairs:
            graph[left].add(right)
            graph[right].add(left)
            for feature, spec, offset in ((left, a, offset_a), (right, b, offset_b)):
                low, high = spec.neutral_interval(masses[feature], ppm)
                low, high = low - offset / spec.oligomer, high - offset / spec.oligomer
                if high <= 0:
                    continue
                role = {
                    "species_id": spec.id,
                    "isotope_shift": float(offset),
                    "interval": [max(low, 0.0), high],
                    "charge": spec.charge,
                    "oligomer": None if spec.id.startswith("_unknown_ion:") else spec.oligomer,
                    "coordinate_kind": "ion_envelope"
                    if spec.id.startswith("_unknown_ion:")
                    else "neutral_mass",
                }
                key = json_identity([spec.id, float(offset).hex()])
                roles[feature][key] = role
    components, remaining = [], set(ids)
    while remaining:
        stack, component = [min(remaining)], set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(sorted(graph[node] - component))
        remaining -= component
        components.append(sorted(component))
    groups, diagnostics = {}, []
    for component in components:
        start_time, states, complete = monotonic(), 0, True
        found = {}
        if len(component) < 2:
            diagnostics.append({"features": component, "search_complete": True, "states": 0})
            continue
        for anchor_feature in component:
            for anchor_key, anchor in sorted(roles[anchor_feature].items()):
                if not complete:
                    break
                options = []
                for feature in component:
                    if feature == anchor_feature:
                        continue
                    compatible = [
                        (key, role)
                        for key, role in sorted(roles[feature].items())
                        if role["coordinate_kind"] == anchor["coordinate_kind"]
                        and max(anchor["interval"][0], role["interval"][0])
                        <= min(anchor["interval"][1], role["interval"][1])
                    ]
                    if compatible:
                        options.append((feature, compatible))
                occupied = {(anchor["species_id"], anchor["isotope_shift"].hex())}
                initial = {anchor_feature: (anchor_key, anchor)}

                def visit(
                    position,
                    low,
                    high,
                    assigned,
                    slots,
                    *,
                    options=options,
                    found=found,
                    start_time=start_time,
                    coordinate_kind=anchor["coordinate_kind"],
                ):
                    nonlocal states, complete
                    states += 1
                    if states > max_states or monotonic() - start_time > timeout_seconds:
                        complete = False
                        return
                    if position == len(options):
                        if len(assigned) >= 2:
                            members = sorted(assigned)
                            key = json_identity({f: assigned[f][0] for f in members})
                            if key not in found and len(found) >= max_hypotheses:
                                complete = False
                                return
                            found[key] = {
                                "hypothesis_id": key,
                                "members": {f: assigned[f][1] for f in members},
                                "neutral_interval": [low, high]
                                if coordinate_kind == "neutral_mass"
                                else None,
                                "neutral_mass": (low + high) / 2
                                if coordinate_kind == "neutral_mass"
                                else None,
                                "envelope_interval": [low, high]
                                if coordinate_kind == "ion_envelope"
                                else None,
                                "neutral_mass_estimator": "matching_interval_midpoint",
                            }
                        return
                    feature, candidates = options[position]
                    visit(position + 1, low, high, assigned, slots)
                    for role_key, role in candidates:
                        if not complete:
                            return
                        slot = (role["species_id"], role["isotope_shift"].hex())
                        lower, upper = max(low, role["interval"][0]), min(high, role["interval"][1])
                        if lower > upper or slot in slots:
                            continue
                        visit(
                            position + 1,
                            lower,
                            upper,
                            {**assigned, feature: (role_key, role)},
                            slots | {slot},
                        )

                visit(0, *anchor["interval"], initial, occupied)
            if not complete:
                break
        diagnostics.append({"features": component, "search_complete": complete, "states": states})
        for hypothesis in found.values():
            members = sorted(hypothesis["members"])
            group_id = json_identity({"input": input_identity, "members": members})
            group = groups.setdefault(
                group_id,
                {
                    "ec_id": group_id,
                    "feature_ids": members,
                    "hypotheses": [],
                    "search_complete": complete,
                    "independent_split_possible": True,
                },
            )
            group["hypotheses"].append(hypothesis)
    grouped = {f for group in groups.values() for f in group["feature_ids"]}
    return {
        "schema_version": 1,
        "input_identity": input_identity,
        "parameters": {
            "ppm": ppm,
            "max_states": max_states,
            "timeout_seconds": timeout_seconds,
            "max_missing_monoisotopic_order": 3,
            "max_hypotheses": max_hypotheses,
        },
        "groups": [groups[key] for key in sorted(groups)],
        "relations": deepcopy(relations),
        "singletons": sorted(set(ids) - grouped),
        "diagnostics": diagnostics,
    }


def reviewed_group(grouping, ec_id, hypothesis_id):
    group = next((g for g in grouping["groups"] if g["ec_id"] == ec_id), None)
    if group is None or not group["search_complete"]:
        raise ValueError("unknown group or incomplete search")
    hypothesis = next((h for h in group["hypotheses"] if h["hypothesis_id"] == hypothesis_id), None)
    if hypothesis is None:
        raise ValueError("unknown ion-role interpretation")
    return group, hypothesis
