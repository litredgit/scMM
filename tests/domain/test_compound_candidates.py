"""Candidate completeness and scoped evidence are independent from identification."""

import numpy as np
import pytest

from scMM.ion.annotation import build_compound_index, migrate_lipid_version, search_candidates
from scMM.ion.evidence import normalize_evidence, parse_text_spectra, record_review
from scMM.ion.species import ION_SPECS


def test_same_formula_isomers_and_nonlipid_records_remain_separate():
    database = build_compound_index(
        [
            {"namespace": "test", "record_id": "one", "formula": "C6H12O6", "name": "isomer"},
            {"namespace": "test", "record_id": "two", "formula": "C6H12O6", "name": "isomer"},
        ],
        source={"version": "test"},
    )
    spec = ION_SPECS["[M+H]+"]
    target = {
        "target_id": "f",
        "target_kind": "feature",
        "mass": spec.mz(database.records[0]["exact_mass"]),
        "polarity": "pos",
    }
    results = search_candidates([target], database, [spec])
    assert len(results["candidates"]) == 2
    assert all(
        row["identification_status"] == "mass_or_formula_candidate" for row in results["candidates"]
    )
    assert len({row["candidate_id"] for row in results["candidates"]}) == 2
    unknown = search_candidates(
        [{"target_id": "e", "target_kind": "ec", "mass": None}], database, [spec]
    )
    assert unknown["unknown_targets"] and not unknown["candidates"]
    with pytest.raises(ValueError, match="conflict"):
        build_compound_index(
            [{"namespace": "t", "record_id": "a", "formula": "C6H12O6", "exact_mass": 200.0}],
            source={},
        )


def test_mgf_and_msp_are_parsed_without_search_and_reject_partial_records():
    spectra = parse_text_spectra(
        "BEGIN IONS\nTITLE=pool\nPEPMASS=181.07\n50 10\n100 20\nEND IONS\n", format="mgf"
    )
    assert len(spectra[0]["peaks"]) == 2
    rows = normalize_evidence(
        [
            {
                "kind": "bulk_msms",
                "target": {"kind": "unmapped"},
                "scope": {"sample_ids": ["pool"]},
                **spectra[0],
            }
        ],
        source={"sha": "synthetic"},
    )
    assert rows[0]["mapping_status"] == "unmatched"
    assert rows[0]["metadata"]["isolation_window"] is None
    assert "not_individual_cell" in rows[0]["transfer_scope"]
    with pytest.raises(ValueError, match="unterminated"):
        parse_text_spectra("BEGIN IONS\n50 2\n", format="mgf")
    with pytest.raises(ValueError, match="count"):
        parse_text_spectra("Name: test\nNum Peaks: 2\n50 1\n", format="msp")


def test_evidence_is_version_scoped_and_legacy_choices_are_not_upgraded():
    with pytest.raises(ValueError, match="version"):
        normalize_evidence(
            [{"kind": "experience", "scope": {}, "target": {"kind": "feature", "id": "f"}}],
            source={},
        )
    legacy = {"id": "old", "selected": {"f": ["candidate"]}, "relations": []}
    migrated = migrate_lipid_version(legacy)
    assert migrated["manual_assertions"] == legacy["selected"]
    assert migrated["grouping_acceptance"] == {}
    with pytest.raises(ValueError):
        record_review(
            {}, version="v", decision="accepted", reviewer="", timestamp="now", reason="r", scope={}
        )
    with pytest.raises(ValueError, match="peak"):
        normalize_evidence(
            [
                {
                    "kind": "standard",
                    "scope": {},
                    "target": {"kind": "unmapped"},
                    "peaks": [[50.0, np.inf]],
                }
            ],
            source={},
        )


def test_mass_only_evidence_mapping_retains_ambiguity_and_pool_scope():
    from scMM.ion.evidence import link_external_evidence

    evidence = normalize_evidence(
        [
            {
                "kind": "bulk_msms",
                "target": {"kind": "unmapped"},
                "scope": {"sample_ids": ["s1"]},
                "metadata": {"precursor_mz": 100.0, "polarity": "pos"},
            }
        ],
        source={},
    )
    targets = [
        {
            "kind": "feature",
            "id": key,
            "version": "root",
            "mz": 100.0,
            "polarity": "pos",
            "sample_ids": ["s1", "s2"],
        }
        for key in ["a", "b"]
    ]
    result = link_external_evidence(evidence, targets)[0]
    assert result["mapping_status"] == "ambiguous"
    assert all(link["sample_ids"] == ["s1"] for link in result["links"])
    assert result["review"] == "pending"


def test_lipid_rules_only_reorder_complete_candidates():
    from scMM.ion.annotation import apply_lipid_ranking

    database = build_compound_index(
        [
            {"namespace": "lipids", "record_id": "a", "formula": "C20H40O2", "MAIN_CLASS": "PC"},
            {"namespace": "lipids", "record_id": "b", "formula": "C20H40O2", "MAIN_CLASS": "PE"},
        ],
        source={},
    )
    spec = ION_SPECS["[M+H]+"]
    result = search_candidates(
        [
            {
                "target_id": "f",
                "target_kind": "feature",
                "polarity": "pos",
                "mass": spec.mz(database.records[0]["exact_mass"]),
            }
        ],
        database,
        [spec],
    )
    rules = {
        "name": "test",
        "rules": [{"kind": "class", "level": "MAIN_CLASS", "value": "PE", "score": 10}],
    }
    ranked = apply_lipid_ranking(result, rules)
    assert len(ranked["candidates"]) == 2
    assert ranked["candidates"][0]["record_id"] == "b"
    assert "rule_score" not in result["candidates"][0]
    assert all(row["supported_structure_level"] == "unresolved" for row in ranked["candidates"])
