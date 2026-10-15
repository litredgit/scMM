"""Scientific and persistence boundaries for non-destructive lipid annotations."""

import io
import json
import zipfile
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from pyopenms import EmpiricalFormula

from scMM.application import lipid_database as db
from scMM.application.workbench import AnalysisWorkspace
from scMM.util.lipid_annotation import (
    annotate_lipids,
    filtered_feature_ids,
    mass_candidates,
    version_valid,
)
from scMM.util.lipid_isotopes import ADDUCTS, adduct_shift, resolved_distribution
from scMM.util.lipid_rules import import_rules, rank_candidates, validate_rules


def sdf_record(identifier="LMGP01010001", formula="C10H20", name="Synthetic A"):
    mass = EmpiricalFormula(formula).getMonoWeight()
    return f"""{name}
  scMM synthetic

>  <LM_ID>
{identifier}

>  <NAME>
{name}

>  <EXACT_MASS>
{mass:.12f}

>  <FORMULA>
{formula}

>  <CATEGORY>
Glycerophospholipids [GP]

>  <MAIN_CLASS>
Glycerophosphocholines [GP01]

>  <ABBREVIATION>
PC 10:0

$$$$
"""


@pytest.fixture
def lipid_database(tmp_path, monkeypatch):
    root = tmp_path / "databases"
    root.mkdir()
    (root / "test.sdf").write_text(sdf_record() + sdf_record("LMGP01010002", name="Synthetic B"))
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(root))
    db._load_cached.cache_clear()
    return db.load_database()


def synthetic_data(adduct="[M+H]+", ratios=(1.0, 1.0), duplicate=False):
    parent_mz = EmpiricalFormula("C10H20").getMonoWeight() + adduct_shift(adduct)
    peak = resolved_distribution("C10H20", adduct, 3, parent_mz, 35000)[0]
    parent = np.linspace(100.0, 1000.0, 40)
    child = parent * peak["ratio"] * np.repeat(ratios, 20)
    X = np.column_stack((parent, child, parent * 0.3))
    masses = [parent_mz, peak["mz"], parent_mz + 10]
    if duplicate:
        X = np.column_stack((X, parent * 0.2))
        masses.append(parent_mz)
    data = AnnData(
        X,
        obs=pd.DataFrame({"sample": np.repeat(["a", "b"], 20)}, index=[f"c{i}" for i in range(40)]),
        var=pd.DataFrame({"mz": masses}, index=[f"f{i}" for i in range(len(masses))]),
    )
    state = AnalysisWorkspace()
    state.replace(data)
    data = state.require_data()
    data.layers["feature_snr"] = np.ones(data.shape) * 50
    return data


def options(adduct="[M+H]+"):
    return {
        "database": "test.sdf",
        "polarity": ADDUCTS[adduct]["polarity"],
        "adducts": [adduct],
        "annotation_ppm": 10.0,
        "isotope_ppm": 10.0,
        "max_isotope_order": 3,
        "isotope_tolerance": 0.2,
        "min_valid_cells": 20,
        "intensity_layer": "",
        "resolution": 35000.0,
    }


def test_ppm_bands_precede_scores_and_ties_remain_separate():
    rules = validate_rules(
        {"rules": [{"kind": "class", "level": "MAIN_CLASS", "value": "GP02", "score": 1000}]},
        ADDUCTS,
    )
    rows = [
        {
            "feature_id": "f",
            "candidate_id": str(i),
            "abs_ppm_error": ppm,
            "polarity": "pos",
            "adduct": "[M+H]+",
            "LM_ID": identifier,
        }
        for i, (ppm, identifier) in enumerate(
            [
                (2.001, "LMGP02010001"),
                (2.0, "LMGP01010001"),
                (0.1, "LMGP01010002"),
                (5.0, "LMGP01010003"),
                (5.001, "LMGP01010004"),
            ]
        )
    ]
    ranked = rank_candidates(rows, rules)
    assert [r["candidate_id"] for r in ranked] == ["1", "2", "0", "3", "4"]
    assert [r["candidate_id"] for r in ranked if r["top_ranked"]] == ["1", "2"]
    assert [r["ppm_band"] for r in ranked] == [1, 1, 2, 2, 3]


def test_rules_csv_specific_override_no_builtin_scores():
    rules = import_rules(
        "kind,level,value,polarity,adduct,score\nadduct,,,pos,[M+H]+,4\nadduct,MAIN_CLASS,GP01,pos,[M+H]+,8\nclass,CATEGORY,GP,,,,1\n".replace(
            "GP,,,,1", "GP,,,1"
        ),
        "csv",
        ADDUCTS,
    )
    row = {
        "feature_id": "f",
        "candidate_id": "a",
        "abs_ppm_error": 1,
        "polarity": "pos",
        "adduct": "[M+H]+",
        "LM_ID": "LMGP01010001",
    }
    result = rank_candidates([row], rules)[0]
    assert result["adduct_score"] == 8 and result["class_score"] == 1
    empty = rank_candidates([dict(row)], validate_rules({}, ADDUCTS))[0]
    assert empty["rule_score"] == 0 and not empty["scored"]
    with pytest.raises(ValueError):
        validate_rules(
            {"rules": [{"kind": "adduct", "adduct": "[M+H]+", "polarity": "neg", "score": 1}]},
            ADDUCTS,
        )
    with pytest.raises(ValueError):
        import_rules(
            '{"rules":[{"kind":"class","level":"CATEGORY","value":"GP","score":NaN}]}',
            "json",
            ADDUCTS,
        )


@pytest.mark.parametrize("adduct", list(ADDUCTS))
def test_positive_negative_ion_mass_round_trip(lipid_database, adduct):
    frame, identity = lipid_database
    mass = EmpiricalFormula("C10H20").getMonoWeight() + adduct_shift(adduct)
    rows = mass_candidates(frame, ["stable-id"], np.array([mass]), options(adduct), identity)
    assert len(rows) == 2
    assert all(row["abs_ppm_error"] < 1e-8 for row in rows)
    assert {row["name"] for row in rows} == {"Synthetic A", "Synthetic B"}


@pytest.mark.parametrize(
    "ratio,matched", [(0.79, False), (0.8, True), (1.0, True), (1.2, True), (1.21, False)]
)
def test_two_sided_isotope_boundaries_preserve_all_values(lipid_database, ratio, matched):
    database, identity = lipid_database
    data = synthetic_data(ratios=(ratio, ratio))
    before = data.copy()
    result = annotate_lipids(data, database, identity, options(), {})
    first = [r for r in result["relations"] if r["isotope_feature_id"] == "f1" and r["order"] == 1]
    assert len(first) == 4
    assert all(r["matched"] == matched for r in first)
    np.testing.assert_array_equal(data.X, before.X)
    pd.testing.assert_frame_equal(data.var, before.var)
    np.testing.assert_array_equal(data.layers["feature_snr"], before.layers["feature_snr"])
    assert len(result["candidates"]) == 2


def test_sample_conflicts_and_duplicate_mz_are_independent(lipid_database):
    database, identity = lipid_database
    data = synthetic_data(ratios=(1.0, 1.3), duplicate=True)
    result = annotate_lipids(data, database, identity, options(), {})
    assert {r["feature_id"] for r in result["candidates"]} == {"f0", "f3"}
    assert len({r["candidate_id"] for r in result["candidates"]}) == 4
    rows = [r for r in result["relations"] if r["parent_feature_id"] == "f0"]
    assert all(r["matched"] for r in rows if r["sample"] == "a")
    assert not any(r["matched"] for r in rows if r["sample"] == "b")
    assert {r["name"] for r in rows} == {"Synthetic A", "Synthetic B"}


def test_identity_normalization_reuse_filter_and_sample_changes_stale(lipid_database):
    database, identity = lipid_database
    data = synthetic_data()
    result = annotate_lipids(data, database, identity, options(), {})
    assert version_valid(data, result)
    data.X = data.X / data.X.sum(axis=1, keepdims=True)
    assert version_valid(data, result)
    assert not version_valid(data[:20].copy(), result)
    data.obs["sample"] = "changed"
    assert not version_valid(data, result)


def test_filtering_isotope_review_and_strongest_never_changes_matrix(lipid_database):
    database, identity = lipid_database
    data = synthetic_data(duplicate=True)
    result = annotate_lipids(data, database, identity, options(), {})
    result["selected"] = {"f0": [result["candidates"][0]["candidate_id"]]}
    filters = {"adduct_mode": "strongest", "include_unannotated": True}
    assert filtered_feature_ids(data, result, filters) == ["f0", "f1", "f2"]
    assert filtered_feature_ids(data, result, {**filters, "isotopes": "hide"}) == ["f0", "f2"]
    assert data.shape == (40, 4)
    for row in result["relations"]:
        row["review"] = "rejected"
    assert "f1" in filtered_feature_ids(data, result, {**filters, "isotopes": "hide"})


def test_potassium_distribution_includes_adduct_isotope():
    peaks = resolved_distribution("C10H20", "[M+K]+", 3, 179.0, 35000)
    carbon_only = resolved_distribution("C10H20", "[M+Na]+", 3, 163.0, 35000)
    assert (
        sum(p["ratio"] for p in peaks if p["order"] == 2)
        > sum(p["ratio"] for p in carbon_only if p["order"] == 2) + 0.05
    )


def test_distribution_matches_independent_carbon_hydrogen_binomial():
    peaks = resolved_distribution("C10H20", "[M+H]+", 3, 141.16, 35000)
    carbon, hydrogen = 0.0107 / 0.9893, 0.000115 / 0.999885
    expected_m1 = 10 * carbon + 21 * hydrogen
    expected_m2 = 45 * carbon**2 + 210 * hydrogen**2 + 210 * carbon * hydrogen
    assert sum(p["ratio"] for p in peaks if p["order"] == 1) == pytest.approx(expected_m1, rel=2e-6)
    assert sum(p["ratio"] for p in peaks if p["order"] == 2) == pytest.approx(expected_m2, rel=2e-6)


def test_known_transformed_and_snr_layers_rejected(lipid_database):
    database, identity = lipid_database
    data = synthetic_data()
    state = AnalysisWorkspace()
    state.replace(data)
    state.normalize("total")
    for layer in ("X", "scmm_normalize_0", "feature_snr"):
        with pytest.raises(ValueError):
            annotate_lipids(
                state.require_data(),
                database,
                identity,
                {**options(), "intensity_layer": layer},
                {},
            )
    assert annotate_lipids(state.require_data(), database, identity, options(), {})["candidates"]


def test_atomic_database_download_reuse_and_corrupt_file_preserved(tmp_path, monkeypatch):
    root = tmp_path / "database"
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(root))
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("../structures.sdf", sdf_record())
    monkeypatch.setattr(
        db.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(zipped.getvalue())
    )
    identity = db.prepare_database()
    assert identity["records"] == 1 and identity["source"] == db.LMSD_URL
    assert not (tmp_path / "structures.sdf").exists()
    monkeypatch.setattr(
        db.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("unexpected download")
    )
    assert db.prepare_database() == identity
    path = root / identity["filename"]
    path.write_text("corrupt")
    with pytest.raises(ValueError):
        db.prepare_database()
    assert path.read_text() == "corrupt"


def test_database_bad_archive_and_path_escape_fail_cleanly(tmp_path, monkeypatch):
    root = tmp_path / "database"
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(root))
    monkeypatch.setattr(
        db.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"not zip")
    )
    with pytest.raises(ValueError, match="压缩包"):
        db.prepare_database()
    assert not list(root.glob("*.sdf"))
    (root / "test.sdf").write_text(sdf_record())
    with pytest.raises((ValueError, PermissionError)):
        db.load_database("../test.sdf")
    outside = tmp_path / "outside.sdf"
    outside.write_text(sdf_record())
    (root / "escape.sdf").symlink_to(outside)
    with pytest.raises(PermissionError):
        db.load_database("escape.sdf")


@pytest.mark.parametrize("formula", ["invalid-formula", "C10H15D5"])
def test_missing_and_invalid_formula_keep_mass_candidates(lipid_database, formula):
    database, identity = lipid_database
    frame = database.copy()
    frame.loc[0, "FORMULA"] = formula
    result = annotate_lipids(synthetic_data(), frame, identity, options(), {})
    assert len(result["candidates"]) == 2
    assert len(result["diagnostics"]) == 1
    assert result["relations"]
    assert json.dumps(deepcopy(result), allow_nan=False)
