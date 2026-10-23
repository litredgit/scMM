"""Existing numerical definitions, named provenance, dependencies and H5AD recovery."""

import json

import numpy as np
import pandas as pd
import pytest
from anndata import read_h5ad

from scMM.application.time_analysis import (
    info,
    palantir,
    result_metadata,
    result_tables,
    time_figure,
)
from scMM.application.workbench import AnalysisWorkspace
from scMM.util.intensity import intensity_states
from scMM.util.lifecycle import invalidate_observation_embeddings
from scMM.util.time_results import (
    TIME_RESULTS,
    invalidate_time_results,
    registry,
    require_run,
    valid_time_figure,
)
from tests.support.time_analysis import example, path

# Palantir changes the sparsity of its transition matrix while adding absorbing
# states. This is a known performance warning, not a numerical warning to hide.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Changing the sparsity structure of a csr_matrix is expensive:scipy.sparse.SparseEfficiencyWarning"
)


@pytest.fixture(scope="module")
def palantir_data():
    pytest.importorskip("palantir")
    data = example()
    palantir(
        data,
        key="pal_a",
        root_cell_id="c3",
        input_representation="X",
        terminal_cell_ids=["c39"],
        n_diff_components=3,
        knn=10,
        num_waypoints=12,
    )
    return data


def test_window_centers_counts_tail_and_missing_windows_preserve_inputs():
    data = example(8)
    before = data.copy()
    path(data)
    windows = result_tables(data, "path_a")["windows"]
    assert windows["window_start"].tolist() == [0, 3, 4]
    np.testing.assert_allclose(windows[["coordinate_0", "coordinate_1"]].iloc[0], [1.5, 3.5])
    assert windows["valid_cells"].tolist() == [4, 4, 4]
    np.testing.assert_array_equal(data.X, before.X)
    pd.testing.assert_frame_equal(data.obs, before.obs)
    np.testing.assert_array_equal(data.obsm["X_test"], before.obsm["X_test"])
    path(data, "too_few", min_cells_per_window=5)
    empty = result_tables(data, "too_few")["windows"]
    assert len(empty) == 3 and empty["coordinate_0"].isna().all() and (empty.valid_cells == 0).all()
    assert "0/3" in time_figure(data, key="too_few").layout.meta["notes"][0]


def test_probabilities_are_explicit_weighted_not_silently_fallback_or_normalized():
    data = example(8)
    weights = np.linspace(0.1, 0.9, 8)
    data.obsm["weights"] = np.column_stack([weights, 1 - weights])
    path(data, branch_probability_key="weights")
    windows = result_tables(data, "path_a")["windows"]
    expected = np.average(np.arange(4.0), weights=weights[:4])
    assert windows.iloc[0]["coordinate_0"] == pytest.approx(expected)
    assert windows.iloc[3]["coordinate_0"] != pytest.approx(expected)
    assert result_tables(data, "path_a")["cells"].shape[1] == 7
    with pytest.raises(KeyError):
        path(data, "missing", branch_probability_key="absent")
    data.obsm["bad"] = np.ones((8, 2))
    with pytest.raises(ValueError, match="概率"):
        path(data, "bad_weights", branch_probability_key="bad")
    assert "bad_weights" not in registry(data)["runs"]


def test_named_keys_remain_reserved_and_input_tampering_refuses_download():
    data = example()
    path(data)
    original = data.uns[TIME_RESULTS]
    with pytest.raises(ValueError, match="输出键"):
        path(data)
    assert data.uns[TIME_RESULTS] == original
    figure = time_figure(data, key="path_a")
    assert valid_time_figure(data, figure.layout.meta)
    data.obsm["X_test"][0, 0] += 1
    with pytest.raises(ValueError, match="stale"):
        require_run(data, "path_a")
    assert not valid_time_figure(data, figure.layout.meta)
    invalidate_time_results(data)
    assert "path_a" not in data.uns
    with pytest.raises(ValueError, match="输出键"):
        path(data)


def test_palantir_stable_nonzero_root_and_provenance(palantir_data):
    data = palantir_data
    parameters = require_run(data, "pal_a")["parameters"]
    assert parameters["root_cell_id"] == "c3" and parameters["actual_earliest_cell_id"] == "c3"
    assert data.obs["pal_a_pseudotime"].idxmin() == "c3"
    assert data.obs["pal_a_pseudotime"].iloc[0] > 0
    assert (
        parameters["n_jobs"] == 1
        and parameters["seed"] == 42
        and parameters["connected_components"] == 1
    )
    assert parameters["palantir_version"]
    np.testing.assert_array_equal(data.X, example().X)
    assert intensity_states(data)["X"] == "raw"
    assert result_tables(data, "pal_a")["cells"].cell_id.tolist() == data.obs_names.tolist()
    values = np.full((40, 1), 1 + 2e-13)
    original = values.copy()
    from scMM.application.time_analysis import _probabilities

    _probabilities(values, 40)
    np.testing.assert_array_equal(values, original)  # Validate without clipping/normalizing.


def test_plot_coordinates_expire_figure_without_expiring_palantir(palantir_data):
    data = palantir_data.copy()
    figure = time_figure(data, key="pal_a", coordinate_key="X_test")
    assert valid_time_figure(data, figure.layout.meta)
    data.obsm["X_test"][0, 0] += 1
    assert require_run(data, "pal_a")
    assert not valid_time_figure(data, figure.layout.meta)


def test_corrupt_time_registry_has_explicit_error():
    data = example()
    path(data)
    value = registry(data)
    value["runs"]["path_a"]["parameters"] = "not parameters"
    data.uns[TIME_RESULTS] = json.dumps(value)
    with pytest.raises(ValueError, match="metadata"):
        info(data)


def test_h5ad_roundtrip_reloads_read_only_values_without_recalculation(
    tmp_path, palantir_data, monkeypatch
):
    import palantir as library

    data = palantir_data.copy()
    path(
        data,
        "pal_path",
        coordinate_key="pal_a_ms_data",
        time_key="pal_a_pseudotime",
        time_kind="pseudotime",
        branch_probability_key="pal_a_branch_probs",
    )
    target = tmp_path / "time.h5ad"
    data.write_h5ad(target)
    loaded = read_h5ad(target)
    assert all(row["valid"] for row in info(loaded))
    assert require_run(loaded, "pal_a")["parameters"]["layer"] is None

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only reload must not recalculate")

    monkeypatch.setattr(library.core, "run_palantir", forbidden)
    for key in ("pal_a", "pal_path"):
        before, after = result_tables(data, key), result_tables(loaded, key)
        for name in before:
            pd.testing.assert_frame_equal(before[name], after[name])
        result_metadata(loaded, key)
    assert len(time_figure(loaded, key="pal_path").data) == 1
    assert valid_time_figure(
        loaded, time_figure(loaded, key="pal_a", coordinate_key="X_test").layout.meta
    )


def test_metadata_invalidates_only_affected_run_and_its_descendants(palantir_data):
    data = palantir_data.copy()
    path(data, "real_path")
    path(
        data,
        "pal_path",
        coordinate_key="pal_a_ms_data",
        time_key="pal_a_pseudotime",
        time_kind="pseudotime",
    )
    data.obs["batch"] = "edited"
    invalidate_time_results(data, {"batch"})
    assert all(row["valid"] for row in info(data))
    data.obs["time"] = data.obs["time"] * 0.5
    invalidate_time_results(data, {"time"})
    states = {row["key"]: row["valid"] for row in info(data)}
    assert states == {"pal_a": True, "real_path": False, "pal_path": True}
    data.X[0, 0] += 1
    removed = invalidate_time_results(data)
    assert "pal_a_pseudotime" in removed and not any(row["valid"] for row in info(data))


def test_declared_latent_and_embedding_parent_dependencies_propagate():
    data = example()
    data.obsm["X_latent"] = data.obsm["X_test"].copy()
    data.obsm["X_chain"] = data.obsm["X_test"].copy()
    data.uns["X_chain_params"] = {"source": "obsm:X_latent"}
    data.uns["scmm_workbench"] = {"latent_dependencies_json": json.dumps({"X_latent": ["group"]})}
    path(data, "plain")
    path(data, "dependent", coordinate_key="X_chain")
    data.obs["group"] = "changed"
    invalidate_observation_embeddings(data, {"group"})
    assert require_run(data, "plain")
    with pytest.raises(ValueError):
        require_run(data, "dependent")
    assert "X_latent" not in data.obsm and "dependent" not in data.uns


def test_transform_clears_time_artifacts_and_preserves_intensity_origin(palantir_data):
    data = palantir_data.copy()
    path(data)
    state = AnalysisWorkspace()
    state.replace(data)
    state.normalize("total")
    assert TIME_RESULTS not in state.data.uns
    assert not any(key.startswith(("pal_a", "path_a")) for key in state.data.obs)
    assert not any(key.startswith(("pal_a", "path_a")) for key in state.data.uns)
    assert intensity_states(state.data)["X"] == "normalized"


def test_disconnected_diffusion_kernel_rejected_without_changing_source():
    pytest.importorskip("palantir")
    data = example()
    data.X[:20] *= 0.001
    data.X[20:] = 100 + data.X[20:] * 0.001
    before = data.copy()
    with pytest.raises(ValueError, match="disconnected"):
        palantir(
            data,
            key="broken",
            root_cell_id="c3",
            input_representation="X",
            n_diff_components=3,
            knn=5,
            num_waypoints=12,
        )
    np.testing.assert_array_equal(data.X, before.X)
    assert TIME_RESULTS not in data.uns and "broken_pseudotime" not in data.obs


def test_resource_gate_rejects_before_allocating_window_buffers(monkeypatch):
    from scMM.plot import _trajectory as domain

    data = example(100)
    data.obsm["wide"] = np.zeros((100, 1000))
    data.obsm["branches"] = np.full((100, 100), 0.01)

    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before numerical allocation")

    monkeypatch.setattr(domain, "resample_trajectory", forbidden)
    with pytest.raises(ValueError, match="预计窗口结果"):
        path(
            data,
            coordinate_key="wide",
            branch_probability_key="branches",
            window_size=2,
            step_size=1,
        )


def test_connected_kernel_cannot_hide_disconnected_shortest_path_graph(monkeypatch):
    library = pytest.importorskip("palantir")
    from scipy.sparse import csr_matrix

    from scMM.plot import _trajectory as domain

    data = example()
    monkeypatch.setattr(
        library.utils,
        "run_diffusion_maps",
        lambda *a, **k: {"kernel": csr_matrix(np.ones((40, 40))), "EigenVectors": np.ones((40, 4))},
    )
    coordinates = pd.DataFrame(
        np.vstack([np.zeros((20, 3)), np.ones((20, 3))]), index=data.obs_names
    )
    monkeypatch.setattr(library.utils, "determine_multiscale_space", lambda *a, **k: coordinates)

    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before Palantir inserts connecting edges")

    monkeypatch.setattr(library.core, "run_palantir", forbidden)
    with pytest.raises(ValueError, match="multiscale neighbor graph is disconnected"):
        domain.run_palantir(data, start_idx=3, knn=5, check_connected=True, n_jobs=1)
