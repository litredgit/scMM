"""Source-bound external annotation tables, MS/MS comparisons and manual links."""
# ruff: noqa: RUF001

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from scMM.ion.evidence import normalize_evidence, parse_text_spectra
from scMM.ion.identity import json_identity
from scMM.util.lipid_annotation import feature_axis, feature_samples

from .annotation_sources import feature_source
from .identity import actor
from .preview_cache import file_identity
from .web_lipids import selected_version
from .web_projects import project_candidate


def evidence_registry(project, *, write=False):
    parent = project.ion_state["registry"] if project.ion_state is not None else project.views
    return (
        parent.setdefault("annotation_evidence", {})
        if write
        else parent.get("annotation_evidence", {})
    )


def external_records(project, *, write=False):
    if project.ion_state is not None:
        return project.ion_state["registry"]["evidence"]
    registry = evidence_registry(project, write=write)
    return registry.setdefault("external", {}) if write else registry.get("external", {})


def evidence_source(project, source):
    data, identity = feature_source(project, source)
    if source in {"", "current"}:
        features, masses = feature_axis(data)
        identity = json_identity(
            [features, masses.tolist(), list(data.obs_names), feature_samples(data).tolist()]
        )
    return data, identity


def evidence_target(project, values):
    source = values["source"]
    data, identity = evidence_source(project, source)
    kind, key, version = values["kind"], values["id"], values["version"]
    feature = values.get("feature_id") or (key if kind == "feature" else "")
    record = {"source": source, "source_identity": identity, "kind": kind, "id": key}
    if kind == "candidate":
        if not version:
            raise ValueError("必须明确选择候选所属的注释版本。")
        _, selected = selected_version(project, data, version, source)
        row = next((r for r in selected["candidates"] if r["candidate_id"] == key), None)
        if row is None or (feature and row["feature_id"] != feature):
            raise ValueError("候选不属于当前版本或测量峰。")
        feature = row["feature_id"]
        record["database"] = {
            name: row.get(name, "")
            for name in ("database_sha256", "database_record_id", "database_filename", "adduct")
        }
    elif kind == "ec":
        from .web_ions import grouping_version

        group = grouping_version(project, version)
        if group["root_id"] != source:
            raise ValueError("离子组属于其他测量来源。")
        match = next((r for r in group["grouping"]["groups"] if r["ec_id"] == key), None)
        if match is None or (feature and feature not in match["feature_ids"]):
            raise ValueError("离子组或成员与所选版本不一致。")
    else:
        if feature != key:
            raise ValueError("关联目标的测量峰编号不一致。")
        # A measurement feature retains its identity across independent candidate runs.
        version = identity
    if feature and feature not in data.var_names:
        raise ValueError("所选测量峰不属于该来源。")
    return {**record, "version": version, "feature_id": feature}


def link_preview(project, target, record_id, row):
    registry = evidence_registry(project)
    search = registry.get("searches", {}).get(record_id)
    if search is not None:
        if search["source_identity"] != target["source_identity"]:
            raise ValueError("该搜索记录的测量来源与当前目标不同。")
        if row is None or row >= len(search["rows"]):
            raise ValueError("请明确选择一条实测与参考谱比对。")
        match = search["rows"][row]
        if not target["feature_id"] or target["feature_id"] != match["feature_id"]:
            raise ValueError("所选比对结果的测量峰与关联目标不同。")
        scope = {"sample_pool": match["sample_pool"], "polarity": match["polarity"]}
        comparison = match["passes_threshold"]
    else:
        external = external_records(project).get(record_id)
        if external is None or row is not None:
            raise ValueError("没有找到所选证据。")
        scope = external["scope"]
        if external["kind"] == "ms1_overlap":
            profile = external["profile_review"]
            if target["source_identity"] != profile["source_identity"] or not any(
                target["feature_id"] == candidate["feature_id"]
                and (
                    target["kind"] == "feature"
                    or (
                        target["kind"] == "candidate"
                        and target["version"] == profile["version"]
                        and target["id"] == candidate["candidate_id"]
                    )
                )
                for candidate in profile["candidates"]
            ):
                raise ValueError("原始谱复核只关联本次选定来源的测量峰或候选。")
        comparison = None
    key = json_identity([target, record_id, row])
    previous = registry.get("links", {}).get(key)
    return {
        "id": key,
        "target": target,
        "record_id": record_id,
        "row": row,
        "scope": scope,
        "passes_threshold": comparison,
        "decision": previous["decision"] if previous else "pending",
    }


class AnnotationEvidenceWorkflow:
    def annotation_acquisition(self, project, sample_id):
        sample = self.sample(project, sample_id)
        if sample.get("result_only"):
            raise ValueError("请先重新定位此样本的原始文件。")
        path = self.storage.resolve_raw_file(sample["storage"], sample["path"])
        return sample["name"], path, file_identity(path)

    def annotation_profile_review(
        self,
        identity,
        revision,
        *,
        source,
        version,
        candidate_ids,
        sample_id,
        scan_index,
        fwhm,
        offset_ppm,
    ):
        from pyopenms import IonSource, SpectrumSettings

        from scMM.file.io import load_single_file
        from scMM.util.lipid_overlap import compare_profile

        from .raw_preview import spectrum_at

        if not source or not version or len(set(candidate_ids)) != 2:
            raise ValueError("请明确选择注释来源、版本和两个候选。")
        with self.access(identity, operation="profile_review_input") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            data, binding = evidence_source(project, source)
            _, selected = selected_version(project, data, version, source)
            rows = [r for r in selected["candidates"] if r["candidate_id"] in candidate_ids]
            if len(rows) != 2:
                raise ValueError("候选不属于当前注释版本。")
            candidates = [
                {
                    key: row.get(key)
                    for key in (
                        "candidate_id",
                        "feature_id",
                        "name",
                        "formula",
                        "adduct",
                        "query_mz",
                        "theoretical_mz",
                        "polarity",
                        "database_sha256",
                        "database_record_id",
                        "source_formula_conflict",
                    )
                }
                for row in rows
            ]
            parameters = dict(selected["parameters"])
            sample_name, path, acquisition = self.annotation_acquisition(project, sample_id)
        experiment, metadata = load_single_file(path)
        scan = spectrum_at(experiment, scan_index)
        if scan.getMSLevel() != 1:
            raise ValueError("请选择 MS1 扫描。")
        if hasattr(scan, "getType"):
            if scan.getType() != SpectrumSettings.SpectrumType.PROFILE:
                raise ValueError("当前扫描需明确为连续谱（profile）。")
            measured_polarity = {
                IonSource.Polarity.POSITIVE: "pos",
                IonSource.Polarity.NEGATIVE: "neg",
            }.get(scan.getInstrumentSettings().getPolarity())
            if measured_polarity and any(r["polarity"] != measured_polarity for r in candidates):
                raise ValueError("扫描记录的采集极性与候选不一致。")
        elif not scan.is_profile:
            raise ValueError("当前扫描需为连续谱（profile）。")
        else:
            measured_polarity = None
        result = compare_profile(
            *scan.get_peaks(),
            candidates,
            max_order=parameters["max_isotope_order"],
            ppm=parameters["annotation_ppm"],
            fwhm=fwhm,
            offset_ppm=offset_ppm,
        )
        profile = {
            **result,
            "source": source,
            "source_identity": binding,
            "version": version,
            "sample_id": sample_id,
            "scan_index": scan_index,
            "native_id": scan.getNativeID()
            if hasattr(scan, "getNativeID")
            else f"scan={scan.scan_number}",
            "rt_seconds": float(scan.getRT()),
            "acquisition_polarity": measured_polarity,
            "instrument": str(metadata.get("instrument", "")),
        }
        with self.access(identity, operation="profile_review_collect") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            if (
                evidence_source(project, source)[1] != binding
                or self.annotation_acquisition(project, sample_id)[2] != acquisition
            ):
                raise ValueError("测量来源或原始文件已改变，请重新运行。")
            key = json_identity([profile, json_identity(acquisition)])
            candidate = project_candidate(project)
            external_records(candidate, write=True).setdefault(
                key,
                {
                    "evidence_id": key,
                    "kind": "ms1_overlap",
                    "scope": {
                        "description": f"{sample_name} · {profile['native_id']} · 单次 MS1 扫描"
                    },
                    "source": {"name": sample_name, "file_identity": json_identity(acquisition)},
                    "profile_review": profile,
                    "created_at": datetime.now(UTC).isoformat(),
                    "user_id": (actor.get() or {}).get("id", workspace.owner_id),
                },
            )
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": {"id": key, **profile}}

    def annotation_msms(self, identity, revision, *, source, options):
        from scMM.analysis.external_annotations import acquisition_msms, msms_search
        from scMM.plot.presentation import style_figure

        from .preview_cache import digest_file
        from .web_support import figure_view

        sample_id = options.pop("acquisition_sample", "")
        start, end = options.pop("scan_start", 0), options.pop("scan_end", None)
        unknown_type = options.pop("unknown_spectrum_type", "")
        if bool(sample_id) == bool(options["measured"].strip()):
            raise ValueError("请在实测谱文件和项目采集文件中选择一种输入。")
        legacy = not source
        source = source or "current"
        with self.access(identity, operation="msms_input") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            data, binding = evidence_source(project, source)
            # The comparison uses measured feature identities and masses only.
            import numpy as np
            from anndata import AnnData

            features, masses = feature_axis(data)
            from pandas import DataFrame

            frozen = AnnData(
                np.empty((0, data.n_vars)), var=DataFrame({"mz": masses}, index=features)
            )
            token = list(project.workspace.token)
            if sample_id:
                name, path, acquisition_identity = self.annotation_acquisition(project, sample_id)
        acquisition = None
        if sample_id:
            spectra, details = acquisition_msms(
                path, start=start, end=end, unknown_spectrum_type=unknown_type
            )
            acquisition = {
                **details,
                "sample_id": sample_id,
                "sample_name": name,
                "format": path.suffix.lstrip(".").lower(),
                "sha256": digest_file(path),
                "spectra": spectra,
            }
        figure = msms_search(frozen, acquisition=acquisition, **options)
        meta = dict(figure.layout.meta)
        rows = meta.pop("match_rows")
        key = uuid4().hex
        parameters = {k: v for k, v in options.items() if k not in {"measured", "library"}}
        if sample_id:
            parameters["acquisition"] = meta["acquisition"]
        figure.update_layout(
            meta={
                **meta,
                "annotation_record": key,
                "parameters": parameters,
                **({"dataset_token": token} if legacy else {}),
            },
            overwrite=True,
        )
        value = figure_view(style_figure(figure))
        with self.access(identity, operation="msms_collect") as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            if evidence_source(project, source)[1] != binding:
                raise ValueError("数据已改变，请重新运行 MS/MS 搜索。")
            if (
                sample_id
                and self.annotation_acquisition(project, sample_id)[2] != acquisition_identity
            ):
                raise ValueError("原始文件已改变，请重新运行 MS/MS 搜索。")
            candidate = project_candidate(project)
            evidence_registry(candidate, write=True).setdefault("searches", {})[key] = {
                "id": key,
                "source": source,
                "source_identity": binding,
                "created_at": datetime.now(UTC).isoformat(),
                "user_id": (actor.get() or {}).get("id", workspace.owner_id),
                "parameters": parameters,
                "rows": rows,
                "figure": value,
            }
            if legacy:
                candidate.views.setdefault("figures", {})["msms_evidence"] = value
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": value}

    def annotation_evidence_list(self, identity, *, source="", feature=""):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            registry = evidence_registry(project)
            binding = evidence_source(project, source)[1] if source else ""
            searches = [
                {
                    **{k: record[k] for k in ("id", "source", "created_at", "parameters")},
                    "size": len(record["rows"]),
                    "current": record["source_identity"] == binding,
                }
                for record in registry.get("searches", {}).values()
            ]
            links = [
                row
                for row in registry.get("links", {}).values()
                if not feature
                or (
                    row["target"]["source_identity"] == binding
                    and row["target"]["feature_id"] == feature
                )
            ]
            return {
                "searches": list(reversed(searches)),
                "external": [
                    {k: row[k] for k in ("evidence_id", "kind", "scope", "source")}
                    for row in external_records(project).values()
                ],
                "links": links,
                "tables": registry.get("tables", []),
            }

    def annotation_evidence_record(self, identity, key):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            for records in (
                evidence_registry(project).get("searches", {}),
                external_records(project),
            ):
                if key in records:
                    return records[key]
            raise ValueError("证据记录不属于当前项目。")

    def annotation_import_evidence(
        self, identity, revision, *, kind, source_name, scope, format, content
    ):
        provenance = {
            "name": source_name.strip(),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "format": format,
        }
        if not provenance["name"] or not scope.strip():
            raise ValueError("请填写证据来源和适用范围。")
        if format == "json":
            rows = json.loads(content)
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError("证据 JSON 必须由记录对象组成。")
        elif format in {"mgf", "msp"}:
            rows = parse_text_spectra(content, format=format)
        else:
            rows = [{"text": content}]
        if not rows or len(rows) > 10000:
            raise ValueError("证据记录数必须为 1 至 10000。")
        records = normalize_evidence(
            [
                {
                    **row,
                    "kind": kind,
                    "scope": {"description": scope.strip()},
                    "target": {"kind": "unmapped"},
                }
                for row in rows
            ],
            source=provenance,
        )
        with self.access(identity) as workspace:
            workspace.check(revision)
            candidate = project_candidate(workspace.require_project())
            external = external_records(candidate, write=True)
            for row in records:
                external.setdefault(
                    row["evidence_id"],
                    {
                        **row,
                        "created_at": datetime.now(UTC).isoformat(),
                        "user_id": (actor.get() or {}).get("id", workspace.owner_id),
                    },
                )
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": {"imported": len(records)}}

    def annotation_link(
        self, identity, revision, *, target, record_id, row, decision, reason, preview=False
    ):
        with self.access(identity) as workspace:
            workspace.check(revision)
            project = workspace.require_project()
            resolved = evidence_target(project, target)
            link = link_preview(project, resolved, record_id, row)
            if preview:
                return {"workspace": self.view(workspace), "value": link}
            if decision == "withdrawn" and link["decision"] != "linked":
                raise ValueError("只有已关联的证据可以撤回。")
            if not reason.strip():
                raise ValueError("请填写人工关联或撤回的理由。")
            candidate = project_candidate(project)
            links = evidence_registry(candidate, write=True).setdefault("links", {})
            history = list(links.get(link["id"], {}).get("history", []))
            if link["decision"] != decision:
                history.append(
                    {
                        "decision": decision,
                        "reason": reason.strip(),
                        "reviewer": (actor.get() or {}).get("id", workspace.owner_id),
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
            link.update(decision=decision, history=history)
            links[link["id"]] = link
            candidate.dirty = True
            workspace.project = candidate
            workspace.revision += 1
            return {"workspace": self.view(workspace), "value": link}
