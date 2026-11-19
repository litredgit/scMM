"""Transactional annotation versions, review, presets and precision CSV exports."""
# ruff: noqa: RUF001

import json
from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from uuid import uuid4

import numpy as np
import pandas as pd

from scMM.util.lipid_annotation import (
    STORAGE_KEY,
    annotate_lipids,
    annotation_store,
    feature_only,
    filtered_candidates,
    filtered_feature_ids,
    isotope_feature_ids,
    version_valid,
)
from scMM.util.lipid_isotopes import ADDUCTS
from scMM.util.lipid_network import apply_support, intensity_layers
from scMM.util.lipid_network_views import annotation_charts, representatives
from scMM.util.lipid_rules import import_rules, rank_candidates, validate_rules
from scMM.util.lipid_spectrum import annotation_spectrum, apply_review, inherit_reviews

from .identity import actor
from .lipid_database import database_status, load_database, load_databases, prepare_database
from .preferences import preferences_path
from .projects import project_lock, write_json
from .web_support import table_view


def rules_presets():
    path = preferences_path().with_name("lipid-rules.json")
    presets = {}
    for resource in sorted(
        files("scMM").joinpath("resources/lipid_rules").iterdir(), key=lambda r: r.name
    ):
        if resource.name.endswith(".json"):
            rules = validate_rules(json.loads(resource.read_text(encoding="utf-8")), ADDUCTS)
            presets[rules["name"]] = rules
    # Existing named user presets keep their saved values, including older drafts.
    if path.is_file():
        presets.update(json.loads(path.read_text(encoding="utf-8")))
    return presets


def save_rules_preset(name, rules):
    name = name.strip()
    if not name:
        raise ValueError("请输入预设名称。")
    rules = validate_rules(rules, ADDUCTS)
    path = preferences_path().with_name("lipid-rules.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with project_lock(path.parent):
        presets = rules_presets()
        if name in presets:
            raise ValueError("预设名称已存在，请使用新名称。")
        custom = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        custom[name] = {**rules, "name": name}
        write_json(path, custom)
    return rules_presets()


def selected_version(data, identity):
    store = annotation_store(data)
    version = next((v for v in store["versions"] if v["id"] == (identity or store["active"])), None)
    if version is None:
        raise ValueError("请先运行注释并选择有效版本。")
    if not version_valid(data, version):
        raise ValueError("注释版本的特征、细胞、样本分组或强度来源已改变，请重新运行。")
    return store, version


def persist_annotation(data, store):
    data.uns[STORAGE_KEY] = json.dumps(store, ensure_ascii=False, allow_nan=False)
    active = next((v for v in store["versions"] if v["id"] == store["active"]), None)
    for column in ("lipid_candidate_ids", "lipid_isotope_match", "lipid_annotation_version"):
        if column in data.var:
            del data.var[column]
    if active:
        grouped = {}
        for row in active["candidates"]:
            grouped.setdefault(row["feature_id"], []).append(row["candidate_id"])
        isotopes = isotope_feature_ids(active)
        data.var["lipid_candidate_ids"] = [
            json.dumps(grouped.get(str(f), [])) for f in data.var_names
        ]
        data.var["lipid_isotope_match"] = [str(f) in isotopes for f in data.var_names]
        data.var["lipid_annotation_version"] = active["id"]


def relation_labels(project, rows):
    names = {sample["id"]: sample["name"] for sample in project.samples}
    return [{**row, "sample_name": names.get(row["sample"], row["sample"])} for row in rows]


def catalog_relations(project, data):
    """Snapshot reviewed root relations without changing the ion registry or its matrices."""
    state = project.ion_state
    if state is None or state.get("active_branch_id") is None:
        return []
    view = state["views"][state["branches"][state["active_branch_id"]]["view_id"]]
    if view["variable_kind"] != "feature":
        return []
    entries = [
        (key, entry)
        for key, entry in state["registry"]["grouping"].items()
        if entry["root_id"] == view["root_id"]
        and (not view.get("grouping_id") or key == view["grouping_id"])
    ]
    if not entries:
        return []
    key, entry = entries[-1]
    ids = set(data.var_names)
    result = []
    for row in entry["grouping"]["relations"]:
        if (
            row["kind"] not in {"isotope", "adduct"}
            or not {row["left_feature_id"], row["right_feature_id"]} <= ids
        ):
            continue
        result.append(
            {
                **deepcopy(row),
                "relation_id": f"catalog:{key}:{row['relation_id']}",
                "origin": "ion_catalog_snapshot",
                "grouping_version": key,
                "source": row["left_feature_id"],
                "target": row["right_feature_id"],
                "type": row["kind"],
                "candidate_ids": [],
                "review": entry.get("relation_reviews", {}).get(row["relation_id"], "pending"),
            }
        )
    return result


class LipidWorkflow:
    def lipid_info(self, identity):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            data = project.workspace.require_features()
            store = annotation_store(data)
            return {
                "database": database_status(),
                "quantitation_available": not feature_only(data),
                "adducts": ADDUCTS,
                "presets": rules_presets(),
                "active": store["active"],
                "layers": [] if feature_only(data) else intensity_layers(data)["raw"],
                "molecule_layers": intensity_layers(data)["molecule"],
                "sample_field": next(
                    (k for k in ("sample_id", "sample", "source_file") if k in data.obs), ""
                ),
                "samples": sorted(
                    data.obs[
                        next(k for k in ("sample_id", "sample", "source_file") if k in data.obs)
                    ]
                    .astype(str)
                    .unique()
                    .tolist()
                )
                if any(k in data.obs for k in ("sample_id", "sample", "source_file"))
                else ["单样本"],
                "condition_fields": [
                    str(k)
                    for k in data.obs
                    if k not in {"sample_id", "sample", "source_file"}
                    and data.obs[k].nunique() <= 100
                ],
                "condition_values": {
                    str(k): sorted(data.obs[k].dropna().astype(str).unique().tolist())
                    for k in data.obs
                    if data.obs[k].nunique() <= 100
                },
                "default_layer": data.uns.get("scmm_workbench", {}).get("original_layer", ""),
                "resolution": project.manifest["parameters"].get("resolution"),
                "versions": [
                    {
                        "id": v["id"],
                        "label": v["label"],
                        "created_at": v["created_at"],
                        "valid": version_valid(data, v),
                        "mass_only": v.get("mass_only", False),
                        "candidates": len(v["candidates"]),
                        "isotope_matches": sum(r["matched"] for r in v["relations"]),
                    }
                    for v in store["versions"]
                ],
            }

    def lipid_prepare(self, identity, revision):
        with self.access(identity) as workspace:
            workspace.check(revision)
            workspace.require_project()
            result = prepare_database()
            return {"workspace": self.view(workspace), "value": result}

    def lipid_run(self, identity, revision, options, rules, label):
        from .web_projects import project_candidate

        with self.access(identity, operation="lipid_annotation") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            rules = validate_rules(rules, ADDUCTS)
            if len(set(options["adducts"])) != len(options["adducts"]) or any(
                a not in ADDUCTS for a in options["adducts"]
            ):
                raise ValueError("请选择有效且不重复的单电荷加合物。")
            selected_databases = list(
                dict.fromkeys(
                    name for name in [options["database"], *options.get("databases", [])] if name
                )
            )
            if not selected_databases and not database_status()["available"]:
                prepare_database()
            if len(selected_databases) <= 1:
                database, database_identity = load_database(
                    selected_databases[0] if selected_databases else ""
                )
            else:
                database, database_identity = load_databases(selected_databases)
            candidate = project_candidate(project)
            data = candidate.workspace.require_features()
            version = annotate_lipids(data, database, database_identity, options, rules)
            version["catalog_relations"] = catalog_relations(candidate, data)
            version.update(
                id=uuid4().hex,
                label=label.strip() or "注释与同位素",
                created_at=datetime.now(UTC).isoformat(),
            )
            store = annotation_store(data)
            if store["active"]:
                previous = next((v for v in store["versions"] if v["id"] == store["active"]), None)
                if previous:
                    inherit_reviews(previous, version)
                    apply_support(version)
                    rank_candidates(version["candidates"], version["rules"])
            store["versions"].append(version)
            store["active"] = version["id"]
            persist_annotation(data, store)
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return self.view(workspace)

    def lipid_import_rules(self, identity, revision, content, format):
        with self.access(identity) as workspace:
            workspace.check(revision)
            return import_rules(content, format, ADDUCTS)

    def lipid_preset(self, identity, revision, name, rules):
        with self.access(identity) as workspace:
            workspace.check(revision)
            return {"workspace": self.view(workspace), "value": save_rules_preset(name, rules)}

    def lipid_edit(self, identity, revision, version_id, action):
        from .web_projects import project_candidate

        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            data = candidate.workspace.require_features()
            store, version = selected_version(data, version_id)
            action(version)
            version["review_revision"] = version.get("review_revision", 0) + 1
            apply_support(version)
            rank_candidates(version["candidates"], version["rules"])
            persist_annotation(data, store)
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return self.view(workspace)

    def lipid_apply_rules(self, identity, revision, version_id, rules):
        rules = validate_rules(rules, ADDUCTS)

        def action(version):
            version["rules"] = rules
            rank_candidates(version["candidates"], rules)

        return self.lipid_edit(identity, revision, version_id, action)

    def lipid_review(self, identity, revision, values):
        def action(version):
            principal = actor.get()
            apply_review(
                version,
                values,
                workspace_data_ids,
                reviewer=principal["id"] if principal else "local-api",
                timestamp=datetime.now(UTC).isoformat(),
            )

        with self.access(identity) as workspace:
            workspace_data_ids = set(
                workspace.require_project().workspace.require_features().var_names
            )
            return self.lipid_edit(identity, revision, values["version"], action)

    def lipid_spectrum(self, identity, revision, version_id, feature_id="", sample=""):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            data = project.workspace.require_features()
            _, version = selected_version(data, version_id)
            value = annotation_spectrum(data, version, feature_id=feature_id, sample=sample)
            value["dataset_token"] = list(project.workspace.token)
            return {"workspace": self.view(workspace), "value": value}

    def lipid_activate(self, identity, revision, version_id):
        from .web_projects import project_candidate

        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            data = candidate.workspace.require_features()
            store = annotation_store(data)
            if version_id:
                selected_version(data, version_id)
            store["active"] = version_id
            persist_annotation(data, store)
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return self.view(workspace)

    def lipid_query(self, identity, revision, values):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            data = project.workspace.require_features()
            _, version = selected_version(data, values["version"])
            filters = values["filters"]
            if filters["adduct_mode"] == "specified" and not filters["adducts"]:
                raise ValueError("请指定保留的加合物。")
            ids = filtered_feature_ids(data, version, filters)
            ids_set = set(ids)
            all_rows = filtered_candidates(version, filters)
            candidates = [
                r
                for r in all_rows
                if r["feature_id"] in ids_set
                and (not values["feature_id"] or r["feature_id"] == values["feature_id"])
            ]
            relations = [
                r
                for r in version["relations"]
                if not values["feature_id"]
                or values["feature_id"] in {r["parent_feature_id"], r["isotope_feature_id"]}
            ]
            from .lipid_sorting import sorted_rows

            sorting = values.get("sorting", {})
            candidates = sorted_rows(
                candidates,
                sorting.get("candidate_sort", "recommended"),
                sorting.get("candidate_descending", False),
            )
            relations = relation_labels(project, relations)
            relations = sorted_rows(
                relations,
                sorting.get("relation_sort", "recommended"),
                sorting.get("relation_descending", False),
            )
            feature_mz = dict(
                zip(
                    data.var_names,
                    np.asarray(data.var.get("mz", data.var_names), dtype=float),
                    strict=True,
                )
            )
            matched = isotope_feature_ids(version)
            counts = pd.Series([r["feature_id"] for r in all_rows]).value_counts().to_dict()
            from scMM.util.lipid_names import record_species

            grouped = {}
            for row in candidates:
                label = row.get("species") or record_species(row)
                key = (row["feature_id"], label, row["formula"], row["adduct"])
                grouped.setdefault(key, []).append(row)
            groups = list(grouped.items())
            chosen = groups[values["offset"] : values["offset"] + values["limit"]]
            # Row table remains uncollapsed for downstream exports and compatibility.
            table = table_view(
                pd.DataFrame(candidates[values["offset"] : values["offset"] + values["limit"]]),
                limit=values["limit"],
            )
            table["total"] = len(candidates)
            candidate_groups = [
                {
                    "label": key[1],
                    "feature_id": key[0],
                    "formula": key[2],
                    "adduct": key[3],
                    "rows": rows,
                }
                for key, rows in chosen
            ]
            isotope_table = table_view(
                pd.DataFrame(
                    relation_labels(
                        project,
                        relations[
                            values["relation_offset"] : values["relation_offset"] + values["limit"]
                        ],
                    )
                ),
                limit=values["limit"],
            )
            isotope_table["total"] = len(relations)
            return {
                "candidate_groups": candidate_groups,
                "candidate_group_total": len(groups),
                "version": version["id"],
                "parameters": version["parameters"],
                "rules": version["rules"],
                "database": version["database"],
                "intensity_layer": version["intensity_layer"],
                "features": [
                    {
                        "id": f,
                        "mz": float(feature_mz[f]),
                        "candidates": counts.get(f, 0),
                        "isotope": f in matched,
                        "reviewed": f in version["reviewed_features"],
                    }
                    for f in ids
                ],
                "candidates": table,
                "isotopes": isotope_table,
                "selected": deepcopy(version["selected"]),
                "annotation_names": deepcopy(version.get("annotation_names", {})),
                "linked_annotations": deepcopy(version.get("linked_annotations", {})),
                "adduct_relations": deepcopy(version.get("adduct_relations", [])),
                "review_conflicts": deepcopy(version.get("review_conflicts", [])),
                "review_revision": version.get("review_revision", 0),
                "audit": deepcopy(version.get("audit", [])),
                "suggested": [
                    r["candidate_id"]
                    for r in version["candidates"]
                    if r["feature_id"] == values["feature_id"] and r["top_ranked"]
                ],
                "diagnostics": version["diagnostics"],
                "classification": {
                    key: sorted({r[key] for r in version["candidates"] if r[key]})
                    for key in ("CATEGORY", "MAIN_CLASS", "SUB_CLASS")
                },
                "classification_tree": [
                    {"CATEGORY": a, "MAIN_CLASS": b, "SUB_CLASS": c}
                    for a, b, c in sorted(
                        {
                            (r["CATEGORY"], r["MAIN_CLASS"], r["SUB_CLASS"])
                            for r in version["candidates"]
                        }
                    )
                ],
                "total_features": data.n_vars,
                "chart_view": version.get("network", {}).get("view", {}),
                "chart_filters": version.get("network", {}).get("chart_filters", {}),
                "network_parameters": version.get("network", {}).get("parameters"),
            }

    def lipid_charts(self, identity, revision, version_id, filters, view):
        with self.access(identity) as workspace:
            workspace.check(revision)
            data = workspace.require_project().workspace.require_features()
            _, version = selected_version(data, version_id)
            if filters["adduct_mode"] == "specified" and not filters["adducts"]:
                raise ValueError("请指定保留的加合物。")
            ids = filtered_feature_ids(data, version, filters)
            mz = dict(
                zip(
                    data.var_names,
                    np.asarray(data.var.get("mz", data.var_names), dtype=float),
                    strict=True,
                )
            )
            return annotation_charts(
                version, ids, mz, filtered_candidates(version, filters), filters, view
            )

    def lipid_chart_view(self, identity, revision, version_id, filters, view):
        def action(version):
            if "network" not in version:
                raise ValueError("旧版本未计算相关网络，请重新运行注释。")
            version["network"]["view"] = view
            version["network"]["chart_filters"] = filters

        # Validate scope and filters before committing the display settings.
        self.lipid_charts(identity, revision, version_id, filters, view)
        return self.lipid_edit(identity, revision, version_id, action)

    def lipid_representative(self, identity, revision, version_id, database_id, feature_id):
        def action(version):
            if "network" not in version:
                raise ValueError("请重新运行注释以计算相关网络。")
            _, groups, _ = representatives(version)
            if database_id not in groups or (feature_id and feature_id not in groups[database_id]):
                raise ValueError("代表特征必须无歧义地属于所选数据库分子。")
            if feature_id:
                version["network"]["representatives"][database_id] = feature_id
            else:
                version["network"]["representatives"].pop(database_id, None)

        return self.lipid_edit(identity, revision, version_id, action)

    def lipid_export(self, identity, revision, version_id, filters, kind, view=None, sorting=None):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            data = project.workspace.require_features()
            _, version = selected_version(data, version_id)
            if filters["adduct_mode"] == "specified" and not filters["adducts"]:
                raise ValueError("请指定保留的加合物。")
            ids = filtered_feature_ids(data, version, filters)
            if kind in {
                "charts",
                "pie",
                "feature_nodes",
                "feature_edges",
                "molecule_nodes",
                "molecule_edges",
                "network_evidence",
            }:
                view = dict(view or {})
                view["node_limit"] = max(data.n_vars, 1)
                if kind.startswith("feature_"):
                    view["graph"] = "feature"
                elif kind.startswith("molecule_"):
                    view["graph"] = "molecule"
                mz = dict(
                    zip(
                        data.var_names,
                        np.asarray(data.var.get("mz", data.var_names), dtype=float),
                        strict=True,
                    )
                )
                charts = annotation_charts(
                    version, ids, mz, filtered_candidates(version, filters), filters, view
                )
                if kind == "charts":
                    return json.dumps(
                        charts, ensure_ascii=False, allow_nan=False
                    ).encode(), "application/json"
                if kind == "pie":
                    rows = [
                        {
                            **r,
                            "denominator": charts["pie"]["denominator"],
                            "level": charts["pie"]["level"],
                            "candidate_mode": charts["pie"]["candidate_mode"],
                            "filters": filters,
                        }
                        for r in charts["pie"]["counts"]
                    ]
                elif kind == "network_evidence":
                    rows = charts.get("evidence", [])
                else:
                    graph = charts["network"]
                    if graph is None:
                        raise ValueError("旧版本未计算相关网络，请重新运行。")
                    rows = [
                        {
                            **r,
                            "layer": graph["layer"],
                            "method": graph["method"],
                            "scope": graph["scope"],
                            "annotation_version": version_id,
                            "parameters": graph["parameters"],
                            "filters": filters,
                        }
                        for r in graph["nodes" if kind.endswith("nodes") else "edges"]
                    ]
                # Nested evidence is encoded as JSON inside CSV, retaining every sample.
                columns = {
                    "pie": ["classification", "count", "denominator", "level"],
                    "network_evidence": [
                        "source",
                        "target",
                        "type",
                        "candidate_ids",
                        "samples",
                        "consensus",
                    ],
                }
                frame = (
                    pd.DataFrame(rows)
                    if rows
                    else pd.DataFrame(
                        columns=columns.get(
                            kind,
                            [
                                "id",
                                "source",
                                "target",
                                "layer",
                                "method",
                                "scope",
                                "annotation_version",
                            ],
                        )
                    )
                )
                for column in frame:
                    frame[column] = frame[column].map(
                        lambda v: (
                            json.dumps(v, ensure_ascii=False, allow_nan=False)
                            if isinstance(v, (dict, list))
                            else v
                        )
                    )
                return frame.to_csv(index=False).encode(), "text/csv; charset=utf-8"
            if kind == "matrix":
                from .matrix_export import matrix_csv

                if feature_only(data):
                    raise ValueError("当前仅有特征表，未提供可导出的定量矩阵。")
                return matrix_csv(data, features=ids), "text/csv; charset=utf-8"
            if kind == "candidates":
                rows = [r for r in filtered_candidates(version, filters) if r["feature_id"] in ids]
            elif kind == "isotopes":
                # Full relationships remain auditable even if their feature is hidden from the matrix.
                rows = relation_labels(project, version["relations"])
                by_candidate = {row["candidate_id"]: row for row in version["candidates"]}
                from scMM.util.lipid_evidence import ms2_status

                rows = [
                    {
                        **row,
                        **{
                            key: by_candidate[row["parent_candidate_id"]].get(
                                key, [] if key == "ms2_evidence" else ""
                            )
                            for key in (
                                "database_record_id",
                                "database_sha256",
                                "database_source",
                                "database_filename",
                                "source_ms2_status",
                                "ms2_evidence",
                            )
                        },
                        "ms2_status": ms2_status(
                            by_candidate[row["parent_candidate_id"]],
                            input_identity=version["input_identity"],
                        ),
                        "ms2_scope_feature_id": row["parent_feature_id"],
                        "parent_annotation_name": version.get("annotation_names", {}).get(
                            row["parent_feature_id"], ""
                        ),
                        "isotope_annotation_name": version.get("annotation_names", {}).get(
                            row["isotope_feature_id"], ""
                        ),
                    }
                    for row in rows
                ]
            else:
                return json.dumps(
                    version["rules"], ensure_ascii=False, indent=2
                ).encode(), "application/json"
            from .lipid_sorting import sorted_rows

            sorting = sorting or {}
            prefix = "candidate" if kind == "candidates" else "relation"
            rows = sorted_rows(
                rows,
                sorting.get(f"{prefix}_sort", "recommended"),
                sorting.get(f"{prefix}_descending", False),
            )
            frame = pd.DataFrame(rows)
            if kind == "candidates" and not frame.empty:
                frame["annotation_name"] = (
                    frame["feature_id"].map(version.get("annotation_names", {})).fillna("")
                )
            if "ms2_evidence" in frame:
                frame["ms2_evidence"] = frame["ms2_evidence"].map(
                    lambda value: json.dumps(value, ensure_ascii=False)
                )
            if frame.empty:
                columns = (
                    "candidate_id feature_id name formula database_id database_record_id database_sha256 database_source database_filename adduct ppm_error ppm_band class_score adduct_score ms2_status ms2_evidence annotation_name"
                    if kind == "candidates"
                    else "relation_id parent_feature_id isotope_feature_id name formula adduct sample sample_name order theoretical_ratio observed_ratio matched review database_record_id database_sha256 database_source database_filename ms2_status ms2_evidence ms2_scope_feature_id parent_annotation_name isotope_annotation_name"
                )
                frame = pd.DataFrame(columns=columns.split())
            return frame.to_csv(index=False).encode(), "text/csv; charset=utf-8"
