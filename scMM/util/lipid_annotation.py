"""Indexed MS1 lipid candidates and immutable annotation-version identities."""
# ruff: noqa: RUF001

import hashlib
import json

import numpy as np

from .lipid_isotopes import ADDUCTS, adduct_shift, isotope_evidence
from .lipid_rules import rank_candidates, validate_rules

STORAGE_KEY = "scmm_lipid_annotations_json"


def validate_intensity_layer(data, layer):
    if layer == "feature_snr":
        raise ValueError("SNR 不是强度，不能用作同位素比例来源。")
    transformed, current = set(), False
    history = json.loads(data.uns.get("scmm_workbench", {}).get("history_json", "[]"))
    for step in history:
        operation = step.get("operation")
        if operation in {"normalize", "impute"}:
            current = True
        elif operation == "restore":
            current = step.get("parameters", {}).get("layer") in transformed
        elif operation == "reset":
            current = False
        if step.get("layer") and current:
            transformed.add(step["layer"])
    if (layer == "X" and current) or layer in transformed:
        raise ValueError("所选强度已归一化或插补，请选择未变换的输入强度层。")


def dataset_inputs(data, layer=""):
    feature_ids = data.var_names.astype(str).tolist()
    mz = np.asarray(data.var.get("mz", data.var_names), dtype=float)
    if not np.isfinite(mz).all() or (mz <= 0).any() or not data.var_names.is_unique:
        raise ValueError("注释需要唯一特征 ID 和正的有限 m/z；允许不同 ID 对应相同 m/z。")
    layer = layer or data.uns.get("scmm_workbench", {}).get("original_layer", "")
    validate_intensity_layer(data, layer)
    matrix = data.X if layer in {"", "X"} else data.layers[layer]
    values = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("同位素检测需要有限、非负的未变换强度，请选择原始强度层。")
    group_key = next((key for key in ("sample_id", "sample", "source_file") if key in data.obs), "")
    samples = (
        data.obs[group_key].astype("string").fillna("未分组").to_numpy(dtype=str)
        if group_key
        else np.repeat("单样本", data.n_obs)
    )
    digest = hashlib.sha256()
    for value in (
        feature_ids,
        mz.tolist(),
        data.obs_names.astype(str).tolist(),
        samples.tolist(),
        layer,
    ):
        digest.update(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    digest.update(np.ascontiguousarray(values, dtype="<f8").tobytes())
    return feature_ids, mz, values, samples, layer, digest.hexdigest()


def mass_candidates(database, feature_ids, mz, parameters, database_identity):
    masses = database["EXACT_MASS"].to_numpy(dtype=float)
    records = database.to_dict(orient="records")
    rows = []
    for adduct in parameters["adducts"]:
        spec = ADDUCTS[adduct]
        if parameters["polarity"] != "both" and spec["polarity"] != parameters["polarity"]:
            raise ValueError("所选加合物与搜索极性不一致。")
        shift = adduct_shift(adduct)
        ppm = parameters["annotation_ppm"] * 1e-6
        for feature_id, query in zip(feature_ids, mz, strict=True):
            # Query-relative bounds are converted back to theoretical-relative ppm bounds.
            low, high = query / (1 + ppm) - shift, query / (1 - ppm) - shift
            start, end = np.searchsorted(
                masses, [np.nextafter(low, -np.inf), np.nextafter(high, np.inf)]
            )
            for index in range(start, end):
                record = records[index]
                theoretical = masses[index] + shift
                error = (query - theoretical) / theoretical * 1e6
                if abs(error) > np.nextafter(parameters["annotation_ppm"], np.inf):
                    continue
                identity = json.dumps(
                    [database_identity["sha256"], feature_id, record["record_id"], adduct]
                )
                rows.append(
                    {
                        "candidate_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                        "feature_id": feature_id,
                        "query_mz": float(query),
                        "database_id": record["record_id"],
                        "name": str(record["COMMON_NAME"]),
                        "formula": str(record["FORMULA"]),
                        "adduct": adduct,
                        "polarity": spec["polarity"],
                        "theoretical_mz": float(theoretical),
                        "ppm_error": float(error),
                        "abs_ppm_error": float(abs(error)),
                        **{
                            key: str(record.get(key, ""))
                            for key in (
                                "LM_ID",
                                "CATEGORY",
                                "MAIN_CLASS",
                                "SUB_CLASS",
                                "ABBREVIATION",
                                "INCHI_KEY",
                            )
                        },
                    }
                )
    return rows


def annotate_lipids(data, database, database_identity, parameters, rules):
    rules = validate_rules(rules, ADDUCTS)
    ids, mz, values, samples, layer, identity = dataset_inputs(data, parameters["intensity_layer"])
    rows = rank_candidates(mass_candidates(database, ids, mz, parameters, database_identity), rules)
    relations, diagnostics = isotope_evidence(rows, mz, ids, values, samples, parameters)
    import pyopenms

    return {
        "schema_version": 1,
        "input_identity": identity,
        "intensity_layer": layer,
        "database": database_identity,
        "parameters": parameters,
        "rules": rules,
        "candidates": rows,
        "relations": relations,
        "diagnostics": diagnostics,
        "selected": {},
        "reviewed_features": [],
        "pyopenms_version": pyopenms.__version__,
        "distribution_probability_tail": 1e-6,
    }


def annotation_store(data):
    value = json.loads(data.uns.get(STORAGE_KEY, '{"schema_version":1,"active":"","versions":[]}'))
    if value.get("schema_version") != 1:
        raise ValueError("不支持的注释版本格式。")
    return value


def version_valid(data, version):
    try:
        return dataset_inputs(data, version["intensity_layer"])[-1] == version["input_identity"]
    except (ValueError, KeyError):
        return False


def filtered_candidates(version, filters):
    rows = version["candidates"]
    query = filters.get("query", "").casefold()
    fields = {"category": "CATEGORY", "main_class": "MAIN_CLASS", "sub_class": "SUB_CLASS"}
    rows = [
        row
        for row in rows
        if (not query or query in " ".join(str(v) for v in row.values()).casefold())
        and all(
            not filters.get(key) or filters[key].casefold() in class_values_for_filter(row, field)
            for key, field in fields.items()
        )
    ]
    if filters.get("candidates") == "top":
        rows = [
            row
            for row in rows
            if (
                row["candidate_id"] in version["selected"][row["feature_id"]]
                if row["feature_id"] in version["selected"]
                else row["top_ranked"]
            )
        ]
    elif filters.get("candidates") == "manual":
        rows = [
            row
            for row in rows
            if row["candidate_id"] in version["selected"].get(row["feature_id"], [])
        ]
    selected_adducts = filters.get("adducts", [])
    if selected_adducts:
        rows = [row for row in rows if row["adduct"] in selected_adducts]
    return rows


def class_values_for_filter(row, field):
    from .lipid_rules import class_values

    return class_values(row, field)


def isotope_feature_ids(version, review="all"):
    return {
        row["isotope_feature_id"]
        for row in version["relations"]
        if row["review"] != "rejected"
        and ((row["matched"] and review == "all") or row["review"] == "accepted")
    }


def filtered_feature_ids(data, version, filters):
    rows = filtered_candidates(version, filters)
    ids = {row["feature_id"] for row in rows}
    annotated = {row["feature_id"] for row in version["candidates"]}
    if filters.get("include_unannotated", True):
        query = filters.get("query", "").casefold()
        ids.update(
            str(f)
            for f in set(data.var_names) - annotated
            if not query or query in str(f).casefold()
        )
    isotope_ids = isotope_feature_ids(version, filters.get("review", "all"))
    if filters.get("isotopes") == "hide":
        ids -= isotope_ids
    elif filters.get("isotopes") == "only":
        ids &= isotope_ids
    if filters.get("adduct_mode") == "strongest":
        _, _, values, samples, _, _ = dataset_inputs(data, version["intensity_layer"])
        sample_means = np.vstack(
            [values[samples == sample].mean(axis=0) for sample in dict.fromkeys(samples)]
        )
        strengths = dict(zip(data.var_names, sample_means.mean(axis=0), strict=True))
        groups = {}
        # Ambiguous features are only grouped when their complete selected ID set agrees.
        identities = {}
        for row in rows:
            if row["feature_id"] in ids:
                identities.setdefault(row["feature_id"], set()).add(row["database_id"])
        for feature, candidates in identities.items():
            groups.setdefault(tuple(sorted(candidates)), []).append(feature)
        for features in groups.values():
            winner = max(features, key=lambda f: (strengths[f], str(f)))
            ids.difference_update(set(features) - {winner})
    return [str(feature) for feature in data.var_names if feature in ids]
