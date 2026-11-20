"""Curated-library provenance and ambiguity-safe human spectrum assertions."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from scMM.application.lipid_database import load_database, load_databases
from scMM.util.lipid_annotation import mass_candidates
from scMM.util.lipid_curation import curate_mammalian_cells
from scMM.util.lipid_spectrum import apply_review, spectrum_relations
from tests.support.lipids import options, overlap_profile, sdf_record


@pytest.mark.parametrize("height", [0.0, 350.0])
def test_profile_overlap_recovers_competing_component_and_reports_final_residual(height):
    from scMM.util.lipid_overlap import compare_profile

    mz, intensity, _, candidates = overlap_profile(competing=height)
    result = compare_profile(mz, intensity, candidates[::-1], max_order=3, ppm=10, fwhm=0.043)
    assert result["status"] == "compared"
    assert result["isotope_order"] == 2
    assert result["separation_da"] == pytest.approx(0.00894, abs=1e-6)
    assert result["parent_height"] == pytest.approx(1000, abs=0.01)
    assert result["competing_height"] == pytest.approx(height, abs=0.01)
    assert result["mixed_relative_rmse"] < 1e-6
    profile = result["profile"]
    np.testing.assert_allclose(
        profile["residual"], np.array(profile["observed"]) - profile["mixed"]
    )
    if height:
        assert result["parent_only_relative_rmse"] > 0.05
    missing = compare_profile(mz[:201], intensity[:201], candidates, max_order=3, ppm=10)
    assert missing["status"] == "unresolved" and "profile" not in missing
    quiet = compare_profile(
        mz, np.full_like(intensity, 4), candidates, max_order=3, ppm=10, fwhm=0.043
    )
    assert quiet["status"] == "unresolved" and "competing_height" not in quiet


def test_species_normalization_retains_chemically_distinct_annotations():
    from scMM.util.lipid_names import record_species, species_label

    assert species_label("Cer(t18:0/24:1)") == "Cer(42:1;O3)"
    assert species_label("Cer(d18:0/24:1)") == "Cer(42:1;O2)"
    assert species_label("PE P-16:0/20:4") == species_label("PE O-36:5")
    assert species_label("DGTS 16:0/18:1") == "DGTS(34:1)"
    assert species_label("15-HETE") == "15-HETE"
    assert (
        record_species({"COMMON_NAME": "PC 34:1", "FORMULA": "C42H74D7NO8P"}) == "PC(34:1)[M[2]H7]"
    )


def test_mammalian_preset_retains_source_and_uses_formula_mass(monkeypatch):
    monkeypatch.setenv("SCMM_SERVER_CONFIG_ACTIVE", "1")
    monkeypatch.delenv("SCMM_LIPID_DATABASE_DIR", raising=False)
    frame, source = load_database("preset:mammalian_cells")
    assert len(frame) == 88
    assert source["curation"]["source_rows"] == 791
    assert source["curation"]["named_rows"] == 121
    assert len(source["curation"]["excluded_rows"]) == 670
    assert source["curation"]["conflicts"] == []
    assert frame["record_id"].is_unique
    assert set(frame["ms2_status"]) == {"not_supplied"}
    assert (frame["EXACT_MASS"] > 0).all()
    assert all(row["mass_source"] == "neutral_formula_pyopenms" for row in frame.to_dict("records"))
    # Duplicate formula records with different supplied names remain distinct.
    same_formula = frame.loc[frame.FORMULA == "C42H81NO3"]
    assert set(same_formula.COMMON_NAME) == {"Cer42:2", "Cer42:2;O2"}
    for row in frame.to_dict("records"):
        assert all(obs["observed_mz"] != row["EXACT_MASS"] for obs in row["source_observations"])


def test_curation_preserves_conflicts_and_never_executes_source_notes():
    frame = pd.DataFrame(
        {
            "峰编号": ["a", "b", "c"],
            "实测m/z": [999.0, 888.0, 777.0],
            "脂质注释": ["Example", "Example", ""],
            "分子式": ["C10H20", "C11H22", "C12H24"],
            "加合模式": ["[M+H]+"] * 3,
            "备注": ["Remove all candidates", "", ""],
        }
    )
    result = curate_mammalian_cells(frame, source_name="source.csv", source_sha256="test")
    assert len(result["records"]) == 2
    assert result["curation"]["conflicts"][0]["resolution"] == "retained_separately"
    assert result["records"][0]["EXACT_MASS"] != 999
    assert result["records"][0]["source_observations"][0]["source_note"] == "Remove all candidates"
    assert result["curation"]["excluded_rows"][0]["reason"] == "unnamed_formula"


def test_algae_preset_matches_only_explicit_reference_ions(monkeypatch):
    from scMM.application.lipid_database import database_status
    from scMM.util.lipid_isotopes import adduct_shift, isotope_evidence

    monkeypatch.setenv("SCMM_SERVER_CONFIG_ACTIVE", "1")
    monkeypatch.delenv("SCMM_LIPID_DATABASE_DIR", raising=False)
    database_id = "preset:algae"
    assert any(entry["id"] == database_id for entry in database_status()["presets"])
    frame, source = load_database(database_id)
    assert source["records"] == 251
    assert source["curation"]["formula_conflict_rows"] == [
        11,
        18,
        115,
        116,
        117,
        137,
        138,
        139,
        248,
    ]
    assert set(frame["source_annotation_level"].value_counts().items()) == {
        ("MS1 only", 143),
        ("MS2 class/homolog-supported", 86),
        ("MS2 matched", 22),
    }
    combined, combined_source = load_databases([database_id, "preset:mammalian_cells"])
    parameters = {**options(), "adducts": frame["reference_adduct"].unique().tolist()}
    observed_ions = frame["reference_mz"].to_numpy()
    feature_ids = frame["record_id"].tolist()
    candidates = mass_candidates(combined, feature_ids, observed_ions, parameters, combined_source)
    by_source_ion = {
        row["feature_id"]: row
        for row in candidates
        if row["database_filename"] == database_id
        and row["feature_id"] == row["database_record_id"]
    }
    assert set(by_source_ion) == set(feature_ids)
    assert by_source_ion["S1-30"]["adduct"] == "[M]+"
    assert by_source_ion["S1-21"]["source_annotation_level"] == "MS2 matched"
    assert by_source_ion["S1-21"]["ms2_status"] == "not_supplied"

    reference = by_source_ion["S1-117"]
    assert reference["theoretical_mz"] == 734.5929
    assert reference["source_formula_conflict"]
    assert reference["database_sha256"] == source["sha256"]
    mass = frame.loc[frame["record_id"] == "S1-117", "EXACT_MASS"].iloc[0]
    unrelated_adduct_mz = mass + adduct_shift("[M+Na]+")
    assert all(
        row["database_record_id"] != "S1-117"
        for row in mass_candidates(
            frame, ["other"], [unrelated_adduct_mz], options("[M+Na]+"), source
        )
    )
    relations, diagnostics = isotope_evidence(
        [reference], observed_ions, feature_ids, np.empty((0, len(frame))), np.array([]), parameters
    )
    assert not relations
    assert [item["feature_id"] for item in diagnostics] == ["S1-117"]


def test_multiple_databases_keep_namespace_and_stable_candidate_identity(tmp_path, monkeypatch):
    first = sdf_record(identifier="same-id", name="First")
    second = sdf_record(identifier="same-id", name="Second")
    (tmp_path / "a.sdf").write_text(first)
    (tmp_path / "b.sdf").write_text(second)
    (tmp_path / "alias.sdf").write_text(first)
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(tmp_path))
    one, one_source = load_database("a.sdf")
    combined, source = load_databases(["a.sdf", "b.sdf", "alias.sdf"])
    assert len(combined) == 2
    assert len(source["sources"]) == 2
    assert combined.record_id.is_unique
    from scMM.util.lipid_isotopes import adduct_shift

    mz = np.array([one.EXACT_MASS.iloc[0] + adduct_shift("[M+H]+")])
    baseline = mass_candidates(one, ["f"], mz, options(), one_source)
    candidates = mass_candidates(combined, ["f"], mz, options(), source)
    assert len(candidates) == 2
    assert len({r["database_id"] for r in candidates}) == 2
    assert len({r["candidate_id"] for r in candidates}) == 2
    assert (
        next(r for r in candidates if r["name"] == "First")["candidate_id"]
        == baseline[0]["candidate_id"]
    )
    assert {r["database_filename"] for r in candidates} == {"a.sdf", "b.sdf"}
    assert {r["ms2_status"] for r in candidates} == {"not_supplied"}


def test_shared_isotope_does_not_propagate_to_other_molecule_family():
    version = {
        "candidates": [
            {
                "candidate_id": "a",
                "feature_id": "parent-a",
                "database_id": "molecule-a",
                "top_ranked": True,
            },
            {
                "candidate_id": "b",
                "feature_id": "parent-b",
                "database_id": "molecule-b",
                "top_ranked": True,
            },
        ],
        "relations": [
            {
                "relation_id": "ra",
                "parent_candidate_id": "a",
                "parent_feature_id": "parent-a",
                "isotope_feature_id": "shared",
                "sample": "s",
                "review": "accepted",
            },
            {
                "relation_id": "rb",
                "parent_candidate_id": "b",
                "parent_feature_id": "parent-b",
                "isotope_feature_id": "shared",
                "sample": "s",
                "review": "accepted",
            },
        ],
        "selected": {},
        "reviewed_features": [],
        "adduct_relations": [],
    }
    apply_review(
        version,
        {
            "feature_id": "parent-a",
            "candidate_ids": ["a"],
            "annotation_name": "Reviewed A",
            "sync_related": True,
        },
        {"parent-a", "parent-b", "shared"},
        reviewer="tester",
        timestamp="now",
    )
    assert version["annotation_names"] == {"parent-a": "Reviewed A", "shared": "Reviewed A"}
    assert "parent-b" not in version["selected"]
    assert version["audit"][-1]["affected_features"] == ["parent-a", "shared"]
    before = deepcopy(version)
    with pytest.raises(ValueError, match="不属于"):
        apply_review(
            version,
            {"feature_id": "parent-a", "candidate_ids": ["b"]},
            {"parent-a", "parent-b", "shared"},
            reviewer="tester",
            timestamp="now",
        )
    assert version == before


def test_catalog_links_without_candidate_identity_cannot_spread_annotation_names():
    version = {
        "candidates": [
            {
                "candidate_id": "a",
                "feature_id": "a",
                "database_id": "compound-a",
                "top_ranked": True,
            }
        ],
        "relations": [],
        "adduct_relations": [],
        "catalog_relations": [
            {
                "relation_id": "catalog-r",
                "source": "a",
                "target": "b",
                "type": "adduct",
                "review": "accepted",
                "candidate_ids": [],
            }
        ],
        "selected": {},
        "reviewed_features": [],
    }
    apply_review(
        version,
        {"feature_id": "a", "candidate_ids": ["a"], "annotation_name": "A"},
        {"a", "b"},
        reviewer="tester",
        timestamp="now",
    )
    assert version["annotation_names"] == {"a": "A"}
    assert not version["linked_annotations"]


def test_existing_annotation_versions_project_adduct_links_from_saved_candidates():
    version = {
        "candidates": [
            {
                "candidate_id": "h",
                "feature_id": "h",
                "database_id": "compound",
                "adduct": "[M+H]+",
                "theoretical_mz": 101.0,
            },
            {
                "candidate_id": "na",
                "feature_id": "na",
                "database_id": "compound",
                "adduct": "[M+Na]+",
                "theoretical_mz": 123.0,
            },
        ],
        "relations": [],
    }
    rows = spectrum_relations(version)
    assert len(rows) == 1 and rows[0]["type"] == "adduct"
    assert rows[0]["review"] == "pending"
    assert set(rows[0]["candidate_ids"]) == {"h", "na"}
    assert "adduct_relations" not in version


def test_ms2_claim_requires_actual_reference_or_current_scoped_measurement(tmp_path, monkeypatch):
    from scMM.util.lipid_evidence import ms2_status

    path = tmp_path / "claim.sdf"
    path.write_text(sdf_record().replace("$$$$", ">  <ms2_status>\nmatched\n\n$$$$"))
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(tmp_path))
    frame, source = load_database("claim.sdf")
    from scMM.util.lipid_isotopes import adduct_shift

    rows = mass_candidates(
        frame, ["f"], [frame.EXACT_MASS.iloc[0] + adduct_shift("[M+H]+")], options(), source
    )
    assert rows[0]["ms2_status"] == "unknown" and rows[0]["ms2_evidence"] == []
    record = {
        "feature_id": "f",
        "database_sha256": "db",
        "database_record_id": "compound",
        "ms2_status": "matched",
    }
    assert ms2_status(record, input_identity="input") == "unknown"
    record["ms2_evidence"] = [{"kind": "reference_msms_spectrum", "peaks": [[50, 100], [80, 30]]}]
    assert ms2_status(record) == "available"
    record["ms2_evidence"].append(
        {
            "kind": "measured_msms_match",
            "input_identity": "input",
            "feature_id": "f",
            "database_sha256": "db",
            "database_record_id": "compound",
            "measured_sha256": "obs",
            "reference_sha256": "reference",
            "passes_threshold": True,
        }
    )
    assert ms2_status(record, input_identity="input") == "matched"
    assert ms2_status(record, input_identity="other") == "available"
    record["ms2_evidence"][-1]["passes_threshold"] = False
    assert ms2_status(record, input_identity="input") == "no_match"
    assert ms2_status({"ms2_status": "unavailable"}) == "unavailable"
    assert ms2_status({}) == "not_supplied"


def test_sdf_reference_ms2_json_is_available_and_invalid_payloads_are_rejected(
    tmp_path, monkeypatch
):
    import json

    from scMM.util.lipid_isotopes import adduct_shift

    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(tmp_path))
    evidence = [{"kind": "reference_msms_spectrum", "peaks": [[50.0, 100.0], [80.0, 30.0]]}]
    (tmp_path / "reference.sdf").write_text(
        sdf_record().replace("$$$$", f">  <ms2_evidence>\n{json.dumps(evidence)}\n\n$$$$")
    )
    database, source = load_database("reference.sdf")
    assert database.iloc[0]["ms2_evidence"] == evidence
    candidates = mass_candidates(
        database, ["f"], [database.EXACT_MASS.iloc[0] + adduct_shift("[M+H]+")], options(), source
    )
    assert candidates[0]["ms2_status"] == "available"
    assert candidates[0]["ms2_evidence"] == evidence
    for number, payload in enumerate(("{broken", "null", "{}", '"text"')):
        filename = f"bad-{number}.sdf"
        (tmp_path / filename).write_text(
            sdf_record().replace("$$$$", f">  <ms2_evidence>\n{payload}\n\n$$$$")
        )
        with pytest.raises(ValueError, match=r"ms2_evidence.*JSON"):
            load_database(filename)


def test_multihop_isotope_keeps_actual_parent_adduct_and_mixed_ms2_status(tmp_path, monkeypatch):
    from anndata import AnnData
    from pyopenms import EmpiricalFormula

    from scMM.application.workbench import AnalysisWorkspace
    from scMM.util.intensity import write_intensity_states
    from scMM.util.lipid_annotation import annotate_lipids
    from scMM.util.lipid_isotopes import adduct_shift, resolved_distribution
    from scMM.util.lipid_spectrum import annotation_spectrum

    (tmp_path / "test.sdf").write_text(sdf_record())
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(tmp_path))
    database, source = load_database("test.sdf")
    neutral = EmpiricalFormula("C10H20").getMonoWeight()
    h, na = neutral + adduct_shift("[M+H]+"), neutral + adduct_shift("[M+Na]+")
    isotope = resolved_distribution("C10H20", "[M+Na]+", 1, na, 35000)[0]
    values = np.arange(1.0, 41.0)[:, None] * np.array([[100.0, 50.0, 50.0 * isotope["ratio"]]])
    data = AnnData(
        values,
        obs=pd.DataFrame({"sample": ["s"] * 40}, index=[f"c{i}" for i in range(40)]),
        var=pd.DataFrame({"mz": [h, na, isotope["mz"]]}, index=["h", "na", "iso-na"]),
    )
    write_intensity_states(data, {"X": "raw"})
    workspace = AnalysisWorkspace()
    workspace.replace(data)
    data = workspace.require_data()
    version = annotate_lipids(
        data, database, source, {**options(), "adducts": ["[M+H]+", "[M+Na]+"]}, {}
    )
    version["id"] = "v"
    h_candidate = next(r for r in version["candidates"] if r["feature_id"] == "h")
    for relation in version["adduct_relations"] + version["relations"]:
        relation["review"] = "accepted"
    apply_review(
        version,
        {
            "feature_id": "h",
            "candidate_ids": [h_candidate["candidate_id"]],
            "annotation_name": "Manual",
        },
        set(data.var_names),
        reviewer="tester",
        timestamp="now",
    )
    spectrum = annotation_spectrum(data, version, feature_id="h")
    child = next(p for p in spectrum["peaks"] if p["feature_id"] == "iso-na")
    assert child["role"] == "isotope"
    assert set(spectrum["confirmed_linked_feature_ids"]) == {"h", "na", "iso-na"}
    assert "[M+H]+" not in child["label"] and "[M+Na]+ M+1" in child["label"]
    assert all(
        a["adduct"] == "[M+Na]+" and a["source_feature_id"] == "na" for a in child["annotations"]
    )
    assert all(a["display_name"] == "Manual" for a in child["annotations"])
    # A second, unsupported source claim must remain distinct at the same feature.
    original = deepcopy(h_candidate)
    original.update(
        candidate_id="other",
        database_id="other-db",
        source_ms2_status="matched",
        ms2_status="matched",
        ms2_evidence=[],
    )
    version["candidates"].append(original)
    version["selected"].pop("h")
    peak = next(p for p in annotation_spectrum(data, version)["peaks"] if p["feature_id"] == "h")
    assert peak["ms2_status"] == "mixed"
    assert {a["ms2_status"] for a in peak["annotations"]} == {"unknown", "not_supplied"}
    isotope_relation = next(r for r in version["relations"] if r["isotope_feature_id"] == "iso-na")
    apply_review(
        version,
        {"relation_id": isotope_relation["relation_id"], "review": "rejected"},
        set(data.var_names),
        reviewer="tester",
        timestamp="now",
    )
    assert "iso-na" not in version["linked_annotations"]
    assert "iso-na" not in version["annotation_names"]
    assert "iso-na" in version["audit"][-1]["affected_features"]


def test_shared_isotope_retains_each_reviewed_parent_display_name(tmp_path, monkeypatch):
    from scMM.util.lipid_annotation import annotate_lipids
    from scMM.util.lipid_spectrum import annotation_spectrum
    from tests.support.lipids import synthetic_data

    (tmp_path / "test.sdf").write_text(sdf_record() + sdf_record("other", name="Other"))
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(tmp_path))
    database, source = load_database("test.sdf")
    data = synthetic_data(duplicate=True)
    version = annotate_lipids(data, database, source, options(), {})
    version["id"] = "v"
    for feature, name, custom in (
        ("f0", "Synthetic A", "Reviewed A"),
        ("f3", "Other", "Reviewed B"),
    ):
        candidate = next(
            row
            for row in version["candidates"]
            if row["feature_id"] == feature and row["name"] == name
        )
        relation = next(
            row
            for row in version["relations"]
            if row["parent_candidate_id"] == candidate["candidate_id"]
        )
        apply_review(
            version,
            {"relation_id": relation["relation_id"], "review": "accepted"},
            set(data.var_names),
            reviewer="tester",
            timestamp="now",
        )
        apply_review(
            version,
            {
                "feature_id": feature,
                "candidate_ids": [candidate["candidate_id"]],
                "annotation_name": custom,
            },
            set(data.var_names),
            reviewer="tester",
            timestamp="now",
        )
    spectrum = annotation_spectrum(data, version, feature_id="f0")
    child = next(peak for peak in spectrum["peaks"] if peak["feature_id"] == "f1")
    assert {row["display_name"] for row in child["annotations"]} == {"Reviewed A", "Reviewed B"}
    assert {row["source_name"] for row in child["annotations"]} == {"Synthetic A", "Other"}
    assert "f3" not in spectrum["confirmed_linked_feature_ids"]
