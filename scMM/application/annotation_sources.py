"""Resolve review sources independently of the active statistical branch."""
# ruff: noqa: RUF001

import json

from scMM.util.lipid_annotation import annotation_store, feature_axis


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
        has_masses = False
        if context.get("variable_kind") != "empirical_compound":
            try:
                feature_axis(data)
            except (TypeError, ValueError):
                pass
            else:
                has_masses = True
        if has_masses:
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


def analysis_review_source(project, data):
    """Map active branch variables back to the measured peak IDs."""
    state = project.ion_state
    if state is None:
        source = "current" if review_sources(project)["sources"] else ""
    else:
        branch = state["branches"].get(state["active_branch_id"])
        source = state["views"][branch["view_id"]]["root_id"] if branch else ""
        if source not in state["roots"]:
            source = ""
    if not source:
        return "", {}
    measured, _ = feature_source(project, source)
    peaks = data.var.get("quantifier_feature_id", data.var_names)
    return source, {
        str(variable): str(peak)
        for variable, peak in zip(data.var_names, peaks, strict=True)
        if str(peak) in measured.var_names
    }


def analysis_annotations(project, data):
    """Read active candidates from the measurement source, projected onto the branch."""
    from scMM.util.lipid_annotation import version_valid

    source, mapping = analysis_review_source(project, data)
    if not source:
        return {}, None
    measured, _ = feature_source(project, source)
    store = source_versions(project, measured, source)
    version = next((v for v in store["versions"] if v["id"] == store["active"]), None)
    if not version or not version_valid(measured, version):
        return {}, None
    names = {}
    for candidate in version["candidates"]:
        names.setdefault(candidate["feature_id"], set()).add(str(candidate.get("name", "")))
    return {variable: names[peak] for variable, peak in mapping.items() if peak in names}, version
