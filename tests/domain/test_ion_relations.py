"""Chemical candidates are independent of identity annotations and grouping decisions."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.ion.relations import find_relations, measure_evidence
from scMM.ion.semantics import unknown_state, write_value_states
from scMM.ion.species import CARBON13_SHIFT, ION_SPECS, resolved_isotopes
from scMM.util.intensity import write_intensity_states


def dataset(masses):
    data = AnnData(
        np.tile(np.arange(1.0, len(masses) + 1), (25, 1)),
        obs=pd.DataFrame({"sample_id": ["a"] * 25}, index=[f"c{i}" for i in range(25)]),
        var=pd.DataFrame({"mz": masses}, index=[f"f{i}" for i in range(len(masses))]),
    )
    write_intensity_states(data, {"X": "raw"})
    write_value_states(data, {"X": {**unknown_state(), "space": "linear_abundance"}})
    return data


def test_species_roundtrip_charge_multimer_and_loss():
    for spec in ION_SPECS.values():
        assert spec.neutral_mass(spec.mz(500.0)) == pytest.approx(500.0)
    parent = ION_SPECS["[M+H]+"].mz(500.0)
    masses = [
        parent,
        parent + CARBON13_SHIFT,
        ION_SPECS["[M+Na]+"].mz(500.0),
        ION_SPECS["[M+2H]2+"].mz(500.0),
        ION_SPECS["[2M+H]+"].mz(500.0),
        ION_SPECS["[M+H-H2O]+"].mz(500.0),
    ]
    result = find_relations(
        dataset(masses), [s for s in ION_SPECS.values() if s.polarity == "pos"], polarity="pos"
    )
    assert {"isotope", "adduct", "charge", "multimer", "neutral_loss", "fragment_form"} <= {
        r["kind"] for r in result["relations"]
    }
    assert all(r["review"] == "pending" for r in result["relations"])


def test_negative_polarity_and_joint_error_intervals():
    h, na = ION_SPECS["[M+H]+"], ION_SPECS["[M+Na]+"]
    data = dataset([h.mz(500.0) * (1 + 4e-6), na.mz(500.0) * (1 - 4e-6)])
    rows = find_relations(data, [h, na], polarity="pos")["relations"]
    assert any(row["kind"] == "adduct" for row in rows)
    with pytest.raises(ValueError, match="incompatible"):
        find_relations(data, [ION_SPECS["[M-H]-"]], polarity="pos")
    negative = dataset([ION_SPECS["[M-H]-"].mz(500.0), ION_SPECS["[M-2H]2-"].mz(500.0)])
    assert any(
        r["kind"] == "charge"
        for r in find_relations(
            negative, [ION_SPECS["[M-H]-"], ION_SPECS["[M-2H]2-"]], polarity="neg"
        )["relations"]
    )


def test_zero_constant_and_unknown_evidence():
    data = dataset([500.0, 500.0 + CARBON13_SHIFT])
    rows = find_relations(data, [], polarity="pos")["relations"]
    data.X[0, 1] = 0
    evidence = measure_evidence(data, rows)
    assert evidence[0]["joint_pearson"] is None
    assert evidence[0]["valid_cells"] == 25
    assert evidence[0]["joint_cells"] == 24
    write_intensity_states(data, {"X": "normalized"})
    with pytest.raises(ValueError, match="unnormalized"):
        measure_evidence(data, rows)


def test_actual_ion_formula_and_double_charge_spacing():
    single = resolved_isotopes(
        "C20H40O2", ION_SPECS["[M+H]+"], parent_mz=314.0, resolution_200=70000.0
    )
    double = resolved_isotopes(
        "C20H40O2", ION_SPECS["[M+2H]2+"], parent_mz=157.0, resolution_200=70000.0
    )
    assert abs((single[0]["mz"] - 314.0) / 2 - (double[0]["mz"] - 157.0)) < 1e-5
    assert single[0]["ratio"] > 0


def test_formula_condition_and_ratio_support_remain_separate():
    from scMM.ion.relations import assess_isotope_ratios, formula_relations

    spec = ION_SPECS["[M+H]+"]
    peaks = resolved_isotopes("C20H40O2", spec, parent_mz=314.0, resolution_200=70000.0)
    data = dataset([314.0, peaks[0]["mz"]])
    data.X[:, 1] = data.X[:, 0] * peaks[0]["ratio"]
    rows = formula_relations(
        data,
        [{"feature_id": "f0", "species_id": spec.id, "formula": "C20H40O2"}],
        polarity="pos",
        resolution_200=70000.0,
    )
    evidence = assess_isotope_ratios(rows, measure_evidence(data, rows))
    assert evidence[0]["ratio_status"] == "pass"
    assert rows[0]["review"] == "pending"
    data.X[:, 1] *= 3
    assert assess_isotope_ratios(rows, measure_evidence(data, rows))[0]["ratio_status"] == "fail"


def test_same_scan_evidence_not_independent_peak_ratio():
    from scMM.ion.relations import same_scan_window_evidence

    result = same_scan_window_evidence(
        [1.0, 4.0], [2.0, 1.0], frame_ids=[0, 1], source_identity="scan-source"
    )
    assert result["observed_ratio"] == pytest.approx(3 / 5)
    assert result["observed_ratio"] != 2 / 4
