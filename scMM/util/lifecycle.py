"""Shared derived-artifact and serialized-report lifecycle rules."""


def invalidate_derived(data):
    from .time_results import invalidate_time_results

    invalidate_time_results(data, clear=True)
    metadata = data.uns.setdefault("scmm_workbench", {})
    for column in metadata.get("derived_obs", []):
        if column in data.obs:
            del data.obs[column]
    metadata["derived_obs"] = []
    if "reports_json" in metadata:
        metadata["reports_json"] = "{}"
    if "latent_dependencies_json" in metadata:
        metadata["latent_dependencies_json"] = "{}"
    for mapping in (data.obsm, data.obsp, data.varm, data.varp):
        mapping.clear()
    for key in list(data.uns):
        if key.endswith(("_params", "_qc")) or key in {
            "neighbors",
            "pca",
            "umap",
            "tsne",
            "scmm_saved_reports",
        }:
            del data.uns[key]


def stored_observation_dependencies(name, value, reports):
    """Read schema-1 dependency evidence, including legacy label/group fields."""
    if not isinstance(value, dict):
        raise ValueError("invalid stored analysis report")
    if "_observation_dependencies" in value:
        keys = value["_observation_dependencies"]
        if not isinstance(keys, list) or any(not isinstance(key, str) or not key for key in keys):
            raise ValueError("invalid stored observation dependencies")
        return set(keys)
    if name == "shap" and "supervised" in reports:
        return stored_observation_dependencies("supervised", reports["supervised"], reports)
    keys = [value.get("label_key"), value.get("group_key")]
    if any(key is not None and not isinstance(key, str) for key in keys):
        raise ValueError("invalid stored label/group dependencies")
    return {key for key in keys if key}


def stale_stored_reports(reports, changed):
    """Filter existing typed reports; missing legacy supervision stays conservative."""
    if not changed:
        return set()
    if not isinstance(reports, dict):
        raise ValueError("stored reports must be a mapping")
    stale = set()
    for name, report in reports.items():
        dependencies = stored_observation_dependencies(name, report, reports)
        if dependencies & changed or (name in {"supervised", "shap"} and not dependencies):
            stale.add(name)
    if "supervised" in stale:
        stale.add("shap")
    return stale


def invalidate_observation_reports(data, changed):
    """Update serialized reports on a caller-owned AnnData candidate only."""
    import json

    metadata = data.uns.get("scmm_workbench", {})
    if not isinstance(metadata, dict):
        raise ValueError("invalid scmm_workbench metadata")
    if not changed or "reports_json" not in metadata:
        return set()
    if metadata.get("schema_version", 1) != 1:
        raise ValueError("unsupported stored report metadata schema")
    try:
        reports = json.loads(metadata["reports_json"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid stored reports_json") from exc
    stale = stale_stored_reports(reports, changed)
    if stale:
        metadata["reports_json"] = json.dumps(
            {key: value for key, value in reports.items() if key not in stale}
        )
    return stale


def invalidate_observation_embeddings(data, changed):
    """Invalidate declared supervised coordinates, preserving independent embeddings."""
    import json

    if not changed:
        return set()
    metadata = data.uns.get("scmm_workbench", {})
    if not isinstance(metadata, dict):
        raise ValueError("invalid scmm_workbench metadata")
    if metadata.get("schema_version", 1) != 1 and any(
        key in metadata for key in ("latent_dependencies_json", "history_json")
    ):
        raise ValueError("unsupported latent dependency metadata schema")
    try:
        rules = json.loads(metadata.get("latent_dependencies_json", "{}"))
        history = json.loads(metadata.get("history_json", "[]"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid latent dependency metadata") from exc
    if not isinstance(rules, dict) or not isinstance(history, list):
        raise ValueError("invalid latent dependency metadata")
    # Latest recorded writer owns each output key. A reused PCA key is not latent.
    legacy = {}
    independent = set()
    for entry in history:
        if not isinstance(entry, dict) or entry.get("operation") not in {"latent", "reduce"}:
            continue
        parameters = entry.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("invalid preprocessing history parameters")
        key = parameters.get("store_key")
        if not isinstance(key, str) or not key:
            continue
        if entry.get("operation") == "latent":
            legacy[key] = parameters.get("observation_dependencies")
            independent.discard(key)
        elif entry.get("operation") == "reduce":
            legacy.pop(key, None)
            independent.add(key)
    for key in independent:
        rules.pop(key, None)
    for key, fields in legacy.items():
        rules.setdefault(key, fields)
    expired = []
    for key, fields in rules.items():
        if not isinstance(key, str) or not key:
            raise ValueError("invalid latent output key")
        if fields is not None and (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) or not field for field in fields)
        ):
            raise ValueError("invalid latent observation dependencies")
        if key in data.obsm and (fields is None or set(fields) & changed):
            expired.append(key)
    if not expired:
        from .time_results import invalidate_time_results

        return invalidate_time_results(data, changed)
    tracked = metadata.get("derived_obs", [])
    if isinstance(tracked, str):
        raise ValueError("invalid derived observation metadata")
    try:
        tracked = list(tracked)
    except TypeError as exc:
        raise ValueError("invalid derived observation metadata") from exc
    if any(not isinstance(key, str) for key in tracked):
        raise ValueError("invalid derived observation metadata")
    removed = set()
    for key in expired:
        del data.obsm[key]
        split = f"{key}_split"
        if split in tracked and split in data.obs:
            del data.obs[split]
            removed.add(split)
        data.uns.pop(f"{key}_params", None)
        rules.pop(key, None)
    metadata["derived_obs"] = [key for key in tracked if key not in removed]
    metadata["latent_dependencies_json"] = json.dumps(rules)
    from .time_results import invalidate_time_results

    return removed | invalidate_time_results(data, set(changed) | removed)
