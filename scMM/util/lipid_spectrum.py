"""Read-only feature spectra and atomic, audited annotation-group assertions."""

import hashlib
import json
from collections import deque
from copy import deepcopy

import numpy as np


def _candidate_identity(row):
    source = row.get("database_sha256")
    record_id = row.get("database_record_id")
    return f"{source}:{record_id}" if source and record_id else row["database_id"]


def make_adduct_relations(candidates):
    from .lipid_network import chemical_links

    result = []
    for link in chemical_links(candidates, [], {}):
        identity = json.dumps(sorted(link["candidate_ids"]))
        result.append(
            {
                **link,
                "relation_id": "adduct-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                "review": "pending",
            }
        )
    return result


def spectrum_relations(version, sample=""):
    rows = []
    for row in version.get("relations", []):
        if sample and row["sample"] != sample:
            continue
        rows.append(
            {
                **row,
                "id": row["relation_id"],
                "source": row["parent_feature_id"],
                "target": row["isotope_feature_id"],
                "type": "isotope",
                "candidate_ids": [row["parent_candidate_id"]],
            }
        )
    adducts = version.get("adduct_relations")
    if adducts is None:
        adducts = make_adduct_relations(version["candidates"])
    for row in adducts:
        rows.append({**row, "id": row["relation_id"]})
    for row in version.get("catalog_relations", []):
        rows.append({**row, "id": row["relation_id"]})
    return rows


def connected_features(version, feature, *, accepted_only=False, sample="", database_ids=None):
    links = spectrum_relations(version, sample)
    candidate_database_ids = {
        row["candidate_id"]: _candidate_identity(row) for row in version["candidates"]
    }
    adjacency = {}
    for row in links:
        if row.get("review") == "rejected" or (accepted_only and row.get("review") != "accepted"):
            continue
        identities = {
            candidate_database_ids[c]
            for c in row.get("candidate_ids", [])
            if c in candidate_database_ids
        }
        if database_ids is not None and not identities.intersection(database_ids):
            continue
        adjacency.setdefault(row["source"], []).append(row["target"])
        adjacency.setdefault(row["target"], []).append(row["source"])
    found, queue = {feature}, deque([feature])
    while queue:
        for member in adjacency.get(queue.popleft(), []):
            if member not in found:
                found.add(member)
                queue.append(member)
    return sorted(found)


def _review_snapshot(version):
    return deepcopy(
        {
            key: version.get(key, default)
            for key, default in (
                ("selected", {}),
                ("reviewed_features", []),
                ("annotation_names", {}),
                ("linked_annotations", {}),
                ("review_conflicts", []),
            )
        }
    )


def apply_review(version, values, feature_ids, *, reviewer, timestamp):
    """Mutate a transaction candidate only; physical measurements remain untouched."""
    before = _review_snapshot(version)
    version.setdefault("annotation_names", {})
    version.setdefault("linked_annotations", {})
    version.setdefault("review_conflicts", [])
    version.setdefault("adduct_relations", make_adduct_relations(version["candidates"]))
    feature = values.get("feature_id")
    relation_id = values.get("relation_id")
    relation_before = None
    if relation_id is not None:
        row = next(
            (
                row
                for key in ("relations", "adduct_relations", "catalog_relations")
                for row in version.get(key, [])
                if row["relation_id"] == relation_id
            ),
            None,
        )
        if row is None:
            raise ValueError("所选同位素或加合关系不存在。")
        relation_before = row.get("review", "pending")
        row["review"] = values["review"]
    affected = []
    if feature is not None:
        if feature not in feature_ids:
            raise ValueError("所选特征不存在。")
        candidates = version["candidates"]
        valid = {r["candidate_id"]: r for r in candidates if r["feature_id"] == feature}
        chosen = values.get("candidate_ids")
        if chosen is not None and not set(chosen) <= valid.keys():
            raise ValueError("所选候选不属于该特征。")
        chosen = list(dict.fromkeys(chosen)) if chosen is not None else None
        # Shared isotope peaks must not join unrelated candidate families.
        by_id = {r["candidate_id"]: r for r in candidates}
        incident_identities = {
            _candidate_identity(by_id[c])
            for relation in spectrum_relations(version)
            if relation.get("review") == "accepted"
            and feature in {relation["source"], relation["target"]}
            for c in relation.get("candidate_ids", [])
            if c in by_id
        }
        chosen_identities = {_candidate_identity(valid[c]) for c in chosen or []}
        previous_identities = {
            _candidate_identity(row) for row in _effective_candidates(version, feature)
        }
        group_identities = incident_identities & (chosen_identities or previous_identities)
        if not group_identities and len(incident_identities) == 1:
            group_identities = incident_identities
        affected = (
            connected_features(version, feature, accepted_only=True, database_ids=group_identities)
            if values.get("sync_related", True)
            else [feature]
        )
        database_ids = {valid[c]["database_id"] for c in chosen or []}
        by_feature = {}
        for row in candidates:
            by_feature.setdefault(row["feature_id"], []).append(row)
        for member in affected:
            if member == feature:
                if chosen is None:
                    version["selected"].pop(member, None)
                else:
                    version["selected"][member] = chosen
                version["linked_annotations"].pop(member, None)
            elif chosen is None:
                version["selected"].pop(member, None)
                version["linked_annotations"].pop(member, None)
            else:
                matched = [
                    r["candidate_id"]
                    for r in by_feature.get(member, [])
                    if r["database_id"] in database_ids
                ]
                if matched or not chosen:
                    version["selected"][member] = matched
                elif member in by_feature:
                    version["review_conflicts"].append(
                        {
                            "feature_id": member,
                            "source_feature_id": feature,
                            "reason": "No corresponding candidate at this related feature; prior selection retained",
                            "candidate_ids": chosen,
                        }
                    )
                version["linked_annotations"][member] = {
                    "source_feature_id": feature,
                    "candidate_ids": chosen,
                    "family_database_ids": sorted(group_identities),
                    "basis": "manual_group_assertion_not_independent_identification",
                }
                if values.get("annotation_name") is not None:
                    version["linked_annotations"][member]["annotation_name"] = values[
                        "annotation_name"
                    ].strip()
            if values.get("annotation_name") is not None:
                name = values["annotation_name"].strip()
                if name:
                    version["annotation_names"][member] = name
                else:
                    version["annotation_names"].pop(member, None)
            if member not in version["reviewed_features"]:
                version["reviewed_features"].append(member)
    if feature is None and relation_id is None:
        raise ValueError("请选择候选或同位素/加合关系。")
    for member, assertion in list(version["linked_annotations"].items()):
        still_linked = connected_features(
            version,
            assertion["source_feature_id"],
            accepted_only=True,
            database_ids=set(assertion.get("family_database_ids", [])),
        )
        if member not in still_linked:
            del version["linked_annotations"][member]
            inherited_name = assertion.get("annotation_name")
            if inherited_name and version["annotation_names"].get(member) == inherited_name:
                del version["annotation_names"][member]
            if member not in affected:
                affected.append(member)
            version["review_conflicts"].append(
                {
                    "feature_id": member,
                    "reason": "Reviewed relation changed; disconnected inherited display assertion removed",
                    "source_feature_id": assertion["source_feature_id"],
                }
            )
    audit = {
        "reviewer": reviewer,
        "timestamp": timestamp,
        "feature_id": feature,
        "relation_id": relation_id,
        "relation_before": relation_before,
        "relation_after": values.get("review") if relation_id is not None else None,
        "sync_related": values.get("sync_related", True),
        "affected_features": affected,
        "before": before,
        "after": _review_snapshot(version),
    }
    version.setdefault("audit", []).append(audit)


def inherit_reviews(previous, version):
    """Carry exact matching assertions forward and expose unmapped decisions as conflicts."""
    if previous.get("input_identity") != version["input_identity"]:
        return
    candidate_ids = {row["candidate_id"] for row in version["candidates"]}
    features = {row["feature_id"] for row in version["candidates"]}
    for feature, selected in previous.get("selected", {}).items():
        missing = set(selected) - candidate_ids
        if missing:
            version["review_conflicts"].append(
                {
                    "feature_id": feature,
                    "source_version": previous["id"],
                    "candidate_ids": list(selected),
                    "reason": "Previously reviewed candidates are absent from this search; no replacement inferred",
                }
            )
        else:
            version["selected"][feature] = list(selected)
    for key in ("annotation_names", "linked_annotations"):
        version[key] = deepcopy(previous.get(key, {}))
    current_candidates = {row["candidate_id"]: row for row in version["candidates"]}
    family_mapping = {
        _candidate_identity(row): _candidate_identity(current_candidates[row["candidate_id"]])
        for row in previous["candidates"]
        if row["candidate_id"] in current_candidates
    }
    for assertion in version["linked_annotations"].values():
        assertion["family_database_ids"] = sorted(
            {
                family_mapping.get(identity, identity)
                for identity in assertion.get("family_database_ids", [])
            }
        )
    version["reviewed_features"] = [
        f
        for f in previous.get("reviewed_features", [])
        if f in features or f in version["annotation_names"] or f in version["linked_annotations"]
    ]
    previous_relations = {
        row["relation_id"]: row.get("review", "pending")
        for key in ("relations", "adduct_relations", "catalog_relations")
        for row in previous.get(key, [])
    }
    for key in ("relations", "adduct_relations", "catalog_relations"):
        for row in version.get(key, []):
            row["review"] = previous_relations.get(row["relation_id"], row.get("review", "pending"))
    for member, assertion in list(version["linked_annotations"].items()):
        if not set(assertion["candidate_ids"]) <= candidate_ids:
            version["review_conflicts"].append(
                {
                    "feature_id": member,
                    "source_version": previous["id"],
                    "reason": "Previous group assertion has unmapped candidates; retained in source version",
                    "candidate_ids": assertion["candidate_ids"],
                }
            )
            del version["linked_annotations"][member]
    version["inherited_from"] = previous["id"]
    version["audit"] = deepcopy(previous.get("audit", []))


def _effective_candidates(version, feature):
    rows = [r for r in version["candidates"] if r["feature_id"] == feature]
    selected = version["selected"].get(feature)
    return (
        [r for r in rows if r["candidate_id"] in selected]
        if selected is not None
        else [r for r in rows if r["top_ranked"]]
    )


def _spectrum_family_ids(version, feature, relations):
    by_id = {r["candidate_id"]: r for r in version["candidates"]}
    chosen = _effective_candidates(version, feature)
    if not chosen:
        chosen = [
            by_id[c]
            for c in version.get("linked_annotations", {}).get(feature, {}).get("candidate_ids", [])
            if c in by_id
        ]
    identities = {_candidate_identity(row) for row in chosen}
    incident = {
        _candidate_identity(by_id[c])
        for relation in relations
        if feature in {relation["source"], relation["target"]}
        and relation.get("review") != "rejected"
        for c in relation.get("candidate_ids", [])
        if c in by_id
    }
    return (identities & incident) or (incident if len(incident) == 1 else identities or None)


def _related_roles(version, feature, relations, families):
    by_id = {r["candidate_id"]: r for r in version["candidates"]}
    adjacency = {}
    for relation in relations:
        if relation.get("review") == "rejected":
            continue
        identities = {
            _candidate_identity(by_id[c]) for c in relation.get("candidate_ids", []) if c in by_id
        }
        if families is not None and not identities.intersection(families):
            continue
        for left, right in (
            (relation["source"], relation["target"]),
            (relation["target"], relation["source"]),
        ):
            adjacency.setdefault(left, []).append((right, relation["type"]))
    roles, queue = {feature: "selected"}, deque([feature])
    while queue:
        for member, kind in adjacency.get(queue.popleft(), []):
            if member not in roles:
                roles[member] = kind
                queue.append(member)
    return roles


def _spectrum_annotation(
    row, *, role="candidate", relation=None, adduct=None, manual=False, input_identity=None
):
    from .lipid_evidence import ms2_status

    relation = relation or {}
    return {
        "candidate_id": row["candidate_id"],
        "source_feature_id": row["feature_id"],
        "name": row["name"],
        "display_name": row["name"],
        "source_name": row["name"],
        "adduct": row["adduct"] if adduct is None else adduct,
        "isotope_order": relation.get("order", 0),
        "annotation_role": role,
        "relation_id": relation.get("id"),
        "relation_review": relation.get("review"),
        "manual_group_assertion": manual,
        **{
            key: row.get(key, "not_supplied" if key == "ms2_status" else "")
            for key in (
                "database_id",
                "database_record_id",
                "database_sha256",
                "database_source",
                "database_filename",
                "ms2_status",
            )
        },
        "ms2_evidence": deepcopy(row.get("ms2_evidence", [])),
        "ms2_status": ms2_status(row, input_identity=input_identity),
    }


def measured_spectrum(data, *, sample="", layer=""):
    """Read the complete peak axis without requiring a candidate version."""
    from scipy.sparse import issparse

    from .intensity import intensity_states
    from .lipid_annotation import feature_axis, feature_only, feature_samples

    ids, masses = feature_axis(data)
    missing = feature_only(data)
    layer = layer or "X"
    value_state = intensity_states(data).get(layer, "unknown")
    selected = feature_samples(data) == sample if sample else slice(None)
    count = data.n_obs if not sample else int(selected.sum())
    if sample and not count:
        raise ValueError("所选样本不存在或未提供定量数据。")
    relative = False
    intensities = [None] * len(ids)
    if not missing:
        if not count:
            raise ValueError("所选样本不存在。")
        values = data.X if layer == "X" else data.layers[layer]
        if sample:
            values = values[selected]
        explicit_values = values.data if issparse(values) else np.asarray(values)
        if not np.isfinite(explicit_values).all():
            raise ValueError("特征谱需要有限矩阵数值。")
        intensities = np.asarray(values.mean(axis=0)).ravel().tolist()
        relative = value_state in {"raw", "normalized"} and bool((explicit_values >= 0).all())
    return {
        "spectrum_kind": "feature_sticks",
        "intensity_label": "Intensity not supplied"
        if missing
        else "Mean intensity"
        if value_state == "raw"
        else "Mean matrix value",
        "intensity_missing": missing,
        "relative_intensity_allowed": relative,
        "intensity_source": {
            "layer": layer,
            "aggregation": "mean_over_observations",
            "sample": sample,
            "quantitation_available": not missing,
            "observation_count": count,
            "value_state": value_state,
            "kind": "not_supplied"
            if missing
            else "intensity"
            if value_state == "raw"
            else "matrix_values",
        },
        "peaks": [
            {"feature_id": feature, "mz": float(mz), "intensity": intensity}
            for feature, mz, intensity in zip(ids, masses, intensities, strict=True)
        ],
    }


def spectrum_overlay(version, ids, *, feature_id="", sample=""):
    if feature_id and feature_id not in ids:
        raise ValueError("所选特征不存在。")
    relations = spectrum_relations(version, sample)
    families = _spectrum_family_ids(version, feature_id, relations) if feature_id else None
    roles = _related_roles(version, feature_id, relations, families) if feature_id else {}
    linked = sorted(roles)
    confirmed = (
        connected_features(
            version, feature_id, accepted_only=True, sample=sample, database_ids=families or set()
        )
        if feature_id
        else []
    )
    by_candidate = {r["candidate_id"]: r for r in version["candidates"]}
    effective = {}
    counts = {}
    names = {}
    reviewed = set(version.get("reviewed_features", []))
    for row in version["candidates"]:
        counts[row["feature_id"]] = counts.get(row["feature_id"], 0) + 1
        names.setdefault(row["feature_id"], set()).add(row["name"])
        selection = version["selected"].get(row["feature_id"])
        if (selection is not None and row["candidate_id"] in selection) or (
            selection is None and row["top_ranked"]
        ):
            effective.setdefault(row["feature_id"], []).append(row)
    effective_ids = {r["candidate_id"] for rows in effective.values() for r in rows}
    isotopes = {}
    for relation in sorted(relations, key=lambda r: r.get("review") != "accepted"):
        if relation["type"] == "isotope" and relation.get("review") != "rejected":
            isotopes.setdefault(relation["target"], []).append(relation)
    peaks = []
    for feature in ids:
        candidates = effective.get(feature, [])
        annotations = [
            _spectrum_annotation(row, input_identity=version["input_identity"])
            for row in candidates
        ]
        inherited = version.get("linked_annotations", {}).get(feature, {})
        inherited_rows = [
            by_candidate[c] for c in inherited.get("candidate_ids", []) if c in by_candidate
        ]
        for relation in isotopes.get(feature, []):
            candidate_id = relation.get("parent_candidate_id")
            if candidate_id in effective_ids:
                row = by_candidate[candidate_id]
                annotation = _spectrum_annotation(
                    row, role="isotope", relation=relation, input_identity=version["input_identity"]
                )
                parent_name = version.get("annotation_names", {}).get(row["feature_id"])
                if parent_name:
                    annotation["name"] = parent_name
                    annotation["display_name"] = parent_name
                annotations.append(annotation)
        for row in inherited_rows:
            isotope = next(
                (r for r in isotopes.get(feature, []) if r["review"] == "accepted"), None
            )
            if isotope:
                actual_adduct = (
                    isotope.get("adduct") or isotope.get("right_species") or row["adduct"]
                )
                actual_parent = next(
                    (
                        candidate
                        for candidate in effective.get(isotope["source"], [])
                        if candidate["database_id"] == row["database_id"]
                        and candidate["adduct"] == actual_adduct
                    ),
                    row,
                )
                annotation = _spectrum_annotation(
                    actual_parent,
                    role="isotope",
                    relation=isotope,
                    adduct=actual_adduct,
                    manual=True,
                    input_identity=version["input_identity"],
                )
                annotation["assertion_source_feature_id"] = inherited["source_feature_id"]
                annotation["source_feature_id"] = isotope["source"]
                annotations.append(annotation)
            elif not any(
                candidate["database_id"] == row["database_id"] for candidate in candidates
            ):
                member_adducts = {
                    by_candidate[c]["adduct"]
                    for relation in relations
                    if relation.get("review") == "accepted"
                    and feature in {relation["source"], relation["target"]}
                    for c in relation.get("candidate_ids", [])
                    if c in by_candidate and by_candidate[c]["feature_id"] == feature
                }
                member_adduct = next(iter(member_adducts)) if len(member_adducts) == 1 else ""
                annotations.append(
                    _spectrum_annotation(
                        row,
                        role="related",
                        adduct=member_adduct,
                        manual=True,
                        input_identity=version["input_identity"],
                    )
                )
        override = version.get("annotation_names", {}).get(feature)
        inherited_identities = {_candidate_identity(row) for row in inherited_rows}
        unique_annotations = {}
        for annotation in annotations:
            source_row = by_candidate[annotation["candidate_id"]]
            if override and (
                not inherited_rows or _candidate_identity(source_row) in inherited_identities
            ):
                annotation["name"] = override
                annotation["display_name"] = override
            key = annotation["candidate_id"], annotation["adduct"], annotation["isotope_order"]
            if key not in unique_annotations or annotation["manual_group_assertion"]:
                unique_annotations[key] = annotation
        annotations = list(unique_annotations.values())
        descriptions = [
            f"{row['name']} {row['adduct']}"
            + (f" M+{row['isotope_order']}" if row["isotope_order"] else "")
            for row in annotations
        ]
        if not descriptions and override:
            descriptions = [override]
        statuses = {r["ms2_status"] for r in annotations}
        ms2 = (
            (next(iter(statuses)) if len(statuses) == 1 else "mixed")
            if statuses
            else version["database"].get("ms2_status", "not_supplied")
        )
        peaks.append(
            {
                "feature_id": feature,
                "label": "; ".join(dict.fromkeys(descriptions)),
                "role": roles.get(feature, "unrelated"),
                "candidate_ids": [r["candidate_id"] for r in candidates],
                "candidate_count": counts.get(feature, 0),
                "candidate_names": sorted(names.get(feature, ())),
                "reviewed": feature in reviewed,
                "ms2_status": ms2,
                "annotations": annotations,
            }
        )
    return {
        "version": version["id"],
        "review_revision": version.get("review_revision", 0),
        "peaks": peaks,
        "relations": relations,
        "selected_feature_id": feature_id,
        "linked_feature_ids": linked,
        "confirmed_linked_feature_ids": confirmed,
        "annotation_names": deepcopy(version.get("annotation_names", {})),
        "database": version["database"],
        "review_conflicts": deepcopy(version.get("review_conflicts", [])),
        "audit": deepcopy(version.get("audit", [])),
    }


def annotation_spectrum(data, version, *, feature_id="", sample=""):
    axis = measured_spectrum(data, sample=sample, layer=version["intensity_layer"])
    overlay = spectrum_overlay(version, data.var_names, feature_id=feature_id, sample=sample)
    result = {**axis, **overlay, "mass_only": version.get("mass_only", False)}
    result["peaks"] = [
        {**peak, **label} for peak, label in zip(axis["peaks"], overlay["peaks"], strict=True)
    ]
    if result["mass_only"] and not axis["intensity_missing"]:
        result["intensity_label"] = "Mean matrix value"
        result["intensity_source"]["kind"] = "matrix_values"
    return result
