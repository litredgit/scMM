"""Review-aware projections of saved lipid network evidence (no matrix mutation)."""

from collections import Counter

from .lipid_network import consensus

VIEW_DEFAULTS = {
    "classification_level": "MAIN_CLASS",
    "graph": "feature",
    "scope": "",
    "sign": "both",
    "node_limit": 100,
    "search": "",
    "category": "",
    "focus": "",
}


def effective_candidates(version, rows=None):
    rows = version["candidates"] if rows is None else rows
    return [
        r
        for r in rows
        if r["feature_id"] not in version["selected"]
        or r["candidate_id"] in version["selected"][r["feature_id"]]
    ]


def molecule_mapping(version):
    groups = {}
    for row in effective_candidates(version):
        groups.setdefault(row["feature_id"], []).append(row)
    mapping = {}
    for feature, rows in groups.items():
        identities = {r["database_id"] for r in rows}
        if len(identities) == 1:
            mapping[feature] = rows[0]["database_id"]
    return mapping


def representatives(version):
    mapping = molecule_mapping(version)
    groups = {}
    for feature, identity in mapping.items():
        groups.setdefault(identity, []).append(feature)
    network = version["network"]
    metrics = network["representative_metrics"]
    selected = {}
    for identity, features in groups.items():
        manual = network["representatives"].get(identity)
        selected[identity] = (
            manual
            if manual in features
            else max(
                features, key=lambda f: (metrics[f]["detection_rate"], metrics[f]["mean_raw"], f)
            )
        )
    return mapping, groups, selected


def annotation_charts(version, feature_ids, mz, candidate_rows, filters, view=None):
    network = version.get("network")
    options = {**VIEW_DEFAULTS, **(network or {}).get("view", {}), **(view or {})}
    rows = effective_candidates(version, candidate_rows)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["feature_id"], []).append(row)
    level = options["classification_level"]
    counts = Counter()
    nodes = []
    for feature in feature_ids:
        candidates = grouped.get(feature, [])
        classes = {r.get(level) or "未分类" for r in candidates}
        classification = (
            next(iter(classes)) if len(classes) == 1 else "多义" if classes else "未注释"
        )
        counts[classification] += 1
        nodes.append(
            {
                "id": feature,
                "feature_id": feature,
                "mz": float(mz[feature]),
                "label": "; ".join(dict.fromkeys(r["name"] for r in candidates)) or "未注释",
                "classification": classification,
                "candidate_ids": [r["candidate_id"] for r in candidates],
                "review": "人工指定"
                if feature in version["selected"]
                else "已审阅"
                if feature in version["reviewed_features"]
                else "待审核",
            }
        )
    pie = {
        "level": level,
        "denominator": len(feature_ids),
        "unit": "特征数",
        "counts": [
            {"classification": key, "count": value} for key, value in sorted(counts.items())
        ],
        "candidate_mode": filters.get("candidates", "all"),
        "filters": filters,
        "manual_priority": True,
    }
    if not network:
        return {"pie": pie, "network": None, "options": options}
    mapping, groups, chosen = representatives(version)
    molecule_nodes = []
    visible_features = set(feature_ids)
    all_rows = {r["candidate_id"]: r for r in version["candidates"]}
    for identity, features in groups.items():
        representative = chosen[identity]
        # Fixed representative may lie outside the feature filter; do not replace it.
        visible = [f for f in features if f in visible_features]
        if not visible:
            continue
        candidate = next(
            r for r in effective_candidates(version) if r["feature_id"] == representative
        )
        molecule_nodes.append(
            {
                "id": identity,
                "feature_id": representative,
                "mz": float(candidate["query_mz"]),
                "label": candidate["name"],
                "classification": candidate.get(level) or "未分类",
                "features": features,
                "representative_manual": network["representatives"].get(identity) == representative,
                **network["representative_metrics"][representative],
            }
        )
    is_molecule = options["graph"] == "molecule"
    source_nodes = molecule_nodes if is_molecule else nodes
    scope = options["scope"] or (f"sample:{network['samples'][0]}" if network["samples"] else "")
    valid_scopes = [f"sample:{s}" for s in network["samples"]] + [
        f"condition:{c}"
        for c in dict.fromkeys(
            network["conditions"][s] for s in network["samples"] if s in network["conditions"]
        )
    ]
    if scope not in valid_scopes:
        raise ValueError("网络 scope 不属于本版本分析范围。")
    source_edges = network["molecule_edges"] if is_molecule else network["feature_edges"]
    ids = {n["id"] for n in source_nodes}
    links = {}
    if not is_molecule:
        for link in network["chemical_links"]:
            key = tuple(sorted((link["source"], link["target"])))
            links.setdefault(key, []).append(link)
    edges = []
    for edge in source_edges:
        a, b = edge["source"], edge["target"]
        pair_links = links.get(tuple(sorted((a, b))), [])
        if is_molecule:
            if a not in mapping or b not in mapping or mapping[a] == mapping[b]:
                continue
            if chosen[mapping[a]] != a or chosen[mapping[b]] != b:
                continue
            a, b = mapping[a], mapping[b]
        if a not in ids or b not in ids:
            continue
        threshold = network["parameters"]["plot_threshold"]
        stats = []
        for row in edge["samples"]:
            if scope.startswith("sample:") and row["sample"] != scope.removeprefix("sample:"):
                continue
            if scope.startswith("condition:") and network["conditions"].get(
                row["sample"]
            ) != scope.removeprefix("condition:"):
                continue
            stats.append(
                {**row, "supported": bool(row["evaluable"] and abs(row["rho_all"]) >= threshold)}
            )
        if not any(r["supported"] for r in stats):
            continue
        if scope.startswith("condition:"):
            # Require sign-specific repeat support. Never average opposing correlations.
            eligible = []
            for sign in (1, -1):
                signed = [
                    {**r, "supported": r["supported"] and (r["rho_all"] > 0) == (sign > 0)}
                    for r in stats
                ]
                summary = consensus(signed, network["conditions"], network["parameters"])
                if any(
                    c["condition"] == scope.removeprefix("condition:") and c["replicate_support"]
                    for c in summary
                ):
                    eligible.extend(r for r in signed if r["supported"])
            shown = eligible
        else:
            shown = [r for r in stats if r["supported"]]
        for row in shown:
            positive = row["rho_all"] >= 0
            if (options["sign"] == "positive" and not positive) or (
                options["sign"] == "negative" and positive
            ):
                continue
            edges.append(
                {
                    "source": a,
                    "target": b,
                    "sign": "positive" if positive else "negative",
                    **row,
                    "relation_types": sorted(
                        {
                            link["type"]
                            for link in pair_links
                            if any(
                                sample["sample"] == row["sample"] and sample["supported"]
                                for sample in link["samples"]
                            )
                        }
                    ),
                    "chemical_relation_types": sorted({link["type"] for link in pair_links}),
                    "support_evidence": [
                        {
                            "type": link["type"],
                            "level": link["level"],
                            "candidate_ids": link["equivalent_candidate_ids"],
                        }
                        for link in pair_links
                        if any(
                            sample["sample"] == row["sample"] and sample["supported"]
                            for sample in link["samples"]
                        )
                    ],
                }
            )
    search = options["search"].casefold()
    source_nodes = [
        n
        for n in source_nodes
        if (not search or search in f"{n['id']} {n['mz']} {n['label']}".casefold())
        and (not options["category"] or n["classification"] == options["category"])
    ]
    if options["focus"]:
        focus = options["focus"]
        neighbors = {focus}
        for edge in edges:
            if focus in {edge["source"], edge["target"]}:
                neighbors.update((edge["source"], edge["target"]))
        source_nodes = [n for n in source_nodes if n["id"] in neighbors]
        source_nodes.sort(key=lambda n: n["id"] != focus)
    total = len(source_nodes)
    displayed = source_nodes[: options["node_limit"]]
    displayed_ids = {n["id"] for n in displayed}
    displayed_edges = [
        e for e in edges if e["source"] in displayed_ids and e["target"] in displayed_ids
    ]
    return {
        "pie": pie,
        "options": options,
        "network": {
            "kind": options["graph"],
            "layer": network["molecule_layer"] if is_molecule else network["feature_layer"],
            "method": network["parameters"]["method"],
            "scope": scope,
            "scopes": valid_scopes,
            "nodes": displayed,
            "edges": displayed_edges,
            "total_nodes": total,
            "truncated": total > len(displayed),
            "molecule_nodes": molecule_nodes,
            "undetermined_features": [f for f in feature_ids if f not in mapping],
            "parameters": network["parameters"],
            "annotation_version": version["id"],
            "database": version["database"],
        },
        "evidence": [
            {**link, "candidate_names": [all_rows[c]["name"] for c in link["candidate_ids"]]}
            for link in network["chemical_links"]
            if link["source"] in visible_features or link["target"] in visible_features
        ],
    }
