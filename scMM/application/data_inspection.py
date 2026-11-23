"""Read-only, bounded data inspection for the web editor."""
# ruff: noqa: RUF001

import json

import numpy as np
import pandas as pd
from scipy import sparse


def inspect_data(data, feature_offset=0, feature_query="", name_filter="all"):
    feature_query = feature_query.strip().casefold()
    matrix = data.X
    warnings = []
    finite = True
    zero_rows = 0
    observed_columns = np.zeros(data.n_vars, dtype=bool)
    totals = np.zeros(data.n_vars, dtype=float)
    absolute_totals = np.zeros(data.n_vars, dtype=float)
    negative = False
    rows_per_block = max(1, 1_000_000 // max(1, data.n_vars))
    for start in range(0, data.n_obs, rows_per_block):
        block = matrix[start : start + rows_per_block]
        if sparse.issparse(block):
            block = block.copy()
            block.eliminate_zeros()
            finite = finite and bool(np.isfinite(block.data).all())
            zero_rows += int(np.count_nonzero(block.getnnz(axis=1) == 0))
            observed_columns |= block.getnnz(axis=0) > 0
        else:
            block = np.asarray(block)
            finite = finite and bool(np.isfinite(block).all())
            present = block != 0
            zero_rows += int(np.count_nonzero(~present.any(axis=1)))
            observed_columns |= present.any(axis=0)
        negative = negative or bool(
            (block.data < 0).any() if sparse.issparse(block) else (block < 0).any()
        )
        totals += np.asarray(block.sum(axis=0)).ravel()
        absolute_totals += np.asarray(abs(block).sum(axis=0)).ravel()
    zero_columns = int(np.count_nonzero(~observed_columns))
    if not finite:
        warnings.append("存在非有限数值。")
    if not data.obs_names.is_unique or not data.var_names.is_unique:
        warnings.append("观测或特征 ID 重复。")
    if zero_rows:
        warnings.append(f"存在 {zero_rows} 个全零观测。")
    if not data.n_obs:
        zero_columns = 0
        warnings.append("未提供定量观测，可用于特征注释。")
    if zero_columns:
        warnings.append(f"存在 {zero_columns} 个全零特征。")
    if data.n_obs and (
        "group" not in data.obs
        or data.obs["group"].astype("string").fillna("").str.strip().eq("").any()
    ):
        warnings.append("分组信息不完整。")
    observation_positions = np.sort(
        np.random.default_rng(0).choice(data.n_obs, min(10, data.n_obs), replace=False)
    )
    feature_positions = np.argsort(
        -np.nan_to_num(absolute_totals if negative else totals, nan=-np.inf), kind="stable"
    )[:10]
    preview = matrix[observation_positions][:, feature_positions]
    if sparse.issparse(preview):
        preview = preview.toarray()
    names = data.var.get("display_name", pd.Series("", index=data.var_names)).fillna("").astype(str)
    matches = np.ones(data.n_vars, dtype=bool)
    if feature_query:
        matches &= np.array(
            [
                feature_query in str(key).casefold() or feature_query in name.casefold()
                for key, name in zip(data.var_names, names, strict=True)
            ]
        )
    if name_filter != "all":
        matches &= names.str.strip().ne("").to_numpy() == (name_filter == "named")
    selected = np.flatnonzero(matches)
    return dict(
        preview_basis="absolute_total" if negative else "total_intensity",
        feature_total=len(selected),
        feature_rows=[
            {"id": str(data.var_names[position]), "name": names.iloc[position]}
            for position in selected[feature_offset : feature_offset + 10]
        ],
        feature_history=json.loads(data.uns.get("scmm_manual_annotations_json", "[]")),
        metadata_history=json.loads(data.uns.get("scmm_metadata_edits_json", "[]")),
        observations=data.n_obs,
        features=data.n_vars,
        warnings=warnings,
        observation_ids=data.obs_names[observation_positions].astype(str).tolist(),
        feature_ids=data.var_names[feature_positions].astype(str).tolist(),
        values=[[float(x) if np.isfinite(x) else None for x in row] for row in np.asarray(preview)],
    )


def workflow_status(project):
    from .annotation_sources import analysis_annotations
    from .method_reports import current_reports

    state = project.workspace

    data = state.require_features()
    history = json.loads(data.uns.get("scmm_workbench", {}).get("history_json", "[]"))
    _, annotation = analysis_annotations(project, data)
    return {
        "/data-editor": bool(json.loads(data.uns.get("scmm_metadata_edits_json", "[]")))
        or bool(json.loads(data.uns.get("scmm_manual_annotations_json", "[]")))
        or any(row.get("operation") == "selection_labels" for row in history),
        "/preprocess": any(
            row.get("operation")
            in {"filter", "impute", "normalize", "remove_outliers", "plugin_preprocess"}
            for row in history
        ),
        "/analysis": bool(data.obsm)
        or bool(project.saved_reports)
        or bool(current_reports(data))
        or any(token == state.token for token, _ in state.results.values()),
        "/annotation": annotation is not None,
    }
