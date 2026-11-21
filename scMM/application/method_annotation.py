"""Adapt feature-annotation plugins to the existing version and review store."""

import math
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd

from scMM.ion.identity import json_identity
from scMM.plugins import AnnotationCandidate, FeatureInput
from scMM.util.lipid_annotation import dataset_inputs
from scMM.util.lipid_rules import rank_candidates

from .annotation_sources import feature_source, source_versions
from .web_lipids import persist_source_annotation


def annotate(project, source, method, options):
    data, _ = feature_source(project, source)
    features, mz, _, _, layer, identity = dataset_inputs(data, "", mass_only=True)
    masses = dict(zip(features, map(float, mz), strict=True))
    raw = method.method.run(FeatureInput(pd.DataFrame({"mz": mz}, index=features)), options.copy())
    provenance = method.provenance(options)
    origin = json_identity(provenance)
    rows = []
    ids = set()
    for candidate in raw:
        if (
            not isinstance(candidate, AnnotationCandidate)
            or any(
                type(value) is not str
                for value in (
                    candidate.feature_id,
                    candidate.name,
                    candidate.accession,
                    candidate.formula,
                    candidate.adduct,
                )
            )
            or candidate.feature_id not in masses
            or not candidate.name.strip()
            or not math.isfinite(candidate.theoretical_mz)
            or candidate.theoretical_mz <= 0
        ):
            raise ValueError("注释候选缺少有效峰 ID、名称或理论 m/z。")
        accession = candidate.accession or candidate.name
        expected = float(candidate.theoretical_mz)
        query = masses[candidate.feature_id]
        ppm = (query - expected) / expected * 1e6
        key = json_identity([origin, candidate.feature_id, accession, candidate.adduct, expected])[
            :24
        ]
        if key in ids or not math.isfinite(ppm):
            raise ValueError("注释候选重复或质量误差不合法。")
        ids.add(key)
        rows.append(
            {
                "candidate_id": key,
                "feature_id": candidate.feature_id,
                "query_mz": query,
                "database_id": accession,
                "database_record_id": accession,
                "name": candidate.name,
                "species": candidate.name,
                "formula": candidate.formula,
                "adduct": candidate.adduct,
                "polarity": "",
                "theoretical_mz": expected,
                "ppm_error": ppm,
                "abs_ppm_error": abs(ppm),
                "database_sha256": origin,
                "database_source": "plugin",
                "database_filename": method.id,
                "ms2_status": "not_supplied",
                "source_ms2_status": "not_supplied",
                "ms2_evidence": [],
                **{
                    key: ""
                    for key in (
                        "LM_ID",
                        "CATEGORY",
                        "MAIN_CLASS",
                        "SUB_CLASS",
                        "ABBREVIATION",
                        "INCHI_KEY",
                    )
                },
            }
        )
    rules = {"schema_version": 1, "rules": []}
    version = {
        "id": uuid4().hex,
        "label": method.method.label,
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": 1,
        "input_identity": identity,
        "intensity_layer": layer,
        "mass_only": True,
        "database": {"sha256": origin, "source": "plugin", "filename": method.id},
        "parameters": {"mass_only": True, "plugin": provenance, "intensity_layer": layer},
        "rules": rules,
        "candidates": rank_candidates(rows, rules),
        "relations": [],
        "adduct_relations": [],
        "diagnostics": [],
        "selected": {},
        "reviewed_features": [],
        "review_revision": 0,
        "annotation_names": {},
        "linked_annotations": {},
        "audit": [],
        "review_conflicts": [],
    }
    store = source_versions(project, data, source)
    store["versions"].append(version)
    store["active"] = version["id"]
    persist_source_annotation(project, data, source, store)
    return {"version": version["id"], "candidates": len(rows)}
