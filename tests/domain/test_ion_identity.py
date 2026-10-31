"""Root isolation and canonical identities are scientific input boundaries."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from scipy import sparse

from scMM.ion.contracts import MeasurementRoot, validate_schema
from scMM.ion.identity import axis_identity, dataset_identity, json_identity, matrix_identity


def example():
    return AnnData(
        np.array([[1.0, 0.0], [2.0, 3.0]]),
        obs=pd.DataFrame(index=["c1", "c2"]),
        var=pd.DataFrame({"mz": [100.0, 100.0]}, index=["f1", "f2"]),
    )


def test_numeric_layout_and_missingness():
    values = np.array([[0.0, 1.0], [2.0, 0.0]])
    assert matrix_identity(values) == matrix_identity(sparse.csc_matrix(values))
    assert matrix_identity(values) == matrix_identity(values.astype(">f8"))
    values[0, 0] = np.nan
    with pytest.raises(ValueError):
        matrix_identity(values)
    assert matrix_identity(values, allow_missing=True) == matrix_identity(
        values.copy(), allow_missing=True
    )
    values[0, 0] = np.inf
    with pytest.raises(ValueError):
        matrix_identity(values, allow_missing=True)


def test_axes_and_strict_parameters():
    with pytest.raises(ValueError):
        axis_identity(["x", "x"])
    assert axis_identity(["x", "y"]) != axis_identity(["y", "x"])
    with pytest.raises(ValueError):
        json_identity({"ppm": np.nan})
    with pytest.raises(ValueError):
        validate_schema({"schema_version": True})


def test_root_copies_and_duplicate_masses_keep_distinct_ids():
    original = example()
    root = MeasurementRoot.create(
        original,
        root_id="root",
        source={"kind": "test"},
        origin_kind="imported_feature",
        value_semantics="unknown",
    )
    original.X[:] = 99
    returned = root.data
    returned.X[:] = 5
    returned.var["mz"] = 9
    assert root.data.X[0, 0] == 1
    assert root.data.var_names.tolist() == ["f1", "f2"]
    assert root.value_semantics == "unknown"
    assert dataset_identity(root.data) == root.identity
    changed = root.data
    changed.layers["measurement"] = changed.X.copy()
    assert dataset_identity(changed) != root.identity


def test_metadata_mass_precision_is_not_display_rounded():
    data = example()
    changed = data.copy()
    changed.var.iloc[0, 0] = np.nextafter(100.0, np.inf)
    assert dataset_identity(data) != dataset_identity(changed)


def test_integer_measurements_do_not_lose_precision_in_identity():
    a = np.array([[2**53]], dtype=np.int64)
    b = np.array([[2**53 + 1]], dtype=np.int64)
    assert matrix_identity(a) != matrix_identity(b)


def test_equal_measurements_in_distinct_roots_have_distinct_entity_namespaces():
    data = example()
    a = MeasurementRoot.create(
        data, root_id="a", source={}, origin_kind="extraction", value_semantics="linear_abundance"
    )
    b = MeasurementRoot.create(
        data, root_id="b", source={}, origin_kind="extraction", value_semantics="linear_abundance"
    )
    assert a.identity != b.identity
    assert "scmm_measurement_root_id" not in data.uns
