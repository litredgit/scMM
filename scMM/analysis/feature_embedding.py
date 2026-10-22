"""Feature-distance UMAP with explicit identities and bounded dense allocations."""

# ruff: noqa: RUF001

import warnings

import numpy as np
import pandas as pd
import plotly.express as px
from sklearn.metrics import pairwise_distances

from scMM.plot.presentation import PLOT_COLORS

from .preprocessing import integer, real

MAX_FEATURES = 500
MAX_VALUES = 2_000_000


def feature_distance_matrix(values, metric):
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or min(values.shape) < 1 or not np.isfinite(values).all():
        raise ValueError("feature distances require finite non-empty input")
    if metric not in {"pearson", "euclidean"}:
        raise ValueError("metric must be pearson or euclidean")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            if metric == "pearson":
                if len(values) < 2 or np.any(np.ptp(values, axis=0) == 0):
                    raise ValueError(
                        "Pearson distance requires at least two cells and no constant features"
                    )
                correlations = np.corrcoef(values.T)
                distances = np.sqrt(2 * (1 - np.clip(np.abs(correlations), 0, 1)))
            else:
                distances = pairwise_distances(values.T, metric="euclidean")
    except FloatingPointError as exc:
        raise ValueError("feature distance is undefined at this numerical scale") from exc
    if not np.isfinite(distances).all():
        raise ValueError("feature distance contains non-finite values")
    np.fill_diagonal(distances, 0)
    return distances


def feature_embedding_figure(
    data,
    *,
    features=None,
    layer=None,
    metric="pearson",
    name_key=None,
    class_key=None,
    n_neighbors=None,
    min_dist=0.1,
    random_state=42,
):
    identities = list(data.var_names) if not features else list(features)
    if len(identities) != len(set(identities)) or not set(identities).issubset(data.var_names):
        raise ValueError("select unique stable feature IDs from the current matrix")
    if not 3 <= len(identities) <= MAX_FEATURES or data.n_obs * len(identities) > MAX_VALUES:
        raise ValueError(
            "feature embedding requires 3–500 features and at most 2000000 input values"
        )
    for key in (name_key, class_key):
        if key is not None and key not in data.var:
            raise ValueError("selected feature metadata column is missing")
    if layer is not None and layer not in data.layers:
        raise ValueError("selected intensity layer is missing")
    count = integer(
        "n_neighbors",
        min(15, len(identities) - 1) if n_neighbors is None else n_neighbors,
        2,
        len(identities) - 1,
    )
    distance = real("min_dist", min_dist, inclusive=True)
    if distance > 1:
        raise ValueError("min_dist must be within [0, 1]")
    seed = integer("random_state", random_state, 0, 2147483647)
    selected = data[:, identities]
    matrix = selected.X if layer is None else selected.layers[layer]
    values = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    distances = feature_distance_matrix(values, metric)
    if not np.any(distances > 0):
        raise ValueError(
            "all selected features have zero distance; an embedding is not informative"
        )
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Tensorflow not installed; ParametricUMAP will be unavailable",
                category=ImportWarning,
            )
            from umap import UMAP
    except ImportError as exc:
        raise ImportError(
            "Feature embedding requires umap-learn; install scMM[web] or scMM[plot]"
        ) from exc
    # This warning describes the unused inverse_transform API, not fit quality.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="using precomputed metric; inverse_transform will be unavailable",
            category=UserWarning,
        )
        coordinates = UMAP(
            metric="precomputed",
            n_components=2,
            n_neighbors=count,
            min_dist=distance,
            random_state=seed,
            init="random",
            n_jobs=1,
        ).fit_transform(distances)
    if coordinates.shape != (len(identities), 2) or not np.isfinite(coordinates).all():
        raise ValueError("feature embedding produced invalid coordinates")
    frame = pd.DataFrame(
        {
            "feature_id": identities,
            "name": identities,
            "UMAP1": coordinates[:, 0],
            "UMAP2": coordinates[:, 1],
        }
    )
    notes = [
        "特征距离嵌入：每点为一个特征，不是细胞嵌入或相关阈值网络。",
        "Pearson 距离为 sqrt(2 × (1 − |r|))，正负完全相关均为零距离；Euclidean 使用所选强度原值，不额外标准化。",
        "UMAP 坐标无强度或时间单位；二维相邻不证明分子关系或鉴定。距离及坐标完整导出，seed 和输入选项随图保存。",
    ]
    if name_key is not None:
        names = selected.var[name_key]
        valid = names.notna() & names.astype(str).str.strip().ne("")
        frame.loc[valid.to_numpy(), "name"] = names.loc[valid].astype(str).to_numpy()
        if not valid.all():
            notes.append("缺失/空白名称使用稳定特征 ID，不静默删除特征；重名依靠 ID 区分。")
    if class_key is not None:
        frame["category"] = (
            selected.var[class_key].astype("string").fillna("（缺失类别）").to_numpy()
        )
    figure = px.scatter(
        frame,
        color_discrete_sequence=PLOT_COLORS,
        x="UMAP1",
        y="UMAP2",
        color="category" if class_key else None,
        hover_name="name",
        custom_data=["feature_id"],
        labels={"category": class_key or "类别"},
    )
    distance_frame = pd.DataFrame(distances, index=identities, columns=identities)
    distance_frame.index.name = "feature_id"
    figure.update_layout(
        title="特征距离嵌入",
        meta={
            "point_kind": "feature",
            "notes": notes,
            "effective_parameters": {
                "metric": metric,
                "n_neighbors": count,
                "min_dist": distance,
                "random_state": seed,
                "init": "random",
                "n_jobs": 1,
                "n_cells": data.n_obs,
                "n_features": len(identities),
                "layer": layer,
                "name_key": name_key,
                "class_key": class_key,
            },
            "observation_dependencies": [],
            "export_tables": {
                "features.csv": frame.to_csv(index=False),
                "distances.csv": distance_frame.to_csv(),
            },
        },
    )
    return figure
