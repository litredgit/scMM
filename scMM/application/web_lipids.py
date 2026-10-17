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
    filtered_candidates,
    filtered_feature_ids,
    isotope_feature_ids,
    version_valid,
)
from scMM.util.lipid_isotopes import ADDUCTS
from scMM.util.lipid_network import apply_support, intensity_layers
from scMM.util.lipid_network_views import annotation_charts, representatives
from scMM.util.lipid_rules import import_rules, rank_candidates, validate_rules

from .lipid_database import database_status, load_database, prepare_database
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


class LipidWorkflow:
    def lipid_info(self, identity):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            data = project.workspace.require_data()
            store = annotation_store(data)
            return {
                "database": database_status(),
                "adducts": ADDUCTS,
                "presets": rules_presets(),
                "active": store["active"],
                "layers": intensity_layers(data)["raw"],
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
        from .web_workspace import project_candidate

        with self.access(identity, operation="lipid_annotation") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            rules = validate_rules(rules, ADDUCTS)
            if len(set(options["adducts"])) != len(options["adducts"]) or any(
                a not in ADDUCTS for a in options["adducts"]
            ):
                raise ValueError("请选择有效且不重复的单电荷加合物。")
            if not database_status()["available"]:
                prepare_database()
            database, database_identity = load_database(options["database"])
            candidate = project_candidate(project)
            data = candidate.workspace.require_data()
            version = annotate_lipids(data, database, database_identity, options, rules)
            version.update(
                id=uuid4().hex,
                label=label.strip() or "注释与同位素",
                created_at=datetime.now(UTC).isoformat(),
            )
            store = annotation_store(data)
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
        from .web_workspace import project_candidate

        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            data = candidate.workspace.require_data()
            store, version = selected_version(data, version_id)
            action(version)
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
            feature = values["feature_id"]
            if feature is not None:
                if feature not in workspace_data_ids:
                    raise ValueError("所选特征不存在。")
                valid = {
                    r["candidate_id"] for r in version["candidates"] if r["feature_id"] == feature
                }
                if values["candidate_ids"] is None:
                    version["selected"].pop(feature, None)
                elif not set(values["candidate_ids"]) <= valid:
                    raise ValueError("所选候选不属于该特征。")
                else:
                    version["selected"][feature] = list(dict.fromkeys(values["candidate_ids"]))
                if feature not in version["reviewed_features"]:
                    version["reviewed_features"].append(feature)
            if values["relation_id"] is not None:
                row = next(
                    (r for r in version["relations"] if r["relation_id"] == values["relation_id"]),
                    None,
                )
                if row is None:
                    raise ValueError("同位素关系不存在。")
                row["review"] = values["review"]
            if feature is None and values["relation_id"] is None:
                raise ValueError("请选择候选或同位素关系。")

        with self.access(identity) as workspace:
            workspace_data_ids = set(workspace.require_project().workspace.require_data().var_names)
            return self.lipid_edit(identity, revision, values["version"], action)

    def lipid_activate(self, identity, revision, version_id):
        from .web_workspace import project_candidate

        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            data = candidate.workspace.require_data()
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
            data = project.workspace.require_data()
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
            feature_mz = dict(
                zip(
                    data.var_names,
                    np.asarray(data.var.get("mz", data.var_names), dtype=float),
                    strict=True,
                )
            )
            matched = isotope_feature_ids(version)
            counts = pd.Series([r["feature_id"] for r in all_rows]).value_counts().to_dict()
            table = table_view(
                pd.DataFrame(candidates[values["offset"] : values["offset"] + values["limit"]]),
                limit=values["limit"],
            )
            table["total"] = len(candidates)
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
            data = workspace.require_project().workspace.require_data()
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

    def lipid_export(self, identity, revision, version_id, filters, kind, view=None):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            data = project.workspace.require_data()
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
                return data[:, ids].to_df().to_csv(index=True).encode(), "text/csv; charset=utf-8"
            if kind == "candidates":
                rows = [r for r in filtered_candidates(version, filters) if r["feature_id"] in ids]
            elif kind == "isotopes":
                # Full relationships remain auditable even if their feature is hidden from the matrix.
                rows = relation_labels(project, version["relations"])
            else:
                return json.dumps(
                    version["rules"], ensure_ascii=False, indent=2
                ).encode(), "application/json"
            frame = pd.DataFrame(rows)
            if frame.empty:
                columns = (
                    "candidate_id feature_id name formula database_id adduct ppm_error ppm_band class_score adduct_score"
                    if kind == "candidates"
                    else "relation_id parent_feature_id isotope_feature_id name formula adduct sample sample_name order theoretical_ratio observed_ratio matched review"
                )
                frame = pd.DataFrame(columns=columns.split())
            return frame.to_csv(index=False).encode(), "text/csv; charset=utf-8"
