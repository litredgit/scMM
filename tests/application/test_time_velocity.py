"""Existing numerical definitions, named provenance, dependencies and H5AD recovery."""

import json

import numpy as np
import pandas as pd
import pytest
from anndata import read_h5ad

from scMM.application.time_analysis import (
    info,
    result_metadata,
    result_tables,
    time_figure,
)
from scMM.util.time_results import (
    invalidate_time_results,
    valid_time_figure,
)
from tests.support.time_analysis import example

# Palantir changes the sparsity of its transition matrix while adding absorbing
# states. This is a known performance warning, not a numerical warning to hide.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Changing the sparsity structure of a csr_matrix is expensive:scipy.sparse.SparseEfficiencyWarning"
)


def test_velocity_exact_slopes_direction_layer_and_readonly_roundtrip(tmp_path):
    from scMM.application.time_analysis import velocity

    data = example(12)
    time = np.arange(12.0)[::-1]
    data.obs["time"] = time
    data.X[:] = 99
    slopes = np.array([3.0, -4.0, 0.0, 1.0, 2.0, -2.0])
    data.layers["signal"] = time[:, None] * slopes + 7
    original = data.X.copy()
    velocity(
        data,
        key="speed_a",
        time_key="time",
        time_kind="acquisition_seconds",
        unit="s",
        layer="signal",
        window_size=4,
        step_size=2,
    )
    tables = result_tables(data, "speed_a")
    np.testing.assert_allclose(
        tables["features"].velocity.to_numpy().reshape(-1, 6), np.tile(slopes, (5, 1))
    )
    np.testing.assert_allclose(tables["windows"].speed, np.linalg.norm(slopes))
    np.testing.assert_array_equal(data.X, original)
    assert tables["cells"].sorted_position.tolist() == list(range(11, -1, -1))
    figure = time_figure(data, key="speed_a")
    assert valid_time_figure(data, figure.layout.meta)
    target = tmp_path / "velocity.h5ad"
    data.write_h5ad(target)
    recovered = read_h5ad(target)
    for name, table in tables.items():
        pd.testing.assert_frame_equal(result_tables(recovered, "speed_a")[name], table)
    recovered.obs["time"] = recovered.obs.time[::-1].to_numpy()
    assert not info(recovered)[0]["valid"]
    with pytest.raises(ValueError, match="stale"):
        result_tables(recovered, "speed_a")
    data.var_names = [f"changed{i}" for i in range(6)]
    assert not info(data)[0]["valid"]


def test_velocity_equal_time_windows_remain_undefined_and_metadata_expires():
    from scMM.application.time_analysis import velocity

    data = example(8)
    data.obs["time"] = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    velocity(
        data,
        key="speed_a",
        time_key="time",
        time_kind="normalized_time",
        unit="unitless",
        window_size=4,
        step_size=4,
    )
    tables = result_tables(data, "speed_a")
    assert tables["windows"].speed.isna().all()
    assert tables["features"].velocity.isna().all()
    assert tables["windows"].valid_cells.tolist() == [0, 0]
    assert json.dumps(result_metadata(data, "speed_a"), allow_nan=False)
    invalidate_time_results(data, ["group"])
    assert info(data)[0]["valid"]
    invalidate_time_results(data, ["time"])
    assert not info(data)[0]["valid"]


@pytest.mark.parametrize("invalid", [np.nan, np.inf, 1e308])
def test_velocity_invalid_or_overflowing_signal_does_not_publish(invalid):
    from scMM.application.time_analysis import velocity

    data = example(8)
    data.X[:] = invalid
    before = data.copy()
    with pytest.raises(ValueError):
        velocity(
            data,
            key="failed",
            time_key="time",
            time_kind="normalized_time",
            unit="unitless",
            window_size=4,
            step_size=2,
        )
    np.testing.assert_equal(data.X, before.X)
    assert "failed" not in data.uns
    assert not info(data)
