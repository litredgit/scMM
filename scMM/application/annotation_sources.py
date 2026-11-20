"""Resolve review sources independently of the active statistical branch."""
# ruff: noqa: RUF001

import json

from scMM.util.lipid_annotation import annotation_store


def review_sources(project):
    state = project.ion_state
    data = project.workspace.data
    sources = []
    active = None
    if state is not None:
        branch_id = state.get("active_branch_id")
        branch = state["branches"].get(branch_id)
        if branch is not None:
            view = state["views"][branch["view_id"]]
            active = {"branch_id": branch_id, "view_id": view["id"], "level": view["level"]}
        sources = [
            {
                "id": key,
                "identity": entry["metadata"]["identity"],
                "label": f"L0 测量根 · {key[:8]}",
                "features": entry["data"].n_vars,
                "quantitation_available": True,
            }
            for key, entry in state["roots"].items()
        ]
        default = view["root_id"] if branch is not None else ""
    else:
        default = ""
    if data is not None and not sources:
        context = json.loads(data.uns.get("scmm_analysis_input_json", "{}"))
        if context.get("variable_kind") != "empirical_compound":
            default = "current"
            sources.append(
                {
                    "id": "current",
                    "identity": ":".join(map(str, project.workspace.token)),
                    "label": "当前特征数据" if data.n_obs else "独立特征表",
                    "features": data.n_vars,
                    "quantitation_available": bool(data.n_obs),
                }
            )
    if default not in {source["id"] for source in sources}:
        default = sources[0]["id"] if sources else ""
    return {"sources": sources, "default_source": default, "statistics": active}


def feature_source(project, source=""):
    if source in {"", "current"}:
        data = project.workspace.require_features()
        context = json.loads(data.uns.get("scmm_analysis_input_json", "{}"))
        if context.get("variable_kind") == "empirical_compound":
            raise ValueError("当前统计输入为 EC，请选择可用的测量根查看实测峰。")
        return data, ":".join(map(str, project.workspace.token))
    root = (project.ion_state or {}).get("roots", {}).get(source)
    if root is None:
        raise ValueError("所选测量来源不属于当前项目。")
    return root["data"], root["metadata"]["identity"]


def source_versions(project, data, source=""):
    if source in {"", "current"}:
        return annotation_store(data)
    state = project.ion_state
    stored = state["registry"].get("feature_annotations", {}).get(source)
    if stored is not None:
        if stored["root_identity"] != state["roots"][source]["metadata"]["identity"]:
            raise ValueError("注释与测量根的身份不一致。")
        return stored["store"]
    # An existing L0 branch may predate source-scoped writes. Its versions are
    # still subject to validation against the actual review matrix and conditions.
    for branch_id, entry in state["branches"].items():
        view = state["views"][entry["view_id"]]
        if view["root_id"] != source or view["level"] != "L0":
            continue
        branch_data = (
            project.workspace.data
            if branch_id == state["active_branch_id"]
            else entry["workspace"]["data"]
        )
        versions = annotation_store(branch_data)
        if versions["versions"]:
            return versions
    return annotation_store(data)
