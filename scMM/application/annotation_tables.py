"""Preview and publish external feature annotations within the workspace transaction."""
# ruff: noqa: RUF001

import hashlib
import json
from datetime import UTC, datetime

import pandas as pd

from scMM.analysis.external_annotations import align_annotations, read_table, write_annotations

from .annotation_evidence import evidence_registry, evidence_source
from .annotation_sources import feature_source
from .web_projects import project_candidate
from .web_support import table_view


def apply_annotation_table(manager, identity, action, values):
    frame = read_table(
        values["content"],
        format=values["format"],
        header=values["header"],
        transpose=values["transpose"],
    )
    with manager.access(identity, operation="manual_annotations") as workspace:
        workspace.check(values["revision"])
        project = workspace.require_project()
        source = values["source"] or "current"
        root_scope = source != "current"
        if not root_scope and project.workspace._selection_source is not None:
            raise ValueError("请先关闭全部标签筛选，再导入注释。")
        if root_scope:
            data, source_identity = evidence_source(project, source)
        else:
            data, _ = feature_source(project, source)
        table, matched = align_annotations(
            data,
            frame,
            **{
                key: values[key]
                for key in ("mapping", "source_key", "target_key", "ppm", "mode", "row_positions")
            },
        )
        if action == "preview":
            return {
                "workspace": manager.view(workspace),
                "value": {
                    "table": table_view(table),
                    "matched": int(matched.sum()),
                    "ambiguous": int((table.status == "ambiguous").sum()),
                    "unmatched": int((table.status == "unmatched").sum()),
                },
            }
        candidate = project_candidate(project)
        if root_scope:
            registry = evidence_registry(candidate, write=True)
            fields = registry.setdefault("feature_fields", {}).setdefault(source, {})
            for column, saved_values in fields.items():
                if data is project.ion_state["roots"][source]["data"]:
                    data = data.copy()
                data.var[column] = data.var_names.map(saved_values).fillna("")
            updated = write_annotations(
                data,
                table,
                matched,
                mapping=values["mapping"],
                clear_unmatched=values["clear_unmatched"],
            )
            for column in values["mapping"].values():
                fields[column] = dict(
                    zip(map(str, updated.var_names), updated.var[column].astype(str), strict=True)
                )
            registry.setdefault("tables", []).append(
                {
                    "source": source,
                    "source_identity": source_identity,
                    "at": datetime.now(UTC).isoformat(),
                    "user_id": workspace.owner_id,
                    "source_sha256": hashlib.sha256(values["content"].encode()).hexdigest(),
                    "mapping": values["mapping"],
                    "mode": values["mode"],
                    "clear_unmatched": values["clear_unmatched"],
                    "matched": int(matched.sum()),
                    "rows": table_view(table, limit=len(table))["rows"],
                }
            )
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": manager.view(workspace), "value": {"matched": int(matched.sum())}}
        previous_names = candidate.workspace.data.var.get("display_name")
        candidate.workspace.data = write_annotations(
            candidate.workspace.data,
            table,
            matched,
            mapping=values["mapping"],
            clear_unmatched=values["clear_unmatched"],
        )
        # The reset origin receives matching annotations by stable feature ID.
        baseline = candidate.workspace._original
        for key in values["mapping"].values():
            baseline_values = (
                baseline.var[key].astype(object).copy()
                if key in baseline.var
                else pd.Series("", index=baseline.var_names, dtype=object)
            )
            common = baseline.var_names.intersection(candidate.workspace.data.var_names)
            baseline_values.loc[common] = candidate.workspace.data.var.loc[common, key]
            baseline.var[key] = baseline_values
        records = json.loads(candidate.workspace.data.uns.get("scmm_manual_annotations_json", "[]"))

        records.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "workspace_id": identity,
                "user_id": workspace.owner_id,
                "changes": [
                    {
                        "feature_id": str(key),
                        "before": str(previous_names.loc[key])
                        if previous_names is not None
                        else "",
                        "after": str(value),
                    }
                    for key, value in candidate.workspace.data.var.loc[
                        candidate.workspace.data.var_names[matched], "display_name"
                    ].items()
                    if previous_names is None or str(previous_names.loc[key]) != str(value)
                ]
                if "display_name" in values["mapping"].values()
                else [],
                "source_sha256": hashlib.sha256(values["content"].encode()).hexdigest(),
                "mapping": values["mapping"],
                "mode": values["mode"],
                "source_key": values["source_key"],
                "target_key": values["target_key"],
                "ppm": values["ppm"],
                "matched": int(matched.sum()),
                "clear_unmatched": values["clear_unmatched"],
            }
        )
        candidate.workspace.data.uns["scmm_manual_annotations_json"] = json.dumps(records)
        baseline.uns["scmm_manual_annotations_json"] = json.dumps(records)
        candidate.dirty = True
        workspace.project = candidate
        workspace.revision += 1
        return {"workspace": manager.view(workspace), "value": {"matched": int(matched.sum())}}
