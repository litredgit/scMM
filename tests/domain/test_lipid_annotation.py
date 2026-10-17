"""Scientific and persistence boundaries for non-destructive lipid annotations."""

import io
import json
import zipfile
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from pyopenms import EmpiricalFormula

from scMM.application import lipid_database as db
from scMM.application.workbench import AnalysisWorkspace
from scMM.util.lipid_annotation import (
    annotate_lipids,
    dataset_inputs,
    filtered_feature_ids,
    mass_candidates,
    version_valid,
)
from scMM.util.lipid_isotopes import ADDUCTS, adduct_shift, resolved_distribution
from scMM.util.lipid_rules import import_rules, rank_candidates, validate_rules
from tests.support.lipids import options, sdf_record, synthetic_data


@pytest.fixture
def lipid_database(tmp_path, monkeypatch):
    root = tmp_path / "databases"
    root.mkdir()
    (root / "test.sdf").write_text(sdf_record() + sdf_record("LMGP01010002", name="Synthetic B"))
    monkeypatch.setenv("SCMM_LIPID_DATABASE_DIR", str(root))
    db._load_cached.cache_clear()
    return db.load_database()


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


def network_data(conflict=False):
    from anndata import AnnData

    parent_mz = EmpiricalFormula("C10H20").getMonoWeight() + adduct_shift("[M+H]+")
    isotope = resolved_distribution("C10H20", "[M+H]+", 3, parent_mz, 35000)[0]
    x = np.tile(np.arange(1, 61, dtype=float), 3)
    sodium = x * 2
    if conflict:
        sodium[-60:] = sodium[-60:][::-1]
    matrix = np.column_stack([x, sodium, x * isotope["ratio"], x**2 + 3, np.ones(180)])
    data = AnnData(
        matrix,
        obs=pd.DataFrame(
            {"sample_id": np.repeat(["a", "b", "c"], 60), "group": "control"},
            index=[f"c{i}" for i in range(180)],
        ),
        var=pd.DataFrame(
            {
                "mz": [
                    parent_mz,
                    parent_mz + adduct_shift("[M+Na]+") - adduct_shift("[M+H]+"),
                    isotope["mz"],
                    300.0,
                    400.0,
                ]
            },
            index=["h", "na", "iso", "unknown", "constant"],
        ),
    )
    workspace = AnalysisWorkspace()
    workspace.replace(data)
    return workspace.require_data()


def network_annotation(data, lipid_database, **network):
    database, identity = lipid_database
    return annotate_lipids(
        data,
        database,
        identity,
        {
            **options(),
            "adducts": ["[M+H]+", "[M+Na]+"],
            "network": {"condition_field": "group", **network},
        },
        {},
    )


def test_network_chemical_gate_isomer_ties_and_replicate_conflict(lipid_database):
    data = network_data(conflict=True)
    version = network_annotation(data, lipid_database)
    assert len(version["candidates"]) == 4
    for row in version["candidates"]:
        assert row["network_level"] == 2
        assert row["top_ranked"]
    adducts = [link for link in version["network"]["chemical_links"] if link["type"] == "adduct"]
    assert len(adducts) == 2
    for link in adducts:
        summary = link["consensus"][0]
        assert summary["support_samples"] == ["a", "b"]
        assert summary["evaluable_samples"] == 3
        assert summary["support_fraction"] == 2 / 3
        assert summary["direction_conflict"] and summary["inconsistent"]
    # Unrelated but highly correlated feature has exploratory edges, no chemical support.
    assert any(e["target"] == "unknown" for e in version["network"]["feature_edges"])
    assert not any(
        "unknown" in {e["source"], e["target"]} for e in version["network"]["chemical_links"]
    )
    assert all(r["network_inconsistent"] for r in version["candidates"])


def test_network_joint_zeros_constant_and_insufficient_are_not_opposition():
    from scMM.util.lipid_network import DEFAULTS, consensus, correlation_matrix, pair_statistics

    raw = np.column_stack(
        [
            np.r_[np.zeros(90), np.arange(1, 11)],
            np.r_[np.zeros(90), np.arange(10, 0, -1)],
            np.ones(100),
        ]
    )
    rho = correlation_matrix(raw, "spearman")
    assert rho[0, 1] > 0.9  # Shared zeros alone would misleadingly support the pair.
    row = pair_statistics(raw, raw > 0, 0, 1, rho[0, 1], {**DEFAULTS, "min_joint_cells": 5})
    assert row["rho_joint"] == pytest.approx(-1) and not row["supported"]
    insufficient = pair_statistics(raw, raw > 0, 0, 1, rho[0, 1], DEFAULTS)
    assert not insufficient["evaluable"] and insufficient["joint_cells"] == 10
    constant = pair_statistics(raw, raw > 0, 0, 2, rho[0, 2], {**DEFAULTS, "min_joint_cells": 5})
    assert constant["rho_all"] is None and not constant["evaluable"]
    result = consensus(
        [
            {"sample": "a", **row, "supported": True},
            {"sample": "b", **row, "supported": True},
            {"sample": "c", **insufficient},
        ],
        dict.fromkeys(["a", "b", "c"], "control"),
        DEFAULTS,
    )[0]
    assert result["evaluable_samples"] == 2 and result["support_fraction"] == 1
    assert result["replicate_support"]


def test_network_sample_separation_and_no_implicit_replicates():
    from scMM.util.lipid_network import DEFAULTS, calculate_network, consensus, correlation_matrix

    x = np.r_[np.arange(1.0, 61), np.arange(101.0, 161)]
    y = np.r_[np.arange(60.0, 0, -1), np.arange(160.0, 100, -1)]
    values = np.column_stack([x, y])
    assert correlation_matrix(values, "spearman")[0, 1] > 0
    rows = calculate_network(
        values, values, ["a", "b"], np.repeat(["s1", "s2"], 60), ["s1", "s2"], DEFAULTS
    )[0]["samples"]
    assert all(r["rho_all"] == pytest.approx(-1) and not r["supported"] for r in rows)
    assert consensus(rows, {}, DEFAULTS) == []


def test_network_methods_ranks_and_total_full_features(lipid_database):
    from scipy.stats import pearsonr, spearmanr

    from scMM.util.lipid_network import DEFAULTS, correlation_matrix, network_inputs

    data = network_data()
    ids, _, raw, samples, layer, _ = dataset_inputs(data)
    molecular, mapping, selected, _ = network_inputs(data, raw, samples, DEFAULTS, layer)
    np.testing.assert_allclose(molecular, raw / raw.sum(axis=1, keepdims=True))
    assert mapping == {} and selected == ["a", "b", "c"] and len(ids) == 5
    array = raw[:60, [0, 3]]
    assert correlation_matrix(array, "pearson")[0, 1] == pytest.approx(pearsonr(*array.T).statistic)
    assert correlation_matrix(array, "spearman")[0, 1] == pytest.approx(
        spearmanr(*array.T).statistic
    )
    version = network_annotation(data, lipid_database, condition_field="")
    assert all(r["network_level"] == 1 for r in version["candidates"])
    assert version["network"]["conditions"] == {}


def test_network_identity_layers_group_scope_and_failure(lipid_database):
    from scMM.util.lipid_network import intensity_layers

    data = network_data()
    version = network_annotation(data, lipid_database)
    assert version_valid(data, version)
    changed = data.copy()
    changed.obs.loc[changed.obs.sample_id == "a", "group"] = "treated"
    assert not version_valid(changed, version)
    changed = data.copy()
    changed.layers[version["intensity_layer"]][0, 0] += 1
    assert not version_valid(changed, version)
    with pytest.raises(ValueError, match="条件必须唯一"):
        data.obs.loc["c0", "group"] = "other"
        network_annotation(data, lipid_database)
    data.obs["group"] = "control"
    with pytest.raises(ValueError, match="不存在"):
        network_annotation(data, lipid_database, samples=["missing"])
    workspace = AnalysisWorkspace()
    workspace.replace(data)
    workspace.normalize("total")
    layer = "scmm_normalize_0"
    assert layer in intensity_layers(workspace.data)["molecule"]
    assert layer not in intensity_layers(workspace.data)["raw"]
    version = network_annotation(workspace.data, lipid_database, molecule_layer=layer)
    assert version_valid(workspace.data, version)
    workspace.data.layers[layer][0, 0] += 0.1
    assert not version_valid(workspace.data, version)
    workspace.impute()
    assert "scmm_impute_0" not in intensity_layers(workspace.data)["molecule"]
    with pytest.raises(ValueError, match="未插补强度"):
        network_annotation(workspace.data, lipid_database, molecule_layer="scmm_impute_0")


def test_network_representatives_pie_and_manual_priority(lipid_database):
    from scMM.util.lipid_network_views import annotation_charts, representatives

    data = network_data()
    version = network_annotation(data, lipid_database)
    version["id"] = "v"
    assert representatives(version)[1] == {}  # Ranking first never resolves two isomers.
    first = next(r for r in version["candidates"] if r["feature_id"] == "h")
    same = next(
        r
        for r in version["candidates"]
        if r["feature_id"] == "na" and r["database_id"] == first["database_id"]
    )
    version["selected"] = {"h": [first["candidate_id"]], "na": [same["candidate_id"]]}
    assert (
        representatives(version)[2][first["database_id"]] == "na"
    )  # Equal detection, stronger raw.
    version["network"]["representatives"][first["database_id"]] = "h"
    assert representatives(version)[2][first["database_id"]] == "h"
    # One feature with cross-class candidates must be counted once as ambiguous.
    other = next(r for r in version["candidates"] if r["feature_id"] == "h" and r != first)
    other["MAIN_CLASS"] = "other class"
    mz = dict(zip(data.var_names, data.var.mz, strict=True))
    chart = annotation_charts(
        version, list(data.var_names), mz, version["candidates"], {}, {"node_limit": 1}
    )
    assert chart["pie"]["denominator"] == 5
    assert sum(r["count"] for r in chart["pie"]["counts"]) == 5
    assert not any(r["classification"] == "多义" for r in chart["pie"]["counts"])
    assert chart["network"]["truncated"]
    assert len(version["network"]["feature_edges"]) > 1
    version["selected"].pop("h")
    chart = annotation_charts(version, list(data.var_names), mz, version["candidates"], {})
    assert next(r for r in chart["pie"]["counts"] if r["classification"] == "多义")["count"] == 1
    assert "h" not in representatives(version)[0]


def test_network_representative_detection_equal_sample_weight(lipid_database):
    from scMM.util.lipid_network_views import representatives

    data = network_data()
    raw = data.layers["scmm_input_0"]
    # H is detected in a,b only; Na in all samples, despite H's huge mean intensity.
    raw[:, 0] *= 10000
    raw[120:, 0] = 0
    version = network_annotation(data, lipid_database)
    rows = version["candidates"]
    identity = rows[0]["database_id"]
    version["selected"] = {
        f: [
            next(
                r["candidate_id"]
                for r in rows
                if r["database_id"] == identity and r["feature_id"] == f
            )
        ]
        for f in ["h", "na"]
    }
    assert representatives(version)[2][identity] == "na"
    assert version["network"]["representative_metrics"]["h"]["detection_rate"] == pytest.approx(
        2 / 3
    )


def test_network_level_follows_ppm_before_rule_score():
    rows = [
        dict(
            feature_id="f",
            candidate_id=str(i),
            abs_ppm_error=ppm,
            polarity="pos",
            adduct="[M+H]+",
            network_level=level,
        )
        for i, (ppm, level) in enumerate([(1.0, 0), (1.0, 2), (3.0, 2)])
    ]
    ranked = rank_candidates(rows, validate_rules({}, ADDUCTS))
    assert [r["candidate_id"] for r in ranked] == ["1", "0", "2"]
    assert [r["candidate_id"] for r in ranked if r["top_ranked"]] == ["1"]


def test_network_different_layers_can_have_opposite_edges(lipid_database):
    version = network_annotation(network_data(), lipid_database)
    raw = next(
        e
        for e in version["network"]["feature_edges"]
        if {e["source"], e["target"]} == {"h", "unknown"}
    )
    total = next(
        e
        for e in version["network"]["molecule_edges"]
        if {e["source"], e["target"]} == {"h", "unknown"}
    )
    assert raw["samples"][0]["rho_all"] > 0.99
    assert total["samples"][0]["rho_all"] < -0.9


def test_network_representative_does_not_weight_large_sample_more(lipid_database):
    from scMM.util.lipid_network_views import representatives

    data = network_data()[list(range(60)) + list(range(60, 66)) + list(range(120, 126))].copy()
    raw = data.layers["scmm_input_0"]
    raw[:, 0] *= 10000
    raw[60:, 0] = 0
    raw[:30, 1] = 0
    version = network_annotation(data, lipid_database, samples=["a"])
    rows = version["candidates"]
    identity = rows[0]["database_id"]
    version["selected"] = {
        f: [
            next(
                r["candidate_id"]
                for r in rows
                if r["database_id"] == identity and r["feature_id"] == f
            )
        ]
        for f in ["h", "na"]
    }
    assert (raw[:, 0] > 0).mean() > (raw[:, 1] > 0).mean()  # Pooled detection would choose H.
    assert representatives(version)[2][identity] == "na"
    assert version["network"]["representative_metrics"]["h"]["detection_rate"] == pytest.approx(
        1 / 3
    )
    # Representative metrics also include samples outside the correlation display scope.
    assert version["network"]["samples"] == ["a"]


def test_network_review_does_not_bypass_theoretical_ratio(lipid_database):
    from scMM.util.lipid_network import apply_support

    version = network_annotation(network_data(), lipid_database)
    for relation in version["relations"]:
        relation["matched"] = False
        relation["review"] = "accepted"
    apply_support(version)
    assert not any(
        link["level"] for link in version["network"]["chemical_links"] if link["type"] == "isotope"
    )
    for relation in version["relations"]:
        relation["matched"] = True
        relation["review"] = "rejected"
    apply_support(version)
    assert not any(
        link["level"] for link in version["network"]["chemical_links"] if link["type"] == "isotope"
    )


def test_network_insufficient_isotope_ratio_and_missing_sample(lipid_database):
    from scMM.util.lipid_network import apply_support

    data = network_data()
    version = network_annotation(data, lipid_database)
    for row in version["relations"]:
        row["valid_cells"] = 1
        row["matched"] = False
    apply_support(version)
    for link in version["network"]["chemical_links"]:
        if link["type"] == "isotope":
            assert not any(r["evaluable"] for r in link["samples"])
            assert link["consensus"][0]["evaluable_samples"] == 0
    data.obs.loc["c0", "sample_id"] = ""
    with pytest.raises(ValueError, match="样本身份存在缺失"):
        network_annotation(data, lipid_database)


def test_network_same_formula_support_is_shared_without_recursive_propagation(lipid_database):
    from scMM.util.lipid_network import apply_support

    version = network_annotation(network_data(), lipid_database)
    source = next(r for r in version["candidates"] if r["feature_id"] == "h")
    clone = {**source, "candidate_id": "other-isomer", "database_id": "other-structure"}
    version["candidates"].append(clone)
    # New isomer has no Na candidate and no isotope records of its own.
    apply_support(version)
    assert clone["network_level"] == source["network_level"] == 2
    assert clone["network_samples"] == source["network_samples"]
    assert any(
        "other-isomer" in link["equivalent_candidate_ids"]
        for link in version["network"]["chemical_links"]
    )
