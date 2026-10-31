"""EC merge never infers identity or response comparability from equal masses."""

import json

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.ion_merge import merge_compound_sources
from scMM.ion.semantics import unknown_state, write_value_states


def source(key, species="[M+H]+"):
    data = AnnData(
        np.array([[0.0], [2.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame(
            {
                "neutral_mass": [500.0],
                "quantifier_feature_id": ["f"],
                "ion_role": [
                    json.dumps(
                        {"species_id": species, "charge": 1, "oligomer": 1, "isotope_shift": 0.0}
                    )
                ],
            },
            index=["ec"],
        ),
    )
    data.layers["scmm_quantifiable"] = np.ones(data.shape, dtype=bool)
    data.uns["scmm_variable_kind"] = "empirical_compound"
    write_value_states(
        data,
        {
            "X": {**unknown_state(), "space": "linear_abundance"},
            "scmm_quantifiable": unknown_state(),
        },
    )
    return {"source_id": key, "root_id": key, "view_id": key, "data": data}


def test_equal_masses_separate_until_explicit_comparable_alignment():
    a, b = source("a"), source("b")
    separate, _ = merge_compound_sources([a, b], [])
    assert separate.shape == (4, 2) and np.isnan(separate.X[0, 1])
    mappings = [
        {
            "source_id": key,
            "ec_id": "ec",
            "target_ec_id": "joined",
            "response_comparable": True,
            "reason": "same ion response assertion",
        }
        for key in ["a", "b"]
    ]
    joined, _ = merge_compound_sources([a, b], mappings)
    np.testing.assert_array_equal(joined.X[:, 0], [0.0, 2.0, 0.0, 2.0])
    with pytest.raises(ValueError, match="response systems"):
        merge_compound_sources([a, source("b", "[M+Na]+")], mappings)
