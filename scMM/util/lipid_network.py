"""Sample-wise correlation and non-recursive chemical support for MS1 candidates."""
# ruff: noqa: RUF001

import hashlib
import json
from itertools import combinations

import numpy as np
from scipy.stats import rankdata

from .intensity import intensity_states
from .normalize import normalize

DEFAULTS = {
    "method": "spearman",
    "support_all": 0.8,
    "support_joint": 0.7,
    "min_joint_cells": 30,
    "plot_threshold": 0.7,
    "consensus_fraction": 2 / 3,
    "min_support_samples": 2,
    "condition_field": "",
    "samples": [],
    "conditions": [],
    "molecule_layer": "total",
}


def network_parameters(parameters):
    value = {**DEFAULTS, **parameters.get("network", {})}
    for key in ("support_all", "support_joint", "plot_threshold", "consensus_fraction"):
        if not np.isfinite(value[key]) or not 0 <= value[key] <= 1:
            raise ValueError(f"{key} 需在 0 到 1 之间。")
    for key in ("min_joint_cells", "min_support_samples"):
        if isinstance(value[key], bool) or int(value[key]) != value[key] or value[key] < 2:
            raise ValueError(f"{key} 需为至少 2 的整数。")
    if value["method"] not in {"spearman", "pearson"}:
        raise ValueError("method 仅支持 spearman 或 pearson。")
    return value


def sample_conditions(data, samples, options):
    group_key = next((k for k in ("sample_id", "sample", "source_file") if k in data.obs), "")
    if group_key:
        values = data.obs[group_key]
        if values.isna().any() or (values.astype(str).str.strip() == "").any():
            raise ValueError("样本身份存在缺失值，请先明确样本映射。")
    field = options["condition_field"]
    mapping = {}
    if field:
        if field not in data.obs:
            raise ValueError("condition_field 不存在。")
        for sample in dict.fromkeys(samples):
            values = data.obs.loc[samples == sample, field]
            if values.isna().any() or (values.astype(str).str.strip() == "").any():
                raise ValueError("所选条件字段有缺失值，请先完善样本分组。")
            unique = values.astype(str).unique()
            if len(unique) != 1:
                raise ValueError("同一 sample_id 内的条件必须唯一，请选择样本级条件字段。")
            mapping[str(sample)] = str(unique[0])
    elif options["conditions"]:
        raise ValueError("请先明确选择 condition_field。")
    unknown = set(options["samples"]) - set(samples)
    if unknown or set(options["conditions"]) - set(mapping.values()):
        raise ValueError("样本或条件范围包含不存在的值。")
    selected = [
        str(s)
        for s in dict.fromkeys(samples)
        if (not options["samples"] or s in options["samples"])
        and (not options["conditions"] or mapping.get(str(s)) in options["conditions"])
    ]
    if not selected:
        raise ValueError("相关性分析范围中没有样本。")
    return mapping, selected


def intensity_layers(data):
    """Only offer layers with known untransformed or normalization-only provenance."""
    states = intensity_states(data)
    return {
        "raw": [k for k, v in states.items() if v == "raw" and (k == "X" or k in data.layers)],
        "molecule": [k for k, v in states.items() if v in {"raw", "normalized"}],
    }


def network_inputs(data, raw, samples, options, raw_layer):
    mapping, selected = sample_conditions(data, samples, options)
    layer = options["molecule_layer"]
    if layer == "total":
        molecular = normalize(raw, method="total")
    else:
        if layer not in intensity_layers(data)["molecule"]:
            raise ValueError("分子网络需选择有未插补强度溯源的层。")
        matrix = data.X if layer == "X" else data.layers[layer]
        molecular = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
        if not np.isfinite(molecular).all() or (molecular < 0).any():
            raise ValueError("分子网络强度必须为有限非负值。")
    digest = hashlib.sha256()
    digest.update(json.dumps([options, mapping, selected, raw_layer], sort_keys=True).encode())
    digest.update(np.ascontiguousarray(molecular, dtype="<f8").tobytes())
    return molecular, mapping, selected, digest.hexdigest()


def correlation_matrix(values, method):
    """Rank ties within each sample. Constant columns produce NaN without warnings."""
    array = rankdata(values, axis=0) if method == "spearman" else np.asarray(values, dtype=float)
    centered = array - array.mean(axis=0)
    norms = np.sqrt(np.sum(centered * centered, axis=0))
    unit = np.divide(centered, norms, out=np.zeros_like(centered), where=norms > 0)
    result = np.clip(unit.T @ unit, -1, 1)
    result[norms == 0, :] = np.nan
    result[:, norms == 0] = np.nan
    return result


def pair_statistics(values, detected, i, j, all_rho, options):
    joint = detected[:, i] & detected[:, j]
    count = int(joint.sum())
    joint_rho = None
    reason = ""
    if count < options["min_joint_cells"]:
        reason = "共同检出不足"
    else:
        joint_value = correlation_matrix(values[joint][:, [i, j]], options["method"])[0, 1]
        if np.isfinite(joint_value):
            joint_rho = float(joint_value)
        else:
            reason = "共同检出向量为常数"
    if not np.isfinite(all_rho):
        reason = "全细胞向量为常数"
    evaluable = not reason
    rho = float(all_rho) if np.isfinite(all_rho) else None
    return {
        "rho_all": rho,
        "rho_joint": joint_rho,
        "joint_cells": count,
        "joint_fraction": count / len(values),
        "cells": len(values),
        "evaluable": evaluable,
        "reason": reason,
        "supported": bool(
            evaluable and rho >= options["support_all"] and joint_rho >= options["support_joint"]
        ),
    }


def consensus(rows, mapping, options):
    result = []
    for condition in dict.fromkeys(mapping.values()):
        available = [r for r in rows if mapping.get(r["sample"]) == condition and r["evaluable"]]
        supported = [r["sample"] for r in available if r["supported"]]
        fraction = len(supported) / len(available) if available else None
        signs = {np.sign(r["rho_all"]) for r in available if r["rho_all"]}
        result.append(
            {
                "condition": condition,
                "evaluable_samples": len(available),
                "support_samples": supported,
                "support_fraction": fraction,
                "replicate_support": bool(
                    len(supported) >= options["min_support_samples"]
                    and fraction >= options["consensus_fraction"]
                ),
                "direction_conflict": len(signs) > 1,
                "inconsistent": bool(supported and len(supported) < len(available)),
            }
        )
    return result


def chemical_links(candidates, relations, parameters):
    groups, links = {}, []
    for row in candidates:
        groups.setdefault(row["database_id"], []).append(row)
    for rows in groups.values():
        for a, b in combinations(rows, 2):
            if a["feature_id"] == b["feature_id"] or a["adduct"] == b["adduct"]:
                continue
            # Each ion has already passed annotation_ppm against this DB mass;
            # these two theoretical ion masses therefore define the adduct relation.
            links.append(
                {
                    "source": a["feature_id"],
                    "target": b["feature_id"],
                    "type": "adduct",
                    "candidate_ids": sorted([a["candidate_id"], b["candidate_id"]]),
                    "theoretical_delta": b["theoretical_mz"] - a["theoretical_mz"],
                }
            )
    # Collapse isotope fine components to one candidate/pair; keep per-sample ratio checks.
    isotopes = {}
    for row in relations:
        key = row["parent_candidate_id"], row["parent_feature_id"], row["isotope_feature_id"]
        link = isotopes.setdefault(
            key,
            {
                "source": key[1],
                "target": key[2],
                "type": "isotope",
                "candidate_ids": [key[0]],
                "matched_samples": [],
                "evaluable_samples": [],
                "relation_ids": [],
            },
        )
        link["relation_ids"].append(row["relation_id"])
        if (
            row["valid_cells"] >= parameters["min_valid_cells"]
            and row["observed_ratio"] is not None
            and row["sample"] not in link["evaluable_samples"]
        ):
            link["evaluable_samples"].append(row["sample"])
        if (
            row["matched"]
            and row["review"] != "rejected"
            and row["sample"] not in link["matched_samples"]
        ):
            link["matched_samples"].append(row["sample"])
    return links + list(isotopes.values())


def calculate_network(values, raw, ids, samples, selected, options, required=()):
    """Store statistics for visible edges and all chemical pairs; no display cap here."""
    indices = {f: i for i, f in enumerate(ids)}
    required_pairs = {tuple(sorted((indices[a], indices[b]))) for a, b in required}
    results = {}
    for sample in selected:
        subset = samples == sample
        array = values[subset]
        detected = raw[subset] > 0
        correlations = correlation_matrix(array, options["method"])
        visible = np.argwhere(np.triu(np.abs(correlations) >= options["plot_threshold"], k=1))
        pairs = required_pairs | {tuple(pair) for pair in visible}
        for i, j in sorted(pairs):
            stats = pair_statistics(array, detected, i, j, correlations[i, j], options)
            results.setdefault((ids[i], ids[j]), []).append({"sample": sample, **stats})
    # Complete all sample evidence for any displayed pair, including non-supporting samples.
    # Cached correlations avoid recalculating joint ranks for omitted below-threshold pairs.
    for sample in selected:
        missing = [
            pair for pair, rows in results.items() if not any(r["sample"] == sample for r in rows)
        ]
        if not missing:
            continue
        subset = samples == sample
        array, detected = values[subset], raw[subset] > 0
        correlations = correlation_matrix(array, options["method"])
        for pair in missing:
            i, j = (indices[f] for f in pair)
            results[pair].append(
                {
                    "sample": sample,
                    **pair_statistics(array, detected, i, j, correlations[i, j], options),
                }
            )
    return [{"source": a, "target": b, "samples": rows} for (a, b), rows in results.items()]


def apply_support(version):
    network = version.get("network")
    if not network:
        return
    links = chemical_links(version["candidates"], version["relations"], version["parameters"])
    by_pair = {tuple(sorted((e["source"], e["target"]))): e for e in network["feature_edges"]}
    by_candidate = {}
    for link in links:
        edge = by_pair[tuple(sorted((link["source"], link["target"])))]
        rows = [dict(row) for row in edge["samples"]]
        for row in rows:
            chemical = link["type"] == "adduct" or row["sample"] in link["matched_samples"]
            if link["type"] == "isotope" and row["sample"] not in link["evaluable_samples"]:
                row["evaluable"] = False
                row["reason"] = row["reason"] or "同位素比例有效细胞不足"
                row["supported"] = False
            row["chemical_matched"] = chemical
            row["supported"] = row["supported"] and chemical
        summary = consensus(rows, network["conditions"], network["parameters"])
        link.update(samples=rows, consensus=summary)
        link["level"] = (
            2
            if any(c["replicate_support"] for c in summary)
            else int(any(r["supported"] for r in rows))
        )
        for candidate in link["candidate_ids"]:
            by_candidate.setdefault(candidate, []).append(link)
    # Direct formula/adduct observations cannot distinguish same-formula isomers.
    # Share these observations only at the same measured feature; never recurse.
    equivalent, candidate_keys = {}, {}
    for row in version["candidates"]:
        key = row["feature_id"], row["formula"], row["adduct"]
        candidate_keys[row["candidate_id"]] = key
        equivalent.setdefault(key, []).append(row["candidate_id"])
    for link in links:
        link["equivalent_candidate_ids"] = sorted(
            {
                candidate
                for identity in link["candidate_ids"]
                for candidate in equivalent[candidate_keys[identity]]
            }
        )
    shared = {}
    for identity, evidence in by_candidate.items():
        shared.setdefault(candidate_keys[identity], []).extend(evidence)
    network["chemical_links"] = links
    for row in version["candidates"]:
        evidence = shared.get(candidate_keys[row["candidate_id"]], [])
        row["network_level"] = max((e["level"] for e in evidence), default=0)
        row["network_inconsistent"] = any(
            c["inconsistent"] or c["direction_conflict"] for e in evidence for c in e["consensus"]
        )
        row["network_samples"] = sorted(
            {r["sample"] for e in evidence for r in e["samples"] if r["supported"]}
        )
        row["network_relations"] = sorted({e["type"] for e in evidence if e["level"]})


def build_network(data, version, raw, ids, samples):
    options = network_parameters(version["parameters"])
    molecular, mapping, selected, identity = network_inputs(
        data, raw, samples, options, version["intensity_layer"]
    )
    links = chemical_links(version["candidates"], version["relations"], version["parameters"])
    edges = calculate_network(
        raw,
        raw,
        ids,
        samples,
        selected,
        options,
        [(link["source"], link["target"]) for link in links],
    )
    molecular_edges = calculate_network(molecular, raw, ids, samples, selected, options)
    # Representative selection always uses every sample with equal weight, not the display scope.
    sample_values = [raw[samples == s] for s in dict.fromkeys(samples)]
    detection = np.mean([(v > 0).mean(axis=0) for v in sample_values], axis=0)
    intensity = np.mean([v.mean(axis=0) for v in sample_values], axis=0)
    return {
        "schema_version": 1,
        "parameters": options,
        "input_identity": identity,
        "conditions": mapping,
        "sample_field": next(
            (k for k in ("sample_id", "sample", "source_file") if k in data.obs), "单样本"
        ),
        "samples": selected,
        "feature_layer": version["intensity_layer"] or "X",
        "molecule_layer": f"total({version['intensity_layer'] or 'X'}; full features)"
        if options["molecule_layer"] == "total"
        else options["molecule_layer"],
        "feature_edges": edges,
        "molecule_edges": molecular_edges,
        "representative_metrics": {
            f: {"detection_rate": float(d), "mean_raw": float(m)}
            for f, d, m in zip(ids, detection, intensity, strict=True)
        },
        "representatives": {},
        "view": {},
    }
