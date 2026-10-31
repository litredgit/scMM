"""View-aware analysis contracts without duplicating numerical engines."""

import json
from copy import deepcopy

import numpy as np
import pandas as pd

from scMM.ion.identity import dataset_identity
from scMM.ion.semantics import value_states

KEY = "scmm_analysis_input_json"


def bind_analysis_input(workspace, view, branch_id):
    context = {
        "schema_version": 1,
        "view_id": view["id"],
        "branch_id": branch_id,
        "root_id": view["root_id"],
        "root_identity": view["root_identity"],
        "level": view["level"],
        "variable_kind": view["variable_kind"],
        "grouping_id": view.get("grouping_id"),
        "quantification_id": view.get("quantification_id"),
        "source_identity": view.get("source_identity", view["root_identity"]),
        "representation_selection_scope": "full input; not independently validated by holdout",
    }
    encoded = json.dumps(context, sort_keys=True)
    for data in (workspace.data, workspace._original):
        if data is not None:
            data.uns[KEY] = encoded


def workspace_input(workspace, *, layer=None, purpose="analysis"):
    data = workspace.require_data()
    matrix = data.X if layer in {None, "X", ""} else data.layers[layer]
    values = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    if not np.isfinite(values).all():
        raise ValueError("materialize a complete availability branch before analysis")
    context = json.loads(data.uns[KEY]) if KEY in data.uns else {"level": "legacy"}
    return {
        **context,
        "dataset_id": workspace.dataset_id,
        "revision": workspace.revision,
        "layer": layer or "X",
        "purpose": purpose,
        "shape": list(data.shape),
        "identity": dataset_identity(data),
        "value_state": value_states(data)[layer or "X"],
        "statistical_unit": "cell",
    }


def resolve_analysis_input(
    project, *, view_id=None, branch_id=None, layer=None, purpose="analysis"
):
    if project.ion_state is not None:
        active = project.ion_state["active_branch_id"]
        if active is None:
            raise ValueError("select a materialized analysis branch")
        entry = project.ion_state["branches"][active]
        if branch_id not in {None, active} or view_id not in {None, entry["view_id"]}:
            raise ValueError("activate the requested branch before computing")
        bind_analysis_input(project.workspace, project.ion_state["views"][entry["view_id"]], active)
    elif view_id is not None or branch_id is not None:
        raise ValueError("legacy project has no view catalogue")
    return workspace_input(project.workspace, layer=layer, purpose=purpose)


def replicate_summary(data, *, replicate_key, group_key=None, layer=None, statistic="mean"):
    """Export replicate summaries; this does not run replicate-level inference."""
    if statistic not in {"mean", "median", "sum"}:
        raise ValueError("statistic must be mean, median or sum")
    keys = list(dict.fromkeys([replicate_key, *([group_key] if group_key else [])]))
    if data.obs[keys].isna().any().any():
        raise ValueError("replicate/group labels must be complete")
    matrix = data.X if layer in {None, "X"} else data.layers[layer]
    matrix = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    if not np.isfinite(matrix).all():
        raise ValueError("summary input must be finite")
    frame = pd.DataFrame(matrix, index=data.obs_names, columns=data.var_names)
    groups = [data.obs[key].rename(key) for key in keys]
    grouped = frame.groupby(groups, observed=True, sort=True)
    result = getattr(grouped, statistic)().reset_index()
    result["cell_count"] = grouped.size().to_numpy()
    result.attrs["input"] = {
        "replicate_key": replicate_key,
        "group_key": group_key,
        "layer": layer or "X",
        "statistic": statistic,
        "inference_performed": False,
    }
    return result


def compare_views(project, *, branch_ids, normalization_mode, shared_factors=None):
    """Compare existing branches and results only; never rerun an analysis."""
    from sklearn.metrics import adjusted_rand_score

    from .data_views import DataViewCatalog, freeze_active_branch

    if normalization_mode not in {"shared", "independent"}:
        raise ValueError("declare shared or independent normalization")
    if len(branch_ids) < 2 or len(set(branch_ids)) != len(branch_ids):
        raise ValueError("select at least two distinct branches")
    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    entries = [catalog._branches[key] for key in branch_ids]
    datasets = [entry["workspace"].require_data() for entry in entries]
    cells = list(datasets[0].obs_names)
    if any(list(data.obs_names) != cells for data in datasets):
        raise ValueError("comparison requires identical ordered cell IDs")
    if normalization_mode == "shared":
        if not isinstance(shared_factors, dict) or set(shared_factors) != set(cells):
            raise ValueError("provide the shared normalization denominator for every cell")
        if any(not np.isfinite(v) or v <= 0 for v in shared_factors.values()):
            raise ValueError("shared normalization factors must be finite and positive")
        # A supplied denominator is an audit declaration, not an implicit matrix transformation.
        for data in datasets:
            recorded = data.uns.get("scmm_shared_normalization_json")
            if recorded is None or json.loads(recorded) != shared_factors:
                raise ValueError("branches must record the applied shared normalization factors")
    summaries = []
    for key, entry, data in zip(branch_ids, entries, datasets, strict=True):
        ws = entry["workspace"]
        reductions = {
            name: deepcopy(dict(value))
            for name, value in data.uns.items()
            if name.endswith("_params") and hasattr(value, "get") and value.get("method") == "pca"
        }
        differential = None
        if "differential" in ws.results:
            result = ws.result("differential")
            differential = {
                "input": deepcopy(result.get("input")),
                "rows": result["table"].to_dict(orient="records"),
            }
        summaries.append(
            {
                "branch_id": key,
                "input": workspace_input(ws),
                "variable_universe": list(data.var_names),
                "normalization": value_states(data)["X"]["normalization"],
                "pca": reductions,
                "pca_loadings": {
                    name: np.asarray(value).tolist()
                    for name, value in data.varm.items()
                    if name.endswith("_loadings")
                },
                "differential": differential,
                "quantifier_mapping": data.var[
                    [c for c in ("quantifier_feature_id", "source_members_json") if c in data.var]
                ].to_dict(orient="index"),
            }
        )
    comparisons = []
    for i, left in enumerate(datasets):
        for j in range(i + 1, len(datasets)):
            right = datasets[j]
            clusters = {}
            for name in set(left.obs) & set(right.obs):
                if (
                    (name == "cluster" or name.startswith("cluster_"))
                    and not left.obs[name].isna().any()
                    and not right.obs[name].isna().any()
                ):
                    clusters[name] = float(
                        adjusted_rand_score(left.obs[name].astype(str), right.obs[name].astype(str))
                    )
            matching = set(summaries[i]["pca"]) & set(summaries[j]["pca"])
            diagnostics = {
                name: "matching parameters"
                if {k: v for k, v in summaries[i]["pca"][name].items() if "variance" not in k}
                == {k: v for k, v in summaries[j]["pca"][name].items() if "variance" not in k}
                else "parameters differ"
                for name in matching
            }
            comparisons.append(
                {
                    "left": branch_ids[i],
                    "right": branch_ids[j],
                    "cluster_adjusted_rand": clusters,
                    "pca_comparability": diagnostics,
                }
            )
    return {
        "schema_version": 1,
        "cell_ids": cells,
        "normalization_mode": normalization_mode,
        "shared_factors": deepcopy(shared_factors),
        "branches": summaries,
        "comparisons": comparisons,
        "interpretation": "descriptive sensitivity comparison; no experimental accuracy claim",
    }


def apply_shared_normalization(workspace, factors):
    """Apply explicitly supplied, cell-indexed positive denominators on a branch."""
    from scMM.ion.semantics import write_value_states

    data = workspace.require_data()
    if set(factors) != set(data.obs_names):
        raise ValueError("shared denominators must cover exactly the selected cells")
    denominators = np.asarray([factors[key] for key in data.obs_names], dtype=float)
    if not np.isfinite(denominators).all() or (denominators <= 0).any():
        raise ValueError("shared denominators must be finite and positive")
    if value_states(data)["X"]["space"] != "linear_abundance":
        raise ValueError("shared normalization requires known linear_abundance")
    candidate = data.copy()
    matrix = candidate.X.toarray() if hasattr(candidate.X, "toarray") else candidate.X
    candidate.X = matrix / denominators[:, None]
    candidate.uns["scmm_shared_normalization_json"] = json.dumps(factors, sort_keys=True)
    states = value_states(candidate)
    states["X"]["normalization"].append({"method": "shared", "denominators": deepcopy(factors)})
    write_value_states(candidate, states)
    workspace._commit(candidate, "shared_normalization", {"denominators": deepcopy(factors)})
