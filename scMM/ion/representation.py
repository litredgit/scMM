"""Explicit reviewed representations; no deletion, ion switching or intensity sum."""

import json
from copy import deepcopy

import numpy as np
import pandas as pd
from anndata import AnnData

from .hypotheses import reviewed_group
from .identity import dataset_identity, json_identity
from .semantics import unknown_state, value_states, write_value_states


def build_representations(
    data,
    grouping,
    selections,
    *,
    relation_reviews,
    strategy="isotope_representatives",
    quantification="fixed_representative",
    decision_mode="reviewed_v1",
    include_singletons=False,
):
    """Selections name one group interpretation and optional fixed quantifier feature."""
    if decision_mode not in {"reviewed_v1", "exploratory_v1"}:
        raise ValueError("unknown representation decision mode")
    required_review = "accepted" if decision_mode == "reviewed_v1" else "rule_supported"
    if grouping["input_identity"] != dataset_identity(data):
        raise ValueError("grouping input changed")
    if strategy not in {"isotope_representatives", "ion_group_representatives"}:
        raise ValueError("unknown L1 representation")
    if quantification != "fixed_representative":
        raise ValueError("unsupported quantification strategy")
    semantics = value_states(data)["X"]
    if semantics["space"] != "linear_abundance" or semantics["imputed"]:
        raise ValueError("quantification requires unimputed linear measurement input")
    values = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("finite nonnegative measurement intensities required")
    samples = (
        data.obs["sample_id"].astype(str).to_numpy()
        if "sample_id" in data.obs
        else np.repeat("single_sample", data.n_obs)
    )
    positions = {str(key): i for i, key in enumerate(data.var_names)}
    used, exclude, quantifiers, audit, unavailable = set(), set(), [], [], []
    for selection in selections:
        group, hypothesis = reviewed_group(grouping, selection["ec_id"], selection["hypothesis_id"])
        members = set(group["feature_ids"])
        if members & used:
            raise ValueError("a feature cannot be quantified in two selected entities")
        if selection.get("review") != required_review:
            raise ValueError("reviewed representation requires explicit acceptance")
        support = selection.get("relation_ids", [])
        if not support or any(relation_reviews.get(key) != required_review for key in support):
            raise ValueError("required relations have not been accepted")
        if selection.get("mixed") or selection.get("shared"):
            raise ValueError("unresolved mixed or shared signal cannot be quantified")
        supporting = {row["relation_id"]: row for row in grouping["relations"]}
        adjacency = {feature: set() for feature in members}
        for identity in support:
            if identity not in supporting:
                raise ValueError("unknown supporting relation")
            row = supporting[identity]
            left, right = row["left_feature_id"], row["right_feature_id"]
            if (
                left not in members
                or right not in members
                or row["kind"] in {"neutral_loss", "fragment_form"}
            ):
                raise ValueError("supporting relation does not belong to selected core group")
            left_role, right_role = hypothesis["members"][left], hypothesis["members"][right]
            if row["kind"] == "isotope":
                expected_shift = (row["predicted_mz"] - float(data.var.loc[left, "mz"])) * row[
                    "charge_magnitude"
                ]
                if (
                    abs(left_role["charge"]) != row["charge_magnitude"]
                    or left_role["species_id"] != right_role["species_id"]
                    or not np.isclose(
                        right_role["isotope_shift"] - left_role["isotope_shift"],
                        expected_shift,
                        rtol=1e-8,
                        atol=1e-8,
                    )
                ):
                    raise ValueError("accepted relation conflicts with selected ion roles")
            elif (
                left_role["species_id"] != row["left_species"]
                or right_role["species_id"] != row["right_species"]
            ):
                raise ValueError("accepted relation conflicts with selected ion species")
            adjacency[left].add(right)
            adjacency[right].add(left)
        reached, stack = set(), [min(members)]
        while stack:
            node = stack.pop()
            if node in reached:
                continue
            reached.add(node)
            stack.extend(adjacency[node] - reached)
        if reached != members:
            raise ValueError("accepted relations do not connect all selected members")
        used |= members
        eligible = [
            feature for feature, role in hypothesis["members"].items() if role["oligomer"] == 1
        ]

        def rank(feature):
            vector = values[:, positions[feature]]
            detection = np.mean(
                [np.mean(vector[samples == sample] > 0) for sample in sorted(set(samples))]
            )
            average = np.mean([vector[samples == sample].mean() for sample in sorted(set(samples))])
            return (-float(detection), -float(average), feature)

        quantifier = selection.get("quantifier_feature_id") or (
            min(eligible, key=rank) if eligible else None
        )
        if selection.get("quantifier_feature_id") and quantifier not in eligible:
            raise ValueError("quantifier is not an eligible member")
        if quantifier is None:
            unavailable.append({"ec_id": group["ec_id"], "reason": "no_intact_monomer"})
        if quantifier is not None:
            quantifiers.append(
                {
                    "ec_id": group["ec_id"],
                    "quantifier_feature_id": quantifier,
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "method": quantification,
                    "entity_status": "grouped",
                    "source_members": sorted(members),
                    "ion_role": deepcopy(hypothesis["members"][quantifier]),
                    "neutral_mass": hypothesis["neutral_mass"],
                }
            )
        families = {}
        for feature, role in hypothesis["members"].items():
            families.setdefault(role["species_id"], []).append(feature)
        family_representatives = {
            species: min(
                features, key=lambda f: (hypothesis["members"][f]["isotope_shift"], rank(f))
            )
            for species, features in families.items()
        }
        group_representative = quantifier or min(members, key=rank)
        for feature, role in hypothesis["members"].items():
            representative = (
                group_representative
                if strategy == "ion_group_representatives"
                else family_representatives[role["species_id"]]
            )
            remove = feature != representative
            if remove:
                exclude.add(feature)
            audit.append(
                {
                    "feature_id": feature,
                    "action": "exclude" if remove else "keep",
                    "representative_feature_id": representative,
                    "ec_id": group["ec_id"],
                }
            )
    if include_singletons:
        for feature in sorted(set(positions) - used):
            quantifiers.append(
                {
                    "ec_id": json_identity([grouping["input_identity"], feature, "ungrouped"]),
                    "quantifier_feature_id": feature,
                    "method": quantification,
                    "hypothesis_id": "",
                    "entity_status": "ungrouped",
                    "source_members": [feature],
                    "ion_role": {},
                    "neutral_mass": None,
                }
            )
    kept = [str(key) for key in data.var_names if key not in exclude]
    l1 = data[:, kept].copy()
    l2 = None
    if quantifiers:
        columns = [positions[row["quantifier_feature_id"]] for row in quantifiers]
        records = [
            {
                key: json.dumps(value, allow_nan=False)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
            }
            for row in quantifiers
        ]
        var = pd.DataFrame(records).set_index("ec_id", drop=False)
        availability = (
            np.asarray(data.layers["scmm_measurement_available"], dtype=bool)[:, columns]
            if "scmm_measurement_available" in data.layers
            else np.ones((data.n_obs, len(columns)), dtype=bool)
        )
        l2 = AnnData(
            np.where(availability, values[:, columns], np.nan), obs=data.obs.copy(), var=var
        )
        l2.layers["scmm_quantifiable"] = availability
        write_value_states(
            l2,
            {
                "X": {**unknown_state(), "space": "linear_abundance"},
                "scmm_quantifiable": unknown_state(),
            },
        )
        l2.uns["scmm_variable_kind"] = "empirical_compound"
    selected = {row["feature_id"] for row in audit}
    audit += [
        {"feature_id": str(f), "action": "keep", "reason": "unknown_or_unselected"}
        for f in data.var_names
        if f not in selected
    ]
    metadata = {
        "schema_version": 1,
        "input_identity": grouping["input_identity"],
        "strategy": strategy,
        "quantifiers": quantifiers,
        "selection_audit": audit,
        "unavailable_groups": unavailable,
        "selections": deepcopy(selections),
        "decision_mode": decision_mode,
        "include_singletons": include_singletons,
    }
    metadata["representation_id"] = json_identity(metadata)
    encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    l1.uns["scmm_representation_json"] = encoded
    if l2 is not None:
        from scMM.util.intensity import intensity_states, write_intensity_states

        l2.uns["scmm_representation_json"] = encoded
        write_intensity_states(
            l2, {"X": intensity_states(data)["X"], "scmm_quantifiable": "unknown"}
        )
    return l1, l2, metadata


def preview_complete_availability(source, *, cell_ids=None, variable_ids=None):
    """Fix exactly one axis, then select complete availability on the other axis."""
    if (cell_ids is None) == (variable_ids is None):
        raise ValueError("fix exactly one axis for availability selection")
    available = source.layers["scmm_quantifiable"]
    if available.dtype.kind != "b":
        raise ValueError("availability must use a boolean mask")
    mask = available.toarray() if hasattr(available, "toarray") else np.asarray(available)
    values = source.X.toarray() if hasattr(source.X, "toarray") else np.asarray(source.X)
    if np.isinf(values).any() or not np.array_equal(np.isnan(values), ~mask):
        raise ValueError("availability does not match structural missingness")
    if cell_ids is not None:
        cells = list(cell_ids)
        indices = source.obs_names.get_indexer(cells)
        if not cells or min(indices) < 0 or len(cells) != len(set(cells)):
            raise ValueError("invalid cell selection")
        variables = list(source.var_names[mask[indices].all(axis=0)])
    else:
        variables = list(variable_ids)
        indices = source.var_names.get_indexer(variables)
        if not variables or min(indices) < 0 or len(variables) != len(set(variables)):
            raise ValueError("invalid variable selection")
        cells = list(source.obs_names[mask[:, indices].all(axis=1)])
    if not cells or not variables:
        raise ValueError("no common quantifiable input")
    return {
        "source_identity": dataset_identity(source, allow_missing=True),
        "cell_ids": cells,
        "variable_ids": variables,
        "policy": "complete_availability",
    }


def materialize_complete_availability(source, preview):
    if preview["source_identity"] != dataset_identity(source, allow_missing=True):
        raise ValueError("availability preview is stale")
    selected = source[preview["cell_ids"], preview["variable_ids"]].copy()
    numeric = selected.X.toarray() if hasattr(selected.X, "toarray") else selected.X
    if not np.isfinite(numeric).all():
        raise ValueError("selection contains unavailable measurements")
    selected.uns["scmm_materialization"] = dict(preview)
    return selected


def build_exploratory_representations(data, grouping, evidence, **options):
    """Apply the explicit uncalibrated rule profile; never create manual review events."""
    by_relation = {}
    for row in evidence:
        by_relation.setdefault(row["relation_id"], []).append(row)
    relations = grouping["relations"]
    isotope_rows = [row for row in relations if row["kind"] == "isotope"]
    compatible = {}
    for row in isotope_rows:
        key = (
            row["left_feature_id"],
            row["right_feature_id"],
            row["charge_magnitude"],
            row["order"],
        )
        compatible.setdefault(key, []).append(row)
    eligible = []
    for alternatives in compatible.values():
        tested = [r for r in alternatives if r.get("theoretical_ratio") is not None]
        if not tested:
            continue
        passed = True
        for row in tested:
            checks = [e["ratio_status"] for e in by_relation.get(row["relation_id"], [])]
            if "pass" not in checks or "fail" in checks:
                passed = False
        if passed:
            eligible.extend(tested)
    parents = {r["left_feature_id"] for r in eligible}
    eligible += [
        row
        for row in relations
        if row["kind"] in {"adduct", "charge"}
        and row["left_feature_id"] in parents
        and row["right_feature_id"] in parents
    ]
    graph = {}
    for row in eligible:
        left, right = row["left_feature_id"], row["right_feature_id"]
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    remaining = set(graph)
    selections = []
    while remaining:
        visited, stack = set(), [min(remaining)]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(graph[node] - visited)
        remaining -= visited
        candidates = [
            group
            for group in grouping["groups"]
            if group["search_complete"] and set(group["feature_ids"]) == visited
        ]
        if len(candidates) != 1:
            continue
        group = candidates[0]
        support = [
            row
            for row in eligible
            if row["left_feature_id"] in visited and row["right_feature_id"] in visited
        ]
        hypotheses = []
        for hypothesis in group["hypotheses"]:
            roles = hypothesis["members"]
            valid = True
            for row in support:
                left, right = roles[row["left_feature_id"]], roles[row["right_feature_id"]]
                if row.get("left_species") and left["species_id"] != row["left_species"]:
                    valid = False
                if row.get("right_species") and right["species_id"] != row["right_species"]:
                    valid = False
                if row["kind"] == "isotope" and not (
                    left["isotope_shift"] == 0 and right["isotope_shift"] > 0
                ):
                    valid = False
            if valid:
                hypotheses.append(hypothesis)
        signatures = {
            tuple(
                (f, role["species_id"], role["isotope_shift"])
                for f, role in sorted(h["members"].items())
            )
            for h in hypotheses
        }
        if len(signatures) != 1:
            continue
        chosen = min(hypotheses, key=lambda h: h["hypothesis_id"])
        selections.append(
            {
                "ec_id": group["ec_id"],
                "hypothesis_id": chosen["hypothesis_id"],
                "review": "rule_supported",
                "relation_ids": [r["relation_id"] for r in support],
            }
        )
    reviews = {row["relation_id"]: "rule_supported" for row in eligible}
    return build_representations(
        data,
        grouping,
        selections,
        relation_reviews=reviews,
        decision_mode="exploratory_v1",
        **options,
    )
