"""Existing numerical definitions, named provenance, dependencies and H5AD recovery."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.application.time_analysis import (
    info,
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


def test_trends_exact_selection_missing_names_display_and_h5ad_roundtrip(tmp_path):
    from scMM.application.time_analysis import trends

    data = example(8)
    t = np.arange(8.0)[::-1]
    data.obs["time"] = t
    data.X = np.column_stack([2 * t + 1, 20 - t, np.ones(8), np.full(8, np.nan), t, t])
    data.var["title"] = pd.Categorical(["duplicate", "duplicate", None, "missing", "x", "y"])
    before = data.X.copy()
    trends(
        data,
        key="trend_a",
        time_key="time",
        time_kind="experimental_time",
        unit="h",
        features=["f1", "f0", "f2", "f3"],
        feature_name_key="title",
        window_size=2,
        step_size=2,
        kernel_stat="mean",
    )
    table = result_tables(data, "trend_a")
    values = data.uns["trend_a"]
    np.testing.assert_allclose(
        values["pooled"][:, :3],
        [[19.5, 2.0, 1.0], [17.5, 6.0, 1.0], [15.5, 10.0, 1.0], [13.5, 14.0, 1.0]],
    )
    assert np.isnan(values["pooled"][:, 3]).all()
    np.testing.assert_equal(values["finite_counts"], np.tile([2, 2, 2, 0], (4, 1)))
    np.testing.assert_allclose(table["statistics"].rho[:2], [-1, 1])
    assert table["statistics"].feature_name.tolist() == ["duplicate", "duplicate", "f2", "missing"]
    assert np.isnan(table["statistics"].rho[2:]).all()
    np.testing.assert_equal(data.X, before)
    fig = time_figure(data, key="trend_a", plot_top_n=4)
    assert fig.layout.meta["trend_display_standardize"]
    assert valid_time_figure(data, fig.layout.meta)
    displayed = fig.layout.meta["trend_display_feature_ids"]
    assert list(fig.data[0].y) == displayed
    constant = displayed.index("f2")
    np.testing.assert_equal(np.asarray(fig.data[0].z)[constant], np.zeros(4))
    raw = time_figure(data, key="trend_a", plot_top_n=4, display_standardize=False)
    assert not raw.layout.meta["trend_display_standardize"]
    np.testing.assert_equal(np.asarray(raw.data[0].z), values["pooled"][:, values["rank_idx"]].T)
    np.testing.assert_equal(
        values["pooled"][:, :3], [[19.5, 2, 1], [17.5, 6, 1], [15.5, 10, 1], [13.5, 14, 1]]
    )
    target = tmp_path / "trends.h5ad"
    data.write_h5ad(target)
    loaded = read_h5ad(target)
    assert info(loaded)[0]["valid"]
    for name, frame in table.items():
        pd.testing.assert_frame_equal(result_tables(loaded, "trend_a")[name], frame)
    loaded.var["unrelated"] = "changed"
    assert info(loaded)[0]["valid"]
    loaded.var["title"] = loaded.var.title.astype(object)
    loaded.var.loc["f0", "title"] = "changed"
    assert not info(loaded)[0]["valid"]
    invalidate_time_results(data, ["group"])
    assert info(data)[0]["valid"]
    invalidate_time_results(data, ["time"])
    assert not info(data)[0]["valid"]
    with pytest.raises(ValueError, match="stale"):
        result_tables(data, "trend_a")


@pytest.mark.parametrize(
    "changes",
    [
        dict(features=["absent"]),
        dict(features=["f0", "f0"]),
        dict(feature_name_key="missing"),
        dict(kernel_stat="max"),
    ],
)
def test_trends_invalid_selection_and_statistics_do_not_publish(changes):
    from scMM.application.time_analysis import trends

    data = example()
    with pytest.raises((KeyError, ValueError)):
        trends(
            data,
            key="invalid",
            time_key="time",
            time_kind="normalized_time",
            unit="unitless",
            **changes,
        )
    assert not info(data)
    assert "invalid" not in data.uns


@pytest.mark.parametrize("invalid", [np.inf, -np.inf, 1e308])
def test_trends_infinite_or_overflowing_signal_preserves_original(invalid):
    from scMM.application.time_analysis import trends

    data = example(8)
    data.X[:] = invalid
    before = data.X.copy()
    with pytest.raises(ValueError):
        trends(
            data,
            key="invalid",
            time_key="time",
            time_kind="normalized_time",
            unit="unitless",
            kernel_stat="mean",
            window_size=4,
            step_size=2,
        )
    np.testing.assert_equal(data.X, before)
    assert not info(data)
    assert "invalid" not in data.uns


def test_trends_result_budget_rejects_before_allocating_window_output(monkeypatch):
    from scMM.application.time_analysis import trends

    data = AnnData(
        np.zeros((1000, 3000)),
        obs=pd.DataFrame({"time": np.linspace(0, 1, 1000)}, index=[f"c{i}" for i in range(1000)]),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("oversize output must be rejected before numerical allocation")

    monkeypatch.setattr("scMM.plot._trajectory.metabolite_trends", forbidden)
    with pytest.raises(ValueError, match="500 万"):
        trends(
            data,
            key="oversize",
            time_key="time",
            time_kind="normalized_time",
            unit="unitless",
            window_size=1,
            step_size=1,
        )
    assert not info(data)
    assert "oversize" not in data.uns
