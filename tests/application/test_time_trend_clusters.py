"""Stored trend dependency, analytical distances, seeded algorithms and process cleanup."""

import os
import random
import subprocess

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.application import time_trend_clusters as workflow
from scMM.application.time_analysis import info, result_tables, time_figure, trend_clusters, trends
from scMM.util.time_results import invalidate_time_results, registry, require_run, write_registry


def example(count=16):
    return AnnData(
        np.random.default_rng(12).normal(size=(count, 6)),
        obs=pd.DataFrame({"time": np.linspace(0, 1, count)}, index=[f"c{i}" for i in range(count)]),
        var=pd.DataFrame(index=[f"f{i}" for i in range(6)]),
    )


def source(data=None):
    data = example(16) if data is None else data
    trends(
        data,
        key="trend_a",
        time_key="time",
        time_kind="normalized_time",
        unit="unitless",
        window_size=2,
        step_size=2,
    )
    return data


@pytest.mark.parametrize("method", ["agglomerative", "kmeans", "leiden", "louvain"])
def test_seeded_methods_repeat_labels_without_changing_parent_or_global_rng(
    method, tmp_path, monkeypatch
):
    if method in {"leiden", "louvain"}:
        pytest.importorskip("igraph")
    if method == "leiden":
        pytest.importorskip("leidenalg")
    data = source()
    before = data.X.copy()
    parent = result_tables(data, "trend_a")
    rng = random.getstate()
    for key in ["groups_a", "groups_b"]:
        trend_clusters(
            data, key=key, trend_key="trend_a", cluster_method=method, seed=123, n_clusters=2
        )
    np.testing.assert_equal(data.uns["groups_a"]["labels"], data.uns["groups_b"]["labels"])
    assert random.getstate() == rng
    np.testing.assert_equal(data.X, before)
    for name, frame in parent.items():
        pd.testing.assert_frame_equal(result_tables(data, "trend_a")[name], frame)
    parameters = require_run(data, "groups_a")["parameters"]
    assert parameters["seed"] == (None if method == "agglomerative" else 123)
    assert parameters["versions"]["numpy"]
    if method in {"leiden", "louvain"}:
        assert parameters["effective_parameters"]["n_neighbors"] == 5
        assert parameters["requested_parameters"]["n_neighbors"] == 10
        if method == "leiden":
            assert parameters["effective_parameters"]["n_iterations"] == 2
        else:
            assert parameters["effective_parameters"]["resolution"] == 1.0
    tables = result_tables(data, "groups_a")
    target = tmp_path / "groups.h5ad"
    data.write_h5ad(target)
    loaded = read_h5ad(target)
    assert all(row["valid"] for row in info(loaded))

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only results must not cluster")

    monkeypatch.setattr("scMM.plot._trend_clustering.trend_cluster", forbidden)
    for name, frame in tables.items():
        pd.testing.assert_frame_equal(result_tables(loaded, "groups_a")[name], frame)
    figure = time_figure(loaded, key="groups_a")
    assert figure.layout.meta["trend_cluster_parent"] == "trend_a"
    metadata = registry(loaded)
    metadata["runs"]["trend_a"]["identity"] = "f" * 32
    write_registry(loaded, metadata)
    with pytest.raises(ValueError, match="stale"):
        result_tables(loaded, "groups_a")
    invalidate_time_results(data, ["time"])
    assert all(not row["valid"] for row in info(data))


def test_cluster_standardization_distances_and_invalid_feature_are_analytical():
    t = np.arange(8.0)
    data = AnnData(
        np.column_stack([t, 7 - t, np.ones(8), np.full(8, np.nan)]),
        obs=pd.DataFrame({"time": t / 7}, index=[f"c{i}" for i in range(8)]),
        var=pd.DataFrame(index=["rise", "fall", "constant", "missing"]),
    )
    source(data)
    trend_clusters(
        data,
        key="groups_a",
        trend_key="trend_a",
        cluster_method="agglomerative",
        metric="euclidean",
        n_clusters=2,
    )
    result = data.uns["groups_a"]
    expected = np.array([-3.0, -1.0, 1.0, 3.0]) / np.sqrt(5)
    np.testing.assert_allclose(result["normalized"][:, 0], expected)
    np.testing.assert_allclose(result["normalized"][:, 1], -expected)
    np.testing.assert_equal(result["normalized"][:, 2], np.zeros(4))
    assert np.isnan(result["normalized"][:, 3]).all()
    np.testing.assert_allclose(result["distances"][0, :3], [0, 4, 2])
    assert np.isnan(result["distances"][3]).all()
    assert result["labels"][0] != result["labels"][1]
    assert result["labels"][3] == -1
    assert result_tables(data, "groups_a")["features"].measured_windows.tolist() == [4, 4, 4, 0]
    assert len(time_figure(data, key="groups_a").data) == 5


def test_graph_busy_and_real_timeout_leave_no_process_or_temporary_files(monkeypatch):
    workflow._CLUSTER_SLOT.acquire()
    try:
        with pytest.raises(ValueError, match="正在执行"):
            workflow._cluster_labels(np.ones((3, 2)), {})
    finally:
        workflow._CLUSTER_SLOT.release()
    if os.name != "posix":
        pytest.skip("waitpid reaping assertion is POSIX specific")
    launched = []
    original = subprocess.Popen

    def capture(args, **kwargs):
        process = original(args, **kwargs)
        launched.append((process.pid, args[3]))
        return process

    monkeypatch.setattr(subprocess, "Popen", capture)
    monkeypatch.setattr(workflow, "_CLUSTER_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(ValueError, match="子进程已停止并回收"):
        workflow._cluster_labels(
            np.ones((3, 2)), {"metric": "euclidean", "cluster_method": "louvain", "random_state": 3}
        )
    assert launched
    for pid, input_path in launched:
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        assert not os.path.exists(input_path)
    assert workflow._CLUSTER_SLOT.acquire(blocking=False)
    workflow._CLUSTER_SLOT.release()


def test_constant_distance_fallback_and_kmeans_cluster_shortfall_are_visible():
    data = example(8)
    data.X[:] = 1
    source(data)
    trend_clusters(data, key="groups_a", trend_key="trend_a", cluster_method="kmeans", n_clusters=2)
    parameters = require_run(data, "groups_a")["parameters"]
    assert parameters["undefined_distance_pairs"] == 15
    assert parameters["actual_clusters"] == 1
    assert parameters["warnings"]
    np.testing.assert_equal(data.uns["groups_a"]["distances"], np.zeros((6, 6)))


def test_worker_diagnostics_are_bound_to_the_own_result(monkeypatch):
    data = source()
    monkeypatch.setattr(
        workflow,
        "_cluster_labels",
        lambda *args, **kwargs: (np.arange(6) % 2, ["UserWarning: diagnostic warning"]),
    )
    trend_clusters(
        data, key="groups_a", trend_key="trend_a", cluster_method="agglomerative", n_clusters=2
    )
    assert require_run(data, "groups_a")["parameters"]["warnings"] == [
        "UserWarning: diagnostic warning"
    ]


def test_feature_cap_and_invalid_backend_labels_never_publish(monkeypatch):
    data = source()
    monkeypatch.setattr(workflow, "_cluster_labels", lambda *args, **kwargs: (np.full(6, -1), []))
    with pytest.raises(ValueError, match="无效标签"):
        trend_clusters(
            data, key="failed", trend_key="trend_a", cluster_method="agglomerative", n_clusters=2
        )
    assert "failed" not in data.uns
    assert len(info(data)) == 1
    large = AnnData(
        np.ones((8, 501)),
        obs=pd.DataFrame({"time": np.linspace(0, 1, 8)}, index=[f"c{i}" for i in range(8)]),
    )
    source(large)
    with pytest.raises(ValueError, match="500 个特征"):
        trend_clusters(large, key="too_large", trend_key="trend_a")
    assert "too_large" not in large.uns
