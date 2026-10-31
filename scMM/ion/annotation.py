"""Complete local compound candidates; rank is not identification probability."""

from copy import deepcopy
from dataclasses import dataclass

import numpy as np

from .identity import json_identity


@dataclass(frozen=True)
class CompoundIndex:
    records: tuple
    masses: object
    identity: str
    source: dict
    formula_mass_ppm: float

    def validate(self):
        expected = json_identity(
            {
                "source": self.source,
                "records": list(self.records),
                "formula_mass_ppm": self.formula_mass_ppm,
            }
        )
        if expected != self.identity or not np.array_equal(
            self.masses, [row["exact_mass"] for row in self.records]
        ):
            raise ValueError("compound index identity changed")


def build_compound_index(records, *, source, formula_mass_ppm=1.0):
    from pyopenms import EmpiricalFormula

    if not np.isfinite(formula_mass_ppm) or formula_mass_ppm < 0:
        raise ValueError("invalid formula consistency tolerance")
    normalized, identities = [], set()
    for source_record in records:
        row = deepcopy(dict(source_record))
        namespace, record_id = (
            str(row.get("namespace") or "").strip(),
            str(row.get("record_id") or "").strip(),
        )
        if not namespace or not record_id or (namespace, record_id) in identities:
            raise ValueError("compound namespace/record IDs must be explicit and unique")
        identities.add((namespace, record_id))
        formula = str(row.get("formula", "") or "").strip()
        formula_mass = None
        if formula:
            try:
                parsed = EmpiricalFormula(formula)
                if parsed.getCharge() or "(" in formula or ")" in formula:
                    raise ValueError("neutral unlabeled compound formula required")
                formula = (
                    parsed.toString().decode()
                    if isinstance(parsed.toString(), bytes)
                    else parsed.toString()
                )
                formula_mass = float(parsed.getMonoWeight())
            except RuntimeError as exc:
                raise ValueError(f"invalid formula for {namespace}:{record_id}") from exc
        supplied = row.get("exact_mass")
        mass = formula_mass if supplied in (None, "") else float(supplied)
        if mass is None or not np.isfinite(mass) or mass <= 0:
            raise ValueError("positive finite compound exact mass required")
        if (
            formula_mass is not None
            and abs(mass - formula_mass) / formula_mass * 1e6 > formula_mass_ppm
        ):
            raise ValueError(f"formula/exact mass conflict for {namespace}:{record_id}")
        record = {
            **row,
            "namespace": namespace,
            "record_id": record_id,
            "formula": formula,
            "exact_mass": mass,
            "name": str(row.get("name", "") or record_id),
            "formula_mass": formula_mass,
            "identity_resolution": "database_record_only",
        }
        record["record_hash"] = json_identity(record)
        normalized.append(record)
    if not normalized:
        raise ValueError("compound database is empty")
    normalized.sort(key=lambda r: (r["exact_mass"], r["namespace"], r["record_id"]))
    identity = json_identity(
        {"source": source, "records": normalized, "formula_mass_ppm": formula_mass_ppm}
    )
    masses = np.array([row["exact_mass"] for row in normalized], dtype=float)
    masses.flags.writeable = False
    return CompoundIndex(tuple(normalized), masses, identity, deepcopy(source), formula_mass_ppm)


def search_candidates(targets, database, specs, *, ppm=5.0):
    """Every tolerance hit is retained with source and conditional ion hypothesis."""
    if not np.isfinite(ppm) or not 0 <= ppm < 1e6:
        raise ValueError("invalid annotation tolerance")
    database.validate()
    rows, unknown = [], []
    for target in targets:
        target_id, kind = target["target_id"], target["target_kind"]
        before = len(rows)
        if kind not in {"feature", "ec", "formula"}:
            raise ValueError("unknown annotation target kind")
        value = target.get("mass")
        if kind != "formula" and (value is None or not np.isfinite(value) or value <= 0):
            unknown.append({"target_id": target_id, "reason": "mass_not_resolved"})
            continue
        forms = list(specs) if kind == "feature" else [None]
        if kind == "feature":
            if target.get("polarity") not in {"pos", "neg"}:
                raise ValueError("feature annotation requires measured polarity")
            forms = [spec for spec in forms if spec.polarity == target["polarity"]]
        for spec in forms:
            if kind == "formula":
                from pyopenms import EmpiricalFormula

                if not target.get("formula"):
                    raise ValueError("explicit nonempty formula target required")
                parsed_target = EmpiricalFormula(target["formula"])
                if parsed_target.getCharge() or parsed_target.getMonoWeight() <= 0:
                    raise ValueError("neutral formula target required")
                formula = parsed_target.toString()
                formula = formula.decode() if isinstance(formula, bytes) else formula
                matches = [r for r in database.records if r["formula"] == formula]
            else:
                low, high = (
                    spec.neutral_interval(value, ppm)
                    if spec
                    else (value / (1 + ppm * 1e-6), value / (1 - ppm * 1e-6))
                )
                start, stop = np.searchsorted(
                    database.masses, [np.nextafter(low, -np.inf), np.nextafter(high, np.inf)]
                )
                matches = database.records[start:stop]
            for record in matches:
                if spec and record["formula"]:
                    from pyopenms import EmpiricalFormula

                    molecule = EmpiricalFormula(record["formula"]).getElementalComposition()
                    addition = EmpiricalFormula(spec.add).getElementalComposition()
                    removal = EmpiricalFormula(spec.remove).getElementalComposition()
                    if any(
                        molecule.get(element, 0) * spec.oligomer + addition.get(element, 0) < count
                        for element, count in removal.items()
                    ):
                        continue
                theoretical = spec.mz(record["exact_mass"]) if spec else record["exact_mass"]
                error = None if kind == "formula" else (value - theoretical) / theoretical * 1e6
                if error is not None and abs(error) > np.nextafter(ppm, np.inf):
                    continue
                candidate = {
                    "target_id": target_id,
                    "target_kind": kind,
                    "hypothesis_id": target.get("hypothesis_id"),
                    "namespace": record["namespace"],
                    "record_id": record["record_id"],
                    "record_hash": record["record_hash"],
                    "database_identity": database.identity,
                    "formula": record["formula"],
                    "name": record["name"],
                    "species_id": spec.id if spec else None,
                    "theoretical_mass": theoretical,
                    "ppm_error": error,
                    "structure_id": record.get("structure_id"),
                    "identification_status": "mass_or_formula_candidate",
                    "supported_structure_level": "unresolved",
                    "manual_selection": False,
                    "ion_composition_check": "pass" if spec and record["formula"] else "unknown",
                    "ion_form_kind": "fragment_form"
                    if spec and spec.fragment_form
                    else "multimer"
                    if spec and spec.oligomer > 1
                    else "ion",
                    "polarity": target.get("polarity"),
                    "candidate_classification": {
                        key: record.get(key, "")
                        for key in (
                            "CATEGORY",
                            "MAIN_CLASS",
                            "SUB_CLASS",
                            "LIPID_CLASS",
                            "ABBREVIATION",
                            "LM_ID",
                        )
                    },
                }
                candidate["candidate_id"] = json_identity(candidate)
                rows.append(candidate)
        if len(rows) == before:
            unknown.append({"target_id": target_id, "reason": "no_mass_or_formula_match"})
    rows.sort(
        key=lambda r: (
            r["target_id"],
            abs(r["ppm_error"] or 0),
            r["namespace"],
            r["record_id"],
            r["species_id"] or "",
        )
    )
    return {
        "schema_version": 1,
        "database_identity": database.identity,
        "parameters": {"ppm": ppm},
        "candidates": rows,
        "unknown_targets": unknown,
        "rank_definition": "absolute_mass_error_then_stable_source_order_not_probability",
    }


def migrate_lipid_version(version):
    """Retain all legacy records and decisions without promoting old heuristics."""
    return {
        "schema_version": 1,
        "source_kind": "legacy_lipid_schema_1",
        "source_version_id": version["id"],
        "legacy_snapshot": deepcopy(version),
        "manual_assertions": deepcopy(version.get("selected", {})),
        "review_mapping": {
            row["relation_id"]: row.get("review", "pending") for row in version.get("relations", [])
        },
        "grouping_acceptance": {},
        "identification_status": "not_upgraded",
    }


def apply_lipid_ranking(result, rules):
    """Reuse existing declarative rules as sorting evidence, retaining all candidates."""
    from scMM.util.lipid_rules import score_candidate, validate_rules

    from .species import ION_SPECS

    validated = validate_rules(
        rules, {key: {"polarity": spec.polarity} for key, spec in ION_SPECS.items()}
    )
    candidate = deepcopy(result)
    for row in candidate["candidates"]:
        scoring = {
            **row.get("candidate_classification", {}),
            "polarity": row.get("polarity") or "",
            "adduct": row.get("species_id") or "",
        }
        row.update(score_candidate(scoring, validated))
        error = abs(row["ppm_error"] or 0)
        row["ppm_band"] = 1 if error <= 2 else 2 if error <= 5 else 3
    candidate["candidates"].sort(
        key=lambda row: (row["target_id"], row["ppm_band"], -row["rule_score"], row["candidate_id"])
    )
    candidate["ranking_policy"] = {
        "kind": "legacy_lipid_rules_heuristic",
        "rules": validated,
        "identity": json_identity(validated),
    }
    return candidate
