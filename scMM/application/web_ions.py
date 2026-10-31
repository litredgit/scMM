"""Transactional ion orchestration; matrices stay in the application/domain layers."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from scMM.ion.identity import json_identity
from scMM.ion.semantics import value_states, write_value_states
from scMM.ion.species import ION_SPECS

from .data_views import DataViewCatalog, freeze_active_branch
from .identity import actor
from .web_projects import project_candidate


def measurement(project, root_id):
    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    root = catalog._roots.get(root_id)
    if root is None:
        raise ValueError("measurement root unavailable; import a complete project")
    data = root.data
    states = value_states(data)
    states["X"] = {**states["X"], "space": root.value_semantics}
    write_value_states(data, states)
    return data


def grouping_version(project, version):
    try:
        return project.ion_state["registry"]["grouping"][version]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown grouping version") from exc


def binding(workspace, root_id):
    project = workspace.require_project()
    state = project.ion_state
    root = state["roots"].get(root_id)
    if root is None:
        raise ValueError("measurement root unavailable")
    return {
        "root_id": root_id,
        "root_identity": root["metadata"]["identity"],
        "project": str(project.folder),
        "catalog_revision": state["revision"],
        "active_branch_id": state["active_branch_id"],
        "dataset_token": list(project.workspace.token),
        "workspace_revision": workspace.revision,
    }


class IonWorkflow:
    def _ion_jobs(self):
        from .ion_jobs import IonJobs

        with self._lock:
            if not hasattr(self, "ion_jobs"):
                self.ion_jobs = IonJobs(
                    self.store.root / ".ion-jobs",
                    timeout=getattr(self, "ion_resources", {}).get("ion_task_seconds", 300),
                )
            return self.ion_jobs

    def ion_info(self, identity):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            state = project.ion_state
            jobs = self._ion_jobs()
            principal = actor.get()
            owner = principal["id"] if principal else workspace.owner_id
            with jobs.lock:
                tasks = [
                    deepcopy(r)
                    for r in jobs.jobs.values()
                    if r["owner"] == owner and r["workspace"] == identity
                ]
            if state is None:
                return {
                    "initialized": False,
                    "species": [{"id": s.id, "polarity": s.polarity} for s in ION_SPECS.values()],
                    "tasks": tasks,
                }
            state = freeze_active_branch(project)
            return {
                "initialized": True,
                "catalog_revision": state["revision"],
                "active_branch_id": state["active_branch_id"],
                "roots": [
                    {"id": key, **entry["metadata"]} for key, entry in state["roots"].items()
                ],
                "views": list(state["views"].values()),
                "branches": [
                    {
                        "id": key,
                        "view_id": entry["view_id"],
                        "cells": entry["workspace"]["data"].n_obs,
                        "variables": entry["workspace"]["data"].n_vars,
                    }
                    for key, entry in state["branches"].items()
                ],
                "versions": [
                    {
                        "id": key,
                        "root_id": entry["root_id"],
                        "groups": len(entry["grouping"]["groups"]),
                        "relations": len(entry["grouping"]["relations"]),
                        "complete": all(
                            r["search_complete"] for r in entry["grouping"]["diagnostics"]
                        ),
                    }
                    for key, entry in state["registry"]["grouping"].items()
                ],
                "annotation_versions": list(state["registry"]["annotation"]),
                "tasks": tasks,
                "species": [{"id": s.id, "polarity": s.polarity} for s in ION_SPECS.values()],
            }

    def _ion_mutate(self, identity, revision, action):
        with self.access(identity, operation="ions") as workspace:
            if getattr(self, "maintenance_frozen", False):
                raise ValueError("service is frozen for maintenance")
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            if candidate.ion_state is not None:
                candidate.ion_state = freeze_active_branch(candidate)
            value = action(candidate)
            if candidate.ion_state is not None:
                DataViewCatalog.from_state(freeze_active_branch(candidate))
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": value}

    def ion_initialize(self, identity, revision, **options):
        from .data_views import initialize_catalog

        def apply(project):
            data = project.workspace._original
            if data is None:
                raise ValueError("load and approve a feature matrix first")
            view, branch = initialize_catalog(
                project,
                data,
                source={
                    "kind": project.workspace.source,
                    "declaration": "user-selected input semantics",
                },
                preserve_active=True,
                **options,
            )
            return {"view": view, "branch_id": branch}

        return self._ion_mutate(identity, revision, apply)

    def ion_run(self, identity, revision, *, root_id, options, request_id):
        principal = actor.get()
        with self.access(identity, operation="ion_submit") as workspace:
            if getattr(self, "maintenance_frozen", False):
                raise ValueError("service is frozen for maintenance")
            workspace.check(revision)
            project = workspace.require_project()
            frozen = binding(workspace, root_id)
            for key in options["species"]:
                if key not in ION_SPECS or ION_SPECS[key].polarity != options["polarity"]:
                    raise ValueError("select ion forms matching the acquisition polarity")
            if options.get("formula_hypotheses") and options.get("resolution_200") is None:
                raise ValueError(
                    "formula isotope evidence requires acquisition resolution at m/z 200"
                )
            resources = getattr(self, "ion_resources", {})
            options = {
                **options,
                "max_states": resources.get("ion_max_states", 100000),
                "component_seconds": resources.get("ion_component_seconds", 30),
                "max_hypotheses": resources.get("ion_max_hypotheses", 10000),
                "memory_mb": resources.get("ion_memory_mb", 16384),
                "task_seconds": resources.get("ion_task_seconds", 300),
            }
            job = self._ion_jobs().submit(
                measurement(project, root_id),
                owner=principal["id"] if principal else workspace.owner_id,
                workspace=identity,
                binding=frozen,
                options=options,
                request_id=request_id,
            )
            # Submission is a task operation; it does not revise the scientific workspace.
            return {"workspace": self.view(workspace), "value": job}

    def ion_job(self, identity, job_id, *, cancel=False):
        with self.access(identity) as workspace:
            principal = actor.get()
            options = {
                "owner": principal["id"] if principal else workspace.owner_id,
                "workspace": identity,
            }
            jobs = self._ion_jobs()
            record = jobs.cancel(job_id, **options) if cancel else jobs.get(job_id, **options)
            if record["status"] == "succeeded" and record["collectible"]:
                try:
                    valid = binding(workspace, record["binding"]["root_id"]) == record["binding"]
                except (KeyError, TypeError, ValueError):
                    valid = False
                if not valid:
                    jobs.mark(job_id, reason="workspace/input changed; explicitly run a new task")
                    record = jobs.get(job_id, **options)
            return record

    def ion_collect(self, identity, revision, job_id):
        jobs = self._ion_jobs()

        def apply(project):
            if job_id in project.ion_state["registry"]["grouping"]:
                raise ValueError("task has already been collected")
            principal = actor.get()
            record = self.ion_job(identity, job_id)
            result = jobs.result(
                job_id,
                owner=principal["id"] if principal else jobs.jobs[job_id]["owner"],
                workspace=identity,
            )
            data = measurement(project, record["binding"]["root_id"])
            from scMM.ion.identity import dataset_identity

            if result["grouping"]["input_identity"] != dataset_identity(data):
                raise ValueError("worker input identity differs")
            version = job_id
            project.ion_state["registry"]["grouping"][version] = {
                **result,
                "root_id": record["binding"]["root_id"],
                "relation_reviews": {},
                "selections": [],
                "submitted_binding": record["binding"],
            }
            project.ion_state["revision"] += 1
            return {"version": version}

        response = self._ion_mutate(identity, revision, apply)
        jobs.mark(job_id, collected=True)
        return response

    def ion_review(self, identity, revision, **options):
        from scMM.ion.evidence import record_review
        from scMM.ion.representation import build_representations

        def apply(project):
            version = options["version"]
            kind, target = options["kind"], options["target_id"]
            registry = project.ion_state["registry"]
            principal = actor.get()
            reviewer = principal["id"] if principal else "local-api"
            reviews = []

            def review(target_kind, target_id):
                row = record_review(
                    {"kind": target_kind, "id": target_id},
                    version=version,
                    decision=options["decision"],
                    reviewer=reviewer,
                    timestamp=datetime.now(UTC).isoformat(),
                    reason=options["reason"],
                    scope=options["scope"],
                )
                reviews.append(row)

            if kind in {"group", "relation"}:
                entry = grouping_version(project, version)
                rows = {r["relation_id"]: r for r in entry["grouping"]["relations"]}
                if kind == "relation":
                    if target not in rows:
                        raise ValueError("unknown relation")
                    if options["decision"] == "accepted" and rows[target]["kind"] in {
                        "neutral_loss",
                        "fragment_form",
                    }:
                        raise ValueError("fragment candidates cannot drive automatic merging")
                    entry["relation_reviews"][target] = options["decision"]
                    review("relation", target)
                else:
                    selections = [s for s in entry["selections"] if s["ec_id"] != target]
                    if options["decision"] == "accepted":
                        selection = {k: options[k] for k in ("hypothesis_id", "relation_ids")}
                        selection.update(ec_id=target, review="accepted")
                        if options["quantifier_feature_id"]:
                            selection["quantifier_feature_id"] = options["quantifier_feature_id"]
                        for relation in options["relation_ids"]:
                            if relation not in rows or rows[relation]["kind"] in {
                                "neutral_loss",
                                "fragment_form",
                            }:
                                raise ValueError("unsupported merge relation")
                            entry["relation_reviews"][relation] = "accepted"
                            review("relation", relation)
                        selections.append(selection)
                        build_representations(
                            measurement(project, entry["root_id"]),
                            entry["grouping"],
                            selections,
                            relation_reviews=entry["relation_reviews"],
                        )
                    entry["selections"] = selections
                    review("ec", target)
            elif kind == "candidate":
                annotation = registry["annotation"].get(version)
                if annotation is None or not any(
                    r.get("candidate_id") == target for r in annotation["candidates"]
                ):
                    raise ValueError("unknown candidate/version")
                review("candidate", target)
            else:
                if target not in registry["evidence"]:
                    raise ValueError("unknown evidence")
                review("evidence", target)
            registry["reviews"].extend(reviews)
            project.ion_state["revision"] += 1
            # Annotation is an overlay: numerical branches and models are unchanged.
            return reviews

        return self._ion_mutate(identity, revision, apply)

    def ion_represent(self, identity, revision, **options):
        from scMM.ion.representation import build_exploratory_representations, build_representations

        from .data_views import add_source_view

        def apply(project):
            entry = grouping_version(project, options["version"])
            data = measurement(project, entry["root_id"])
            common = {
                "strategy": options["strategy"],
                "include_singletons": options["include_singletons"],
            }
            if options["mode"] == "exploratory_v1":
                result = build_exploratory_representations(
                    data, entry["grouping"], entry["ratio_assessments"], **common
                )
            else:
                result = build_representations(
                    data,
                    entry["grouping"],
                    entry["selections"],
                    relation_reviews=entry["relation_reviews"],
                    **common,
                )
            l1, l2, metadata = result
            views = []
            for level, key in [("L1", "l1"), ("L2", "l2")]:
                matrix = l1 if key == "l1" else l2
                if matrix is None or min(matrix.shape) < 1:
                    continue
                view, branch = add_source_view(
                    project,
                    matrix,
                    root_id=entry["root_id"],
                    level=level,
                    source_features=list(data.var_names),
                    grouping_id=options["version"],
                    quantification_id=metadata["representation_id"],
                )
                views.append({"view": view, "branch_id": branch})
            project.ion_state["registry"].setdefault("representations", {})[
                metadata["representation_id"]
            ] = metadata
            return views

        return self._ion_mutate(identity, revision, apply)

    def ion_annotate(self, identity, revision, **options):
        from scMM.ion.annotation import build_compound_index, search_candidates

        def apply(project):
            data = measurement(project, options["root_id"])
            imported = options["records"]
            if options.get("content"):
                if imported:
                    raise ValueError("provide records or a database file, not both")
                from .compound_database import table_records

                if options["format"] in {"csv", "tsv"}:
                    imported = table_records(
                        options["content"], delimiter="," if options["format"] == "csv" else "\t"
                    )
                elif options["format"] == "sdf":
                    from scMM.util.annotation import parse_sdf_record

                    if not options["content"].rstrip().endswith("$$$$"):
                        raise ValueError("incomplete SDF record")
                    imported = [
                        parse_sdf_record(block.strip())
                        for block in options["content"].split("$$$$")
                        if block.strip()
                    ]
                else:
                    imported = json.loads(options["content"])
            if options.get("field_mapping"):
                imported = [
                    {
                        **row,
                        **{
                            key: row.get(field, "")
                            for key, field in options["field_mapping"].items()
                        },
                    }
                    for row in imported
                ]
            records = [{**r, "namespace": options["namespace"]} for r in imported]
            database = build_compound_index(
                records,
                source={
                    "kind": "user_import",
                    "namespace": options["namespace"],
                    "digest": json_identity(records),
                },
            )
            targets = [
                {
                    "target_id": str(f),
                    "target_kind": "feature",
                    "mass": float(mz),
                    "polarity": options["polarity"],
                }
                for f, mz in zip(data.var_names, data.var.mz, strict=True)
            ]
            if options["version"]:
                entry = grouping_version(project, options["version"])
                if entry["root_id"] != options["root_id"]:
                    raise ValueError("annotation/grouping roots differ")
                for selection in entry["selections"]:
                    from scMM.ion.hypotheses import reviewed_group

                    group, hypothesis = reviewed_group(
                        entry["grouping"], selection["ec_id"], selection["hypothesis_id"]
                    )
                    targets.append(
                        {
                            "target_id": group["ec_id"],
                            "target_kind": "ec",
                            "mass": hypothesis["neutral_mass"],
                            "hypothesis_id": hypothesis["hypothesis_id"],
                        }
                    )
            targets.extend(options["formula_targets"])
            result = search_candidates(
                targets,
                database,
                [ION_SPECS[key] for key in options["species"]],
                ppm=options["ppm"],
            )
            version = uuid4().hex
            result.update(
                root_id=options["root_id"], grouping_version=options["version"], id=version
            )
            project.ion_state["registry"]["annotation"][version] = result
            project.ion_state["revision"] += 1
            return {"version": version, "candidates": len(result["candidates"])}

        return self._ion_mutate(identity, revision, apply)

    def ion_evidence(self, identity, revision, **options):
        from scMM.ion.evidence import normalize_evidence, parse_text_spectra

        def apply(project):
            records = options["records"]
            if options["format"] != "json":
                if records:
                    raise ValueError("provide records or a spectrum file, not both")
                records = [
                    {"kind": "bulk_msms", "target": {"kind": "unmapped"}, "scope": {}, **spectrum}
                    for spectrum in parse_text_spectra(options["content"], format=options["format"])
                ]
            imported = normalize_evidence(
                records,
                source={
                    "kind": "user_import",
                    "filename": options["source_name"],
                    "digest": json_identity([records, options["content"]]),
                },
            )
            for row in imported:
                project.ion_state["registry"]["evidence"][row["evidence_id"]] = row
            project.ion_state["revision"] += 1
            return {"imported": len(imported)}

        return self._ion_mutate(identity, revision, apply)

    def ion_table(self, identity, *, version, kind, offset=0, limit=100):
        import pandas as pd

        from .web_support import table_view

        with self.access(identity) as workspace:
            project = workspace.require_project()
            registry = project.ion_state["registry"]
            if kind in {"relations", "groups", "diagnostics"}:
                rows = grouping_version(project, version)["grouping"][kind]
            elif kind in {"evidence", "reviews"}:
                rows = list(registry[kind].values()) if kind == "evidence" else registry[kind]
            elif kind in {"candidates", "unknown"}:
                rows = registry["annotation"][version][
                    "unknown_targets" if kind == "unknown" else kind
                ]
            elif kind == "representations":
                rows = list(registry.get("representations", {}).values())
            else:
                raise ValueError("unknown ion table")
            display = [
                {
                    key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
                for row in rows[offset : offset + limit]
            ]
            return {
                "total": len(rows),
                "offset": offset,
                "table": table_view(pd.DataFrame(display), limit=limit),
            }
