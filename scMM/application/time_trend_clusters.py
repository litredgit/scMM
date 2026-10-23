"""Traceable clustering of an existing named trend result, without recomputing it."""
# ruff: noqa: RUF001

import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

import numpy as np
import pandas as pd

from scMM.util.time_results import binding, registry, require_run

from .time_inputs import _new_key, _publish, check_size

_CLUSTER_SLOT = BoundedSemaphore(1)
_CLUSTER_TIMEOUT_SECONDS = 90


def _cluster_labels(values, options):
    if not _CLUSTER_SLOT.acquire(blocking=False):
        raise ValueError("已有趋势聚类正在执行，请完成后再提交；未排队或应用本次候选")
    try:
        with TemporaryDirectory(prefix="scmm-trend-clusters-") as directory:
            root = Path(directory)
            np.save(root / "input.npy", values, allow_pickle=False)
            (root / "options.json").write_text(json.dumps(options), encoding="utf-8")
            env = {
                **os.environ,
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
            }
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "scMM.plot._trend_worker",
                        str(root / "input.npy"),
                        str(root / "labels.npy"),
                        str(root / "options.json"),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=_CLUSTER_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError(
                    "趋势聚类超过 90 秒工程限时，子进程已停止并回收；未应用候选"
                ) from error
            if result.returncode:
                raise ValueError("趋势聚类子进程失败：" + result.stderr[-2000:])
            return (
                np.load(root / "labels.npy", allow_pickle=False),
                json.loads((root / "labels.json").read_text(encoding="utf-8")),
            )
    finally:
        _CLUSTER_SLOT.release()


def trend_clusters(
    data,
    *,
    key,
    trend_key,
    metric="correlation",
    cluster_method="leiden",
    top_k=None,
    seed=0,
    n_clusters=5,
    n_neighbors=10,
    resolution=1.0,
    linkage="average",
):
    from scMM.plot._engine_trajectory import _select_and_standardize_trends
    from scMM.plot._trend_clustering import (
        SUPPORTED_METHODS,
        SUPPORTED_METRICS,
        _pairwise_distances,
        trend_cluster,
    )

    check_size(data)
    _new_key(data, key, [key, f"{key}_params"])
    parent = require_run(data, trend_key)
    if parent["kind"] != "trends":
        raise ValueError("须明确选择有效的代谢物窗口趋势结果，不接受速度或旧 Notebook 未绑定结果")
    if metric not in SUPPORTED_METRICS or cluster_method not in SUPPORTED_METHODS:
        raise ValueError("不支持的趋势距离或聚类方法")
    source = data.uns[trend_key]
    indices = (
        np.asarray(source["rank_idx"], dtype=int)[:top_k]
        if top_k is not None
        else np.arange(len(source["rank_idx"]))
    )
    if not 1 <= len(indices) <= 500:
        raise ValueError("趋势聚类同步工程上限 500 个特征；请选择排名前 N 项，不会静默截断")
    expected = len(indices) * len(source["counts"]) + len(indices) ** 2 + 2 * len(indices)
    existing = sum(
        sum(np.asarray(item).size for item in data.uns[name].values())
        for name, run in registry(data)["runs"].items()
        if run["kind"] in {"velocity", "trends", "trend_clusters"} and not run.get("stale")
    )
    if expected + existing > 5_000_000:
        raise ValueError("趋势聚类结果超过累计 500 万数值工程上限，未应用候选")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            normalized = _select_and_standardize_trends(source, top_k)
    except FloatingPointError as error:
        raise ValueError("趋势标准化数值溢出，未应用候选") from error
    valid = np.isfinite(normalized).all(axis=0)
    count = int(valid.sum())
    if not count:
        raise ValueError("没有跨全部窗口有限的趋势；无效特征不会强制归组")
    if cluster_method in {"kmeans", "agglomerative"} and not 1 <= n_clusters <= count:
        raise ValueError("聚类数须在 1 与有效特征数之间")
    if (
        cluster_method == "agglomerative"
        and linkage == "ward"
        and metric not in {"euclidean", "sqeuclidean"}
    ):
        raise ValueError("ward 连接要求 Euclidean 类距离")
    options = {"metric": metric, "cluster_method": cluster_method}
    if cluster_method in {"leiden", "louvain"}:
        options.update(n_neighbors=min(n_neighbors, max(1, count - 1)), random_state=seed)
        if cluster_method == "leiden":
            options["resolution"] = resolution
    elif cluster_method == "kmeans":
        options.update(n_clusters=n_clusters, random_state=seed)
    else:
        options.update(n_clusters=n_clusters, linkage=linkage)
    if count > 1:
        labels, observed = _cluster_labels(normalized, options)
    else:
        labels, observed = trend_cluster(normalized, **options), []
    labels = np.asarray(labels)
    if (
        labels.shape != (len(indices),)
        or labels.dtype.kind not in "iu"
        or np.any(labels < -1)
        or np.any(labels[valid] < 0)
        or np.any(labels[~valid] != -1)
    ):
        raise ValueError("趋势聚类返回无效标签，未应用候选")
    # This is the existing fallback, including finite diagonal zeros. Keep it visible.
    from scipy.spatial.distance import pdist

    with np.errstate(invalid="ignore", divide="ignore"):
        undefined = int((~np.isfinite(pdist(normalized[:, valid].T, metric=metric))).sum())
        actual_distances = _pairwise_distances(normalized[:, valid].T, metric)
    if not np.isfinite(actual_distances).all():
        raise ValueError("趋势距离产生非有限值，未应用候选")
    distances = np.full((len(indices), len(indices)), np.nan)
    distances[np.ix_(valid, valid)] = actual_distances
    ids = np.asarray(parent["parameters"]["feature_ids"])[indices].tolist()
    effective = dict(options)
    effective["singleton_without_fit"] = count == 1
    if cluster_method == "leiden":
        effective.update(n_iterations=2, max_comm_size=0)
    elif cluster_method == "louvain":
        effective.update(resolution=1.0, return_levels=False)
    if cluster_method == "kmeans":
        effective.update(n_init=20, normalize=metric in {"cosine", "correlation"})
    if cluster_method == "agglomerative" and linkage == "ward":
        effective["fit_distance"] = "euclidean_on_standardized_curves"
    versions = {
        "numpy": version("numpy"),
        "scipy": version("scipy"),
        "scikit-learn": version("scikit-learn"),
    }
    if cluster_method in {"leiden", "louvain"} and count > 1:
        versions["igraph"] = version("igraph")
        if cluster_method == "leiden":
            versions["leidenalg"] = version("leidenalg")
    parameters = {
        "trend_key": trend_key,
        "trend_identity": parent["identity"],
        "trend_parameters": parent["parameters"],
        "feature_axis": parent["parameters"]["feature_axis"],
        "feature_ids": ids,
        "metric": metric,
        "cluster_method": cluster_method,
        "top_k": top_k,
        "requested_parameters": {
            "seed": seed,
            "n_clusters": n_clusters,
            "n_neighbors": n_neighbors,
            "resolution": resolution,
            "linkage": linkage,
        },
        "requested_seed": seed,
        "seed": seed if count > 1 and cluster_method != "agglomerative" else None,
        "effective_parameters": effective,
        "valid_features": count,
        "actual_clusters": len(set(labels[labels >= 0].tolist())),
        "warnings": observed,
        "standardization": "existing_window_mean_and_population_std; constant=0; missing_kept",
        "undefined_distance_pairs": undefined,
        "distance_fallback": "existing_max_finite_including_zero_diagonal",
        "execution": "isolated_cluster_process" if count > 1 else "in_request",
        "versions": versions,
    }
    data.uns[key] = {
        "normalized": normalized,
        "labels": labels.astype(int),
        "indices": indices,
        "distances": distances,
    }
    data.uns[f"{key}_params"] = parameters.copy()
    inputs = [*parent["inputs"], *parent["outputs"]]
    return _publish(
        data,
        key,
        "trend_clusters",
        parameters,
        inputs,
        [binding(data, "uns", name) for name in (key, f"{key}_params")],
    )


def cluster_tables(data, key, run):
    values = data.uns[key]
    parent = data.uns[run["parameters"]["trend_key"]]
    indices = np.asarray(values["indices"], dtype=int)
    ids = run["parameters"]["feature_ids"]
    labels = np.asarray(values["labels"])
    matrix = np.asarray(values["normalized"])
    features = pd.DataFrame(
        {
            "feature_id": ids,
            "feature_name": np.asarray(parent["feature_names"])[indices],
            "cluster": labels,
            "valid_curve": np.isfinite(matrix).all(axis=0),
            "measured_windows": (np.asarray(parent["finite_counts"])[:, indices] > 0).sum(axis=0),
            "source_rank": (np.argsort(parent["rank_idx"]) + 1)[indices],
        }
    )
    curves = pd.DataFrame(
        {
            "window_index": np.repeat(np.arange(matrix.shape[0]), len(ids)),
            "feature_id": np.tile(ids, matrix.shape[0]),
            "pooled": np.asarray(parent["pooled"])[:, indices].ravel(),
            "normalized": matrix.ravel(),
            "finite_cells": np.asarray(parent["finite_counts"])[:, indices].ravel(),
        }
    )
    distances = pd.DataFrame(
        {
            "source_id": np.repeat(ids, len(ids)),
            "target_id": np.tile(ids, len(ids)),
            "distance": np.asarray(values["distances"]).ravel(),
        }
    )
    windows = pd.DataFrame(
        {
            "window_index": np.arange(matrix.shape[0]),
            "time_center": parent["time_centers"],
            "cells": parent["counts"],
            "window_start": parent["window_starts"],
        }
    )
    return {"features": features, "curves": curves, "distances": distances, "windows": windows}


def cluster_figure(data, key, run):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    values = data.uns[key]
    labels = np.asarray(values["labels"])
    groups = np.unique(labels[labels >= 0])
    matrix = np.asarray(values["normalized"])
    if matrix.size > 200_000:
        raise ValueError("趋势聚类图超过 20 万显示值，请另算较少特征的排名子集；完整结果仍可下载")
    parent = data.uns[run["parameters"]["trend_key"]]
    times = np.asarray(parent["time_centers"])
    fig = make_subplots(
        rows=len(groups),
        cols=1,
        subplot_titles=[f"簇 {label} · {int((labels == label).sum())} 个特征" for label in groups],
    )
    ids = run["parameters"]["feature_ids"]
    for row, label in enumerate(groups, 1):
        members = np.flatnonzero(labels == label)
        for column in members:
            fig.add_trace(
                go.Scatter(
                    x=times,
                    y=matrix[:, column],
                    name=ids[column],
                    mode="lines",
                    connectgaps=False,
                    line={"color": "#94a3b8", "width": 1},
                    showlegend=False,
                ),
                row=row,
                col=1,
            )
        fig.add_trace(
            go.Scatter(
                x=times,
                y=matrix[:, members].mean(axis=1),
                name=f"簇 {label} 均值",
                mode="lines",
                line={"color": "#111827", "width": 2},
            ),
            row=row,
            col=1,
        )
        fig.update_xaxes(
            title_text=f"时间 ({run['parameters']['trend_parameters']['unit']})", row=row, col=1
        )
        fig.update_yaxes(title_text="标准化趋势", row=row, col=1)
    fig.update_layout(
        title=f"趋势聚类 · {key}",
        height=max(400, 250 * len(groups)),
        meta={
            "trend_cluster_parent": run["parameters"]["trend_key"],
            "trend_cluster_groups": groups.tolist(),
        },
    )
    notes = [
        "按既有流程在聚类前标准化趋势；常量曲线为 0，无跨窗口有限趋势的特征标记 -1，不在簇图中强制归组。",
        "灰线为完整成员曲线，黑线为该簇窗口均值；图、分组和导出读取存储结果，不重新聚类。",
        f"{run['parameters']['undefined_distance_pairs']} 对距离未定义，沿原算法以矩阵最大有限值（含对角线 0）替代；不是生物距离证据。",
        "KMeans 还按所选距离沿原算法处理归一化；Ward 使用标准化曲线的欧氏空间。分组仅为趋势形状探索，不证明代谢通路或因果。",
        f"时间含义：{run['parameters']['trend_parameters']['time_kind']}；单位：{run['parameters']['trend_parameters']['unit']}。伪时间和归一化进程不是物理时间。",
        *run["parameters"]["warnings"],
    ]
    return fig, notes
