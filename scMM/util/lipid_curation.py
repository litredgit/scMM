"""Curate user-supplied lipid labels without treating observed m/z as neutral mass."""

import hashlib
import json
import re

import numpy as np


def curate_mammalian_cells(frame, *, source_name, source_sha256):
    """Keep named formula candidates and their original, non-identifying observations."""
    from pyopenms import EmpiricalFormula

    from .lipid_isotopes import ADDUCTS, adduct_shift

    required = {"峰编号", "实测m/z", "脂质注释", "分子式", "加合模式"}
    if not required <= set(frame):
        raise ValueError("Source lipid table is missing required columns")
    records, excluded, conflicts = {}, [], []
    source = frame.fillna("")
    for position, row in enumerate(source.to_dict(orient="records"), 2):
        name, formula = str(row["脂质注释"]).strip(), str(row["分子式"]).strip()
        reason = ""
        if not name:
            reason = "unnamed_formula" if formula else "unannotated"
        elif not formula:
            reason = "missing_neutral_formula"
        if reason:
            excluded.append({"row": position, "peak_id": str(row["峰编号"]), "reason": reason})
            continue
        try:
            molecule = EmpiricalFormula(formula)
            if molecule.getCharge() or "(" in formula or ")" in formula:
                raise ValueError("A neutral, unlabeled formula is required")
            mass = float(molecule.getMonoWeight())
            if not np.isfinite(mass) or mass <= 0:
                raise ValueError("Invalid formula mass")
        except (RuntimeError, ValueError) as exc:
            excluded.append({"row": position, "peak_id": str(row["峰编号"]), "reason": str(exc)})
            continue
        key = name, formula
        record = records.setdefault(
            key,
            {
                "record_id": "MC-" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16],
                "COMMON_NAME": name,
                "FORMULA": formula,
                "EXACT_MASS": mass,
                "mass_source": "neutral_formula_pyopenms",
                "MAIN_CLASS": re.match(r"[A-Za-z]+", name).group(0)
                if re.match(r"[A-Za-z]+", name)
                else "",
                "CATEGORY": "",
                "SUB_CLASS": "",
                "LM_ID": "",
                "ABBREVIATION": name,
                "INCHI_KEY": "",
                "species": name,
                "ms2_status": "not_supplied",
                "ms2_evidence": [],
                "source_observations": [],
            },
        )
        observation = {
            "row": position,
            "peak_id": str(row["峰编号"]),
            "observed_mz": float(row["实测m/z"]),
            "adduct": str(row["加合模式"]),
            "charge": int(row.get("电荷", 0) or 0),
            "source_note": str(row.get("备注", "")),
            "original_annotation": str(row.get("原始注释", "")),
        }
        if observation["adduct"] in ADDUCTS:
            theoretical = mass + adduct_shift(observation["adduct"])
            observation["formula_adduct_ppm_error"] = (
                observation["observed_mz"] / theoretical - 1
            ) * 1e6
        else:
            observation["formula_adduct_ppm_error"] = None
        record["source_observations"].append(observation)
    names = {}
    for record in records.values():
        names.setdefault(record["COMMON_NAME"], set()).add(record["FORMULA"])
    conflicts.extend(
        {"name": name, "formulas": sorted(formulas), "resolution": "retained_separately"}
        for name, formulas in names.items()
        if len(formulas) > 1
    )
    return {
        "schema_version": 1,
        "id": "preset:mammalian_cells",
        "label": "哺乳动物细胞数据库",
        "source": "user_supplied_lipid_annotation_table",
        "source_filename": source_name,
        "source_sha256": source_sha256,
        "intended_context": "mammalian_cells",
        "taxon_evidence": "not_supplied",
        "identification_status": "mass_candidates_not_structural_identifications",
        "ms2_status": "not_supplied",
        "mass_definition": "neutral monoisotopic mass calculated from supplied molecular formula",
        "records": sorted(records.values(), key=lambda r: (r["EXACT_MASS"], r["record_id"])),
        "curation": {
            "source_rows": len(source),
            "named_rows": int(source["脂质注释"].astype(str).str.strip().ne("").sum()),
            "formula_rows": int(source["分子式"].astype(str).str.strip().ne("").sum()),
            "searchable_records": len(records),
            "excluded_rows": excluded,
            "conflicts": conflicts,
            "rules": [
                "Observed m/z is retained as provenance and is never used as neutral exact mass.",
                "Only named records with a usable neutral formula enter the search library.",
                "Identical names and formulas share one record; different names remain distinct.",
                "Source notes are data, not filtering instructions or structural evidence.",
                "Missing MS/MS and taxonomic evidence are not inferred.",
            ],
        },
    }
