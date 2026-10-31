"""Constrained groups, explicit review and independent L1/L2 semantics."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.ion.hypotheses import infer_groups
from scMM.ion.relations import find_relations
from scMM.ion.representation import (
    build_representations,
    materialize_complete_availability,
    preview_complete_availability,
)
from scMM.ion.semantics import unknown_state, write_value_states
from scMM.ion.species import CARBON13_SHIFT, ION_SPECS


def setup_group(max_states=100000):
    spec = ION_SPECS["[M+H]+"]
    parent = spec.mz(500.0)
    data = AnnData(
        np.array([[10.0, 1.0, 7.0], [5.0, 0.5, 4.0]]),
        obs=pd.DataFrame(index=["c1", "c2"]),
        var=pd.DataFrame(
            {"mz": [parent, parent + CARBON13_SHIFT, 800.0]}, index=["parent", "child", "unknown"]
        ),
    )
    write_value_states(data, {"X": {**unknown_state(), "space": "linear_abundance"}})
    rows = find_relations(data, [spec], polarity="pos", charge_magnitudes=(1,))["relations"]
    grouping = infer_groups(data, rows, [spec], max_states=max_states)
    return data, rows, grouping


def test_reviewed_views_preserve_unknown_and_source_and_choose_fixed_ion():
    data, rows, grouping = setup_group()
    group = next(g for g in grouping["groups"] if set(g["feature_ids"]) == {"parent", "child"})
    hypothesis = next(
        h for h in group["hypotheses"] if h["members"]["parent"]["isotope_shift"] == 0
    )
    selection = {
        "ec_id": group["ec_id"],
        "hypothesis_id": hypothesis["hypothesis_id"],
        "review": "accepted",
        "relation_ids": [rows[0]["relation_id"]],
    }
    l1, l2, metadata = build_representations(
        data, grouping, [selection], relation_reviews={rows[0]["relation_id"]: "accepted"}
    )
    assert l1.var_names.tolist() == ["parent", "unknown"]
    assert metadata["quantifiers"][0]["quantifier_feature_id"] == "parent"
    np.testing.assert_array_equal(l2.X[:, 0], data.X[:, 0])
    assert data.shape == (2, 3)
    with pytest.raises(ValueError, match="two selected"):
        build_representations(
            data,
            grouping,
            [selection, selection],
            relation_reviews={rows[0]["relation_id"]: "accepted"},
        )
    with pytest.raises(ValueError, match="not been accepted"):
        build_representations(data, grouping, [selection], relation_reviews={})


def test_incomplete_search_and_fragment_bridges_never_publish_groups():
    data, _rows, grouping = setup_group(max_states=1)
    assert any(not row["search_complete"] for row in grouping["diagnostics"])
    if grouping["groups"]:
        group = grouping["groups"][0]
        with pytest.raises(ValueError, match="incomplete"):
            build_representations(
                data,
                grouping,
                [
                    {
                        "ec_id": group["ec_id"],
                        "hypothesis_id": group["hypotheses"][0]["hypothesis_id"],
                    }
                ],
                relation_reviews={},
            )
    only_fragments = [
        {"left_feature_id": "parent", "right_feature_id": "unknown", "kind": "neutral_loss"}
    ]
    assert not infer_groups(data, only_fragments, [ION_SPECS["[M+H]+"]])["groups"]


def test_structural_missingness_and_preview_identity():
    source = AnnData(
        np.array([[1.0, np.nan], [0.0, 3.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame(index=["x", "y"]),
    )
    source.layers["scmm_quantifiable"] = np.array([[True, False], [True, True]])
    preview = preview_complete_availability(source, cell_ids=["a", "b"])
    assert preview["variable_ids"] == ["x"]
    matrix = materialize_complete_availability(source, preview)
    assert matrix.X[1, 0] == 0
    source.X[1, 0] = 5
    with pytest.raises(ValueError, match="stale"):
        materialize_complete_availability(source, preview)


def test_exploratory_mode_does_not_create_manual_acceptance():
    from scMM.ion.relations import assess_isotope_ratios, formula_relations, measure_evidence
    from scMM.ion.representation import build_exploratory_representations
    from scMM.ion.species import resolved_isotopes
    from scMM.util.intensity import write_intensity_states

    spec = ION_SPECS["[M+H]+"]
    peak = resolved_isotopes("C20H40O2", spec, parent_mz=314.0, resolution_200=70000.0)[0]
    data = AnnData(
        np.tile([10.0, 10.0 * peak["ratio"]], (25, 1)),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(25)]),
        var=pd.DataFrame({"mz": [314.0, peak["mz"]]}, index=["parent", "child"]),
    )
    write_value_states(data, {"X": {**unknown_state(), "space": "linear_abundance"}})
    write_intensity_states(data, {"X": "raw"})
    rows = formula_relations(
        data,
        [{"feature_id": "parent", "species_id": spec.id, "formula": "C20H40O2"}],
        polarity="pos",
        resolution_200=70000.0,
    )
    grouping = infer_groups(data, rows, [spec])
    evidence = assess_isotope_ratios(rows, measure_evidence(data, rows))
    l1, l2, metadata = build_exploratory_representations(data, grouping, evidence)
    assert l1.n_vars == 1 and l2.n_vars == 1
    assert metadata["decision_mode"] == "exploratory_v1"
    assert all(row["review"] == "pending" for row in rows)
    evidence[0]["ratio_status"] = "fail"
    l1, l2, metadata = build_exploratory_representations(data, grouping, evidence)
    assert l1.n_vars == 2 and l2 is None


def test_role_slot_collision_retains_competing_groups():
    data, rows, _ = setup_group()
    data.var.loc["unknown", "mz"] = data.var.loc["child", "mz"]
    rows = find_relations(data, [ION_SPECS["[M+H]+"]], polarity="pos")["relations"]
    grouping = infer_groups(data, rows, [ION_SPECS["[M+H]+"]])
    assert grouping["groups"]
    assert not any(len(group["feature_ids"]) == 3 for group in grouping["groups"])
    assert {tuple(group["feature_ids"]) for group in grouping["groups"]} >= {
        ("child", "parent"),
        ("parent", "unknown"),
    }


def test_pairwise_mass_bridges_do_not_form_a_whole_group():
    specs = [ION_SPECS[name] for name in ("[M+H]+", "[M+Na]+", "[M+K]+")]
    masses = [spec.mz(mass) for spec, mass in zip(specs, [500.0, 500.004, 500.008], strict=True)]
    data = AnnData(np.ones((2, 3)), var=pd.DataFrame({"mz": masses}, index=["a", "b", "c"]))
    rows = find_relations(data, specs, polarity="pos")["relations"]
    grouping = infer_groups(data, rows, specs)
    assert {tuple(group["feature_ids"]) for group in grouping["groups"]} >= {("a", "b"), ("b", "c")}
    assert not any(len(group["feature_ids"]) == 3 for group in grouping["groups"])


def test_unknown_adduct_envelope_does_not_invent_neutral_mass():
    data = AnnData(
        np.array([[10.0, 1.0], [8.0, 0.8]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame({"mz": [500.0, 500.0 + CARBON13_SHIFT / 2]}, index=["parent", "child"]),
    )
    write_value_states(data, {"X": {**unknown_state(), "space": "linear_abundance"}})
    rows = find_relations(data, [], polarity="pos", charge_magnitudes=(2,))["relations"]
    grouping = infer_groups(data, rows, [])
    group = grouping["groups"][0]
    hypothesis = next(
        h for h in group["hypotheses"] if h["members"]["parent"]["isotope_shift"] == 0
    )
    assert hypothesis["neutral_mass"] is None
    selection = {
        "ec_id": group["ec_id"],
        "hypothesis_id": hypothesis["hypothesis_id"],
        "review": "accepted",
        "relation_ids": [rows[0]["relation_id"]],
    }
    l1, l2, metadata = build_representations(
        data, grouping, [selection], relation_reviews={rows[0]["relation_id"]: "accepted"}
    )
    assert l1.n_vars == 1 and l2 is None
    assert metadata["unavailable_groups"]


def test_explicit_singletons_keep_unknown_mass_and_save_as_h5ad(tmp_path):
    from anndata import read_h5ad

    data, _rows, grouping = setup_group()
    _l1, l2, _metadata = build_representations(
        data, grouping, [], relation_reviews={}, include_singletons=True
    )
    assert l2.n_vars == 3 and l2.var["neutral_mass"].isna().all()
    path = tmp_path / "ungrouped.h5ad"
    l2.write_h5ad(path)
    loaded = read_h5ad(path)
    np.testing.assert_array_equal(loaded.X, data[:, loaded.var["quantifier_feature_id"].tolist()].X)
    assert set(loaded.var["entity_status"].astype(str)) == {"ungrouped"}
