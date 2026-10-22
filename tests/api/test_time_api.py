"""Time-analysis HTTP lifecycle, atomic failure, identity and read-only export."""

import json
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.util.intensity import write_intensity_states
from tests.support.workflow import get

pytestmark = pytest.mark.filterwarnings(
    "ignore:Changing the sparsity structure of a csr_matrix is expensive:scipy.sparse.SparseEfficiencyWarning"
)


def import_time(workflow, count=40):
    _, _, _, _, output, _, _, _, post = workflow
    data = AnnData(
        np.random.default_rng(12).normal(size=(count, 6)),
        obs=pd.DataFrame(
            {
                "sample": ["a"] * (count // 2) + ["b"] * (count - count // 2),
                "group": ["a"] * (count // 2) + ["b"] * (count - count // 2),
                "time": np.linspace(0, 1, count),
                "batch": "b0",
            },
            index=[f"c{i}" for i in range(count)],
        ),
        var=pd.DataFrame({"mz": np.arange(150.0, 156.0)}, index=[f"f{i}" for i in range(6)]),
    )
    data.obsm["X_test"] = np.column_stack([np.arange(float(count)), np.arange(float(count)) ** 2])
    write_intensity_states(data, {"X": "raw"})
    data.write_h5ad(output / "time.h5ad")
    response = post("/dataset/import", {"root": "Output", "path": "time.h5ad"})
    assert response.status_code == 200, response.text
    return data


def palantir(workflow, key="pal_a", **extra):
    return workflow[-1](
        "/analysis/time",
        {
            "operation": "palantir",
            "options": {
                "key": key,
                "root_cell_id": "c3",
                "input_representation": "X",
                "terminal_cell_ids": ["c39"],
                "n_diff_components": 3,
                "knn": 10,
                "num_waypoints": 12,
                **extra,
            },
        },
    )


def path(workflow, key="path_a", **extra):
    return workflow[-1](
        "/analysis/time",
        {
            "operation": "trajectory",
            "options": {
                "key": key,
                "coordinate_key": "X_test",
                "time_key": "time",
                "time_kind": "normalized_time",
                "unit": "unitless",
                "window_size": 8,
                "step_size": 5,
                "min_cells_per_window": 3,
                **extra,
            },
        },
    )


def test_time_roundtrip_full_export_and_current_report_use_stored_values(workflow, monkeypatch):
    pytest.importorskip("palantir")
    original = import_time(workflow)
    _, _, _, _, _, _, _, current, post = workflow
    start = current()
    response = palantir(workflow)
    assert response.status_code == 200, response.text
    assert response.json()["value"]["parameters"]["root_cell_id"] == "c3"
    response = path(workflow)
    assert response.status_code == 200, response.text
    assert get(workflow, "/analysis/time").json()["total_cells"] == 40
    frame = pd.read_csv(
        BytesIO(get(workflow, "/results/download?kind=matrix").content),
        index_col=0,
        float_precision="round_trip",
    )
    assert frame.columns[0] == "Label"
    np.testing.assert_array_equal(frame.drop(columns="Label").to_numpy(), original.X)
    table = get(workflow, "/analysis/time/result?key=pal_a").json()
    assert table["tables"]["cells"]["rows"][0]["cell_id"] == "c0"
    assert table["parameters"]["actual_earliest_cell_id"] == "c3"
    figure = post(
        "/analysis/plot",
        {"kind": "time_plot", "options": {"key": "pal_a", "coordinate_key": "X_test"}},
    )
    assert figure.status_code == 200, figure.text
    payload = figure.json()["value"]
    response = get(workflow, "/analysis/time/download?key=pal_a")
    with ZipFile(BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"metadata.json", "cells.csv", "multiscale.csv"}
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["parameters"]["layer"] is None
        assert metadata["output_metadata"]["pal_a_branch_names"] == ["c39"]
        assert len(pd.read_csv(BytesIO(archive.read("cells.csv")))) == 40
    token = json.dumps(
        [current()["project"]["dataset"]["id"], current()["project"]["dataset"]["revision"]]
    )
    report = workflow[0].get(
        "/api/v1/workspace/results/download",
        headers=workflow[1],
        params={"kind": "report_zip", "key": token},
    )
    assert report.status_code == 200, report.text
    with ZipFile(BytesIO(report.content)) as archive:
        assert "results/time_pal_a_cells.csv" in archive.namelist()
        assert "results/time_path_a_windows.csv" in archive.namelist()
    saved_path = current()["project"]["path"]
    post("/project/save").raise_for_status()
    post("/project/close").raise_for_status()
    post("/project/open", {"path": saved_path}).raise_for_status()

    def forbidden(*args, **kwargs):
        raise AssertionError("reload must not rerun algorithms")

    import palantir as library

    monkeypatch.setattr(library.core, "run_palantir", forbidden)
    assert all(row["valid"] for row in get(workflow, "/analysis/time").json()["results"])
    reloaded = get(workflow, "/analysis/time/result?key=pal_a").json()
    assert reloaded == table
    saved_figure = get(workflow, "/analysis/figures/time_plot").json()
    assert (
        saved_figure["layout"]["meta"]["time_result_identity"]
        == payload["layout"]["meta"]["time_result_identity"]
    )
    assert get(workflow, "/results/download?kind=time_result&key=path_a").status_code == 200
    assert (
        current()["project"]["dataset"]["id"] != start["project"]["dataset"]["id"]
        or current()["project"]["dataset"]["revision"] > start["project"]["dataset"]["revision"]
    )


def test_time_failure_duplicate_keys_and_invalid_inputs_leave_state(workflow, monkeypatch):
    import_time(workflow)
    _, _, _, _, _, _, _, current, post = workflow
    path(workflow).raise_for_status()
    before = current()
    assert path(workflow).status_code == 400
    assert current() == before
    for values, status in (
        ({"window_size": True}, 422),
        ({"window_size": 0}, 422),
        ({"branch_probability_key": "missing"}, 400),
        ({"time_kind": "arbitrary"}, 422),
        ({"unit": ""}, 422),
    ):
        assert path(workflow, "bad", **values).status_code == status
        assert current() == before
    stale = post(
        "/analysis/time",
        {
            "revision": before["revision"] - 1,
            "operation": "trajectory",
            "options": {
                "key": "stale",
                "coordinate_key": "X_test",
                "time_key": "time",
                "time_kind": "normalized_time",
                "unit": "unitless",
            },
        },
    )
    assert stale.status_code == 409 and current() == before
    for values, status in (
        ({"root_cell_id": "missing"}, 400),
        ({"knn": 40}, 400),
        ({"n_diff_components": False}, 422),
        ({"num_waypoints": 500}, 400),
        ({"arbitrary_kwarg": 1}, 422),
    ):
        assert palantir(workflow, "bad", **values).status_code == status
        assert current() == before
    from scMM.application import time_analysis

    original = time_analysis.trajectory

    def fail(data, **options):
        original(data, **options)
        data.X[:] = -999
        raise ValueError("failure after numerical candidate")

    monkeypatch.setattr(time_analysis, "trajectory", fail)
    assert path(workflow, "candidate_failure").status_code == 400
    assert current() == before
    assert [row["key"] for row in get(workflow, "/analysis/time").json()["results"]] == ["path_a"]


def test_time_figure_coordinate_identity_and_transform_download_guard(workflow):
    import_time(workflow)
    _, headers, manager, _, _, _, _, _, post = workflow
    path(workflow).raise_for_status()
    figure = post("/analysis/plot", {"kind": "time_plot", "options": {"key": "path_a"}}).json()[
        "value"
    ]
    metadata = figure["layout"]["meta"]

    def check():
        return workflow[0].post(
            "/api/v1/workspace/figures/check", headers=headers, json={"metadata": metadata}
        )

    assert check().status_code == 204
    # Defense for out-of-band data writers: the token alone is insufficient.
    with manager.access(headers["X-SCMM-Workspace"]) as workspace:
        workspace.project.workspace.data.obsm["X_test"][0, 0] += 1
    assert get(workflow, "/analysis/time/download?key=path_a").status_code == 400
    assert check().status_code == 400
    post(
        "/analysis/operation", {"operation": "normalize", "options": {"method": "total"}}
    ).raise_for_status()
    assert get(workflow, "/analysis/time").json()["results"] == []
    assert get(workflow, "/results/download?kind=time_result&key=path_a").status_code == 400


def test_time_full_download_is_not_limited_to_display_rows(workflow):
    import_time(workflow, count=234)
    path(workflow, window_size=8, step_size=1).raise_for_status()
    tables = get(workflow, "/analysis/time/result?key=path_a").json()["tables"]
    assert tables["cells"]["total"] == 234 and len(tables["cells"]["rows"]) == 200
    assert tables["windows"]["total"] == 227 and len(tables["windows"]["rows"]) == 200
    with ZipFile(BytesIO(get(workflow, "/analysis/time/download?key=path_a").content)) as archive:
        cells = pd.read_csv(BytesIO(archive.read("cells.csv")))
        windows = pd.read_csv(BytesIO(archive.read("windows.csv")))
        assert len(cells) == 234 and cells.cell_id.iloc[-1] == "c233"
        assert len(windows) == 227 and windows.window_start.iloc[-1] == 226


def test_velocity_http_full_export_failure_atomicity_and_reload(workflow, monkeypatch):
    import_time(workflow, count=234)
    _, _, _, _, _, _, _, current, post = workflow
    options = dict(
        key="speed_a",
        time_key="time",
        time_kind="normalized_time",
        unit="unitless",
        window_size=8,
        step_size=1,
    )
    before = current()
    for changes, status in (
        ({"window_size": 1}, 422),
        ({"window_size": True}, 422),
        ({"unit": "s"}, 400),
        ({"time_key": "missing"}, 400),
        ({"layer": "missing"}, 400),
        ({"layer": ""}, 422),
        ({"seed": 42}, 422),
    ):
        response = post(
            "/analysis/time", {"operation": "velocity", "options": {**options, **changes}}
        )
        assert response.status_code == status, response.text
        assert current() == before
    post("/analysis/time", {"operation": "velocity", "options": options}).raise_for_status()
    table = get(workflow, "/analysis/time/result?key=speed_a").json()
    assert table["tables"]["features"]["total"] == 227 * 6
    assert len(table["tables"]["features"]["rows"]) == 200
    with ZipFile(BytesIO(get(workflow, "/analysis/time/download?key=speed_a").content)) as archive:
        assert len(pd.read_csv(BytesIO(archive.read("features.csv")))) == 227 * 6
        assert len(pd.read_csv(BytesIO(archive.read("cells.csv")))) == 234
    post("/analysis/plot", {"kind": "time_plot", "options": {"key": "speed_a"}}).raise_for_status()
    saved_path = current()["project"]["path"]
    post("/project/save").raise_for_status()
    post("/project/close").raise_for_status()
    post("/project/open", {"path": saved_path}).raise_for_status()

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only reload must not calculate")

    monkeypatch.setattr("scMM.plot._trajectory.metabolic_velocity_field", forbidden)
    assert get(workflow, "/analysis/time/result?key=speed_a").json() == table
    assert get(workflow, "/analysis/figures/time_plot").status_code == 200
    before = current()
    assert post("/analysis/time", {"operation": "velocity", "options": options}).status_code == 400
    assert current() == before
    monkeypatch.undo()
    from scMM.application import time_analysis

    original = time_analysis.velocity

    def fail(data, **options):
        original(data, **options)
        data.X[:] = -999
        raise ValueError("candidate failed")

    monkeypatch.setattr(time_analysis, "velocity", fail)
    assert (
        post(
            "/analysis/time", {"operation": "velocity", "options": {**options, "key": "failed"}}
        ).status_code
        == 400
    )
    assert current() == before


def test_trends_full_export_readonly_reload_and_candidate_failure(workflow, monkeypatch):
    import_time(workflow, count=234)
    _, _, _, _, _, _, _, current, post = workflow
    options = dict(
        key="trend_a",
        time_key="time",
        time_kind="normalized_time",
        unit="unitless",
        features=["f5", "f2", "f0"],
        feature_name_key="mz",
        window_size=8,
        step_size=1,
    )
    before = current()
    for change, status in (
        ({"kernel_stat": "max"}, 422),
        ({"window_size": True}, 422),
        ({"features": ["absent"]}, 400),
        ({"features": ["f0", "f0"]}, 400),
        ({"feature_name_key": "missing"}, 400),
        ({"unit": "h"}, 400),
    ):
        response = post("/analysis/time", {"operation": "trends", "options": {**options, **change}})
        assert response.status_code == status, response.text
        assert current() == before
    post("/analysis/time", {"operation": "trends", "options": options}).raise_for_status()
    table = get(workflow, "/analysis/time/result?key=trend_a").json()
    assert table["tables"]["trends"]["total"] == 227 * 3
    assert len(table["tables"]["trends"]["rows"]) == 200
    assert table["tables"]["statistics"]["rows"][0]["feature_id"] == "f5"
    with ZipFile(BytesIO(get(workflow, "/analysis/time/download?key=trend_a").content)) as archive:
        assert set(archive.namelist()) == {
            "metadata.json",
            "windows.csv",
            "statistics.csv",
            "trends.csv",
            "cells.csv",
        }
        assert len(pd.read_csv(BytesIO(archive.read("trends.csv")))) == 227 * 3
        assert len(pd.read_csv(BytesIO(archive.read("cells.csv")))) == 234
    figure = post(
        "/analysis/plot",
        {
            "kind": "time_plot",
            "options": {"key": "trend_a", "plot_top_n": 2, "display_standardize": False},
        },
    )
    assert figure.status_code == 200, figure.text
    assert figure.json()["value"]["layout"]["meta"]["trend_display_standardize"] is False
    path = current()["project"]["path"]
    post("/project/save").raise_for_status()
    post("/project/close").raise_for_status()
    post("/project/open", {"path": path}).raise_for_status()

    def forbidden(*args, **kwargs):
        raise AssertionError("must not rerun trend statistics")

    monkeypatch.setattr("scMM.plot._trajectory.metabolite_trends", forbidden)
    assert get(workflow, "/analysis/time/result?key=trend_a").json() == table
    assert get(workflow, "/analysis/figures/time_plot").status_code == 200
    monkeypatch.undo()
    from scMM.application import time_analysis

    original = time_analysis.trends

    def fail(data, **options):
        original(data, **options)
        data.X[:] = -999
        raise ValueError("candidate failure")

    monkeypatch.setattr(time_analysis, "trends", fail)
    before = current()
    assert (
        post(
            "/analysis/time", {"operation": "trends", "options": {**options, "key": "failed"}}
        ).status_code
        == 400
    )
    assert current() == before


def test_trend_cluster_http_dependency_full_export_roundtrip_and_failure_atomicity(
    workflow, monkeypatch
):
    import_time(workflow, count=234)
    _, _, _, _, _, _, _, current, post = workflow
    post(
        "/analysis/time",
        {
            "operation": "trends",
            "options": dict(
                key="trend_a",
                time_key="time",
                time_kind="normalized_time",
                unit="unitless",
                window_size=8,
                step_size=1,
            ),
        },
    ).raise_for_status()
    options = dict(
        key="groups_a",
        trend_key="trend_a",
        cluster_method="agglomerative",
        metric="euclidean",
        n_clusters=2,
        top_k=3,
    )
    before = current()
    for change, status in (
        ({"trend_key": "missing"}, 400),
        ({"seed": True}, 422),
        ({"n_clusters": 8}, 400),
        ({"metric": "correlation", "linkage": "ward"}, 400),
        ({"top_k": 501}, 422),
        ({"arbitrary_kwargs": {}}, 422),
    ):
        response = post(
            "/analysis/time", {"operation": "trend_clusters", "options": {**options, **change}}
        )
        assert response.status_code == status, response.text
        assert current() == before
    response = post("/analysis/time", {"operation": "trend_clusters", "options": options})
    assert response.status_code == 200, response.text
    table = get(workflow, "/analysis/time/result?key=groups_a").json()
    assert table["parameters"]["trend_key"] == "trend_a"
    assert table["parameters"]["seed"] is None
    assert table["tables"]["features"]["total"] == 3
    assert table["tables"]["curves"]["total"] == 681
    assert len(table["tables"]["curves"]["rows"]) == 200
    with ZipFile(BytesIO(get(workflow, "/analysis/time/download?key=groups_a").content)) as archive:
        assert set(archive.namelist()) == {
            "metadata.json",
            "features.csv",
            "curves.csv",
            "distances.csv",
            "windows.csv",
        }
        assert len(pd.read_csv(BytesIO(archive.read("curves.csv")))) == 681
        assert len(pd.read_csv(BytesIO(archive.read("distances.csv")))) == 9
    post("/analysis/plot", {"kind": "time_plot", "options": {"key": "groups_a"}}).raise_for_status()
    saved = current()["project"]["path"]
    post("/project/save").raise_for_status()
    post("/project/close").raise_for_status()
    post("/project/open", {"path": saved}).raise_for_status()

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only reload must not cluster")

    monkeypatch.setattr("scMM.plot._trend_clustering.trend_cluster", forbidden)
    assert get(workflow, "/analysis/time/result?key=groups_a").json() == table
    assert get(workflow, "/analysis/figures/time_plot").status_code == 200
    monkeypatch.undo()
    before = current()
    assert (
        post("/analysis/time", {"operation": "trend_clusters", "options": options}).status_code
        == 400
    )
    assert current() == before
    from scMM.application import time_analysis

    original = time_analysis.trend_clusters

    def fail(data, **settings):
        original(data, **settings)
        data.X[:] = -999
        raise ValueError("candidate after-fit failure")

    monkeypatch.setattr(time_analysis, "trend_clusters", fail)
    assert (
        post(
            "/analysis/time",
            {"operation": "trend_clusters", "options": {**options, "key": "failed"}},
        ).status_code
        == 400
    )
    assert current() == before
    monkeypatch.undo()
    post(
        "/analysis/operation", {"operation": "normalize", "options": {"method": "total"}}
    ).raise_for_status()
    assert get(workflow, "/analysis/time/download?key=groups_a").status_code == 400
