"""Workspace-owned preview tokens and atomic installation of processed merges."""
# ruff: noqa: RUF001

import json
import time
from uuid import uuid4

import pandas as pd

from . import processed_merge
from .merge_metadata import mapping_rows
from .merge_sources import load_inputs, recheck
from .project_batch import batches, read_batch
from .web_support import table_view
from .workbench import AnalysisWorkspace


def _idle(workspace):
    project = workspace.require_project()
    if workspace.preview_job and not workspace.preview_job["future"].done():
        raise ValueError("原始预览仍在计算，请结束后再合并")
    if any(read_batch(path)["status"] in {"queued", "running"} for path in batches(project)):
        raise ValueError("当前项目提取仍在运行，请结束后再合并")
    return project


class MergeWorkflow:
    def merge_inspect(self, identity, revision, specification):
        with self.access(identity, operation="merge_inspect") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            inputs = load_inputs(self, project, [specification])
            entry = inputs[0]
            data = entry["data"]
            return {
                "workspace": self.view(workspace),
                "value": {
                    "cells": data.n_obs,
                    "features": data.n_vars,
                    "baseline_cells": entry["baseline"].n_obs,
                    "baseline_features": entry["baseline"].n_vars,
                    "baseline_scope": entry["scope"],
                    "label": entry["label"],
                    "observations": list(data.obs),
                    "feature_columns": list(data.var),
                    "layers": list(data.layers),
                    "samples": mapping_rows(inputs),
                },
            }

    def merge_preview(self, identity, revision, options):
        with self.access(identity, operation="merge_preview") as workspace:
            workspace.check(revision)
            project = _idle(workspace)
            workspace.merge_plan = None
            inputs = load_inputs(self, project, options["sources"])
            roles = processed_merge.prepare(inputs, options)
            conflicts = sum(value["ambiguous"] for value in roles.values())
            permitted = not conflicts or options["ambiguity"] == "legacy"
            recheck(self, project, inputs)
            token = uuid4().hex
            workspace.merge_plan = {
                "token": token,
                "can_apply": permitted,
                "revision": workspace.revision,
                "project_id": project.manifest["id"],
                "expires": time.monotonic() + 300,
                "options": options,
                "identities": [entry["identity"] for entry in inputs],
            }
            return {
                "workspace": self.view(workspace),
                "value": {
                    "token": token,
                    "can_apply": permitted,
                    "conflicts": conflicts,
                    "sample_mapping": options["mapping"],
                    "inputs": [
                        {
                            "id": entry["id"],
                            "label": entry["label"],
                            "baseline_scope": entry["scope"],
                        }
                        for entry in inputs
                    ],
                    "summaries": {
                        role: {
                            "cells": plan["cells"],
                            "features": len(plan["features"]),
                            "matched": sum(row["status"] == "matched" for row in plan["rows"]),
                            "excluded": sum(row["status"] == "excluded" for row in plan["rows"]),
                            "added": sum(row["status"] == "added" for row in plan["rows"]),
                            "ambiguous": plan["ambiguous"],
                        }
                        for role, plan in roles.items()
                    },
                    "tables": {
                        role: table_view(pd.DataFrame(plan["rows"])) for role, plan in roles.items()
                    },
                },
            }

    def merge_info(self, identity):
        from .merge_audit import merge_info

        with self.access(identity) as workspace:
            return merge_info(workspace.require_project().workspace.data)

    def merge_preview_download(self, identity, token):
        from .merge_audit import bundle

        with self.access(identity) as workspace:
            project = workspace.require_project()
            plan = workspace.merge_plan
            if (
                not plan
                or plan["token"] != token
                or plan["expires"] < time.monotonic()
                or plan["revision"] != workspace.revision
                or plan["project_id"] != project.manifest["id"]
            ):
                raise ValueError("预览已过期或不属于当前项目，请重新预览")
            inputs = load_inputs(self, project, plan["options"]["sources"])
            if [entry["identity"] for entry in inputs] != plan["identities"]:
                raise ValueError("输入已改变，请重新预览")
            roles = processed_merge.prepare(inputs, plan["options"])
            recheck(self, project, inputs)
            return bundle(
                {
                    "scope": "read_only_merge_preview",
                    "options": plan["options"],
                    "identities": plan["identities"],
                    "baseline_mode": "union",
                },
                {
                    role + "_feature_mapping": pd.DataFrame(value["rows"])
                    for role, value in roles.items()
                },
            )

    def merge_apply(self, identity, revision, token):
        from .web_projects import project_candidate

        with self.access(identity, operation="merge_processed") as workspace:
            workspace.check(revision)
            project = _idle(workspace)
            plan = workspace.merge_plan
            if (
                not plan
                or plan["token"] != token
                or plan["expires"] < time.monotonic()
                or not plan.get("can_apply")
                or plan["revision"] != revision
                or plan["project_id"] != project.manifest["id"]
            ):
                raise ValueError("合并预览已过期或不属于当前项目/修订，请重新预览")
            inputs = load_inputs(self, project, plan["options"]["sources"])
            if [entry["identity"] for entry in inputs] != plan["identities"]:
                raise ValueError("预览后输入已改变或替换，请重新预览，当前数据未修改")
            roles = processed_merge.prepare(inputs, plan["options"])
            if plan["options"]["ambiguity"] == "reject" and any(
                value["ambiguous"] for value in roles.values()
            ):
                raise ValueError("输入出现匹配冲突，未应用候选")
            current = processed_merge.assemble(
                inputs, plan["options"], roles["data"], "data", token
            )
            baseline = processed_merge.assemble(
                inputs, plan["options"], roles["baseline"], "baseline", token
            )
            candidate = project_candidate(project)
            state = AnalysisWorkspace()
            state.replace(current, source="processed_merge:" + token)
            start = AnalysisWorkspace()
            start.replace(baseline, source=state.source)
            state._original = start.data
            event = {
                "operation": "merge_processed",
                "parameters": {
                    key: plan["options"][key]
                    for key in ("mode", "reference", "ppm_tol", "ambiguity")
                },
                "layer": "",
                "dataset_id": state.dataset_id,
                "revision": 0,
                "shape": list(state.data.shape),
            }
            for role, data in (("data", state.data), ("baseline", state._original)):
                actual = {
                    **event,
                    "shape": list(data.shape),
                    "parameters": {
                        **event["parameters"],
                        "role": role,
                        "mode": "union" if role == "baseline" else plan["options"]["mode"],
                    },
                }
                data.uns["scmm_workbench"]["history_json"] = json.dumps([actual])
            samples = []
            combined = pd.concat([state.data.obs, state._original.obs])
            for sample_id, rows in combined.groupby("sample_id", observed=True, sort=False):
                fields = {
                    key: str(rows[key].iloc[0]) if rows[key].nunique(dropna=False) == 1 else ""
                    for key in ("group", "subject", "batch")
                }
                samples.append(
                    {
                        "id": str(sample_id),
                        "name": str(rows["sample"].iloc[0]),
                        "path": "",
                        "storage": self.storage.roots[0].label,
                        "parameters": None,
                        "result_only": True,
                        "metadata_unresolved": [
                            key for key in fields if rows[key].nunique(dropna=False) > 1
                        ],
                        **fields,
                    }
                )
            candidate.workspace = state
            candidate.manifest["samples"] = samples
            candidate.manifest.update(
                sample_column="sample", sample_mapping={s["name"]: s["id"] for s in samples}
            )
            candidate.saved_reports = {}
            candidate.views.pop("figures", None)
            candidate.views.pop("analysis", None)
            candidate.report_token = state.token
            candidate.dirty = True
            candidate.validate_samples()
            recheck(self, project, inputs)
            workspace.project = candidate
            workspace.discard_views()
            workspace.merge_plan = None
            workspace.revision += 1
            return self.view(workspace)
