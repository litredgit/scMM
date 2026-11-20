"""Indexed MS1 lipid candidates and immutable annotation-version identities."""
# ruff: noqa: RUF001

import hashlib
import json

import numpy as np

from .intensity import intensity_states
from .lipid_evidence import ms2_status
from .lipid_isotopes import ADDUCTS, adduct_shift, isotope_evidence
from .lipid_rules import rank_candidates, validate_rules

STORAGE_KEY = "scmm_lipid_annotations_json"
REFERENCE_ION_FIELDS = (
    "source_row",
    "source_observed_mz",
    "source_adduct",
    "source_ppm_error",
    "source_annotation_level",
    "source_msi_level",
    "source_formula_ppm_error",
    "source_formula_conflict",
)


def feature_only(data):
    exchange = json.loads(data.uns.get("scmm_exchange_json", "{}"))
    return (
        data.n_obs == 0
        and exchange.get("kind") == "feature_only"
        and exchange.get("quantitation_available") is False
    )


def validate_intensity_layer(data, layer):
    if layer == "feature_snr":
        raise ValueError("SNR 不是强度，不能用作同位素比例来源。")
    if intensity_states(data).get(layer or "X", "unknown") != "raw":
        raise ValueError("所选强度已变换或来源未知，请选择有未归一化、未插补溯源的原始强度层。")


def feature_axis(data):
    context = json.loads(data.uns.get("scmm_analysis_input_json", "{}"))
    if context.get("variable_kind") == "empirical_compound":
        raise ValueError("EC 中性质量不是 m/z；请选择 Feature 视图或通用化合物候选搜索。")
    feature_ids = data.var_names.astype(str).tolist()
    mz = np.asarray(data.var.get("mz", data.var_names), dtype=float)
    if not np.isfinite(mz).all() or (mz <= 0).any() or not data.var_names.is_unique:
        raise ValueError("注释需要唯一特征 ID 和正的有限 m/z；允许不同 ID 对应相同 m/z。")
    return feature_ids, mz


def feature_samples(data):
    group_key = next((key for key in ("sample_id", "sample", "source_file") if key in data.obs), "")
    return (
        data.obs[group_key].astype("string").fillna("未分组").to_numpy(dtype=str)
        if group_key
        else np.repeat("单样本", data.n_obs)
    )


def dataset_inputs(data, layer="", *, mass_only=False):
    feature_ids, mz = feature_axis(data)
    if feature_only(data):
        layer = ""
    elif not mass_only:
        layer = layer or data.uns.get("scmm_workbench", {}).get("original_layer", "")
    if layer not in {"", "X"} and layer not in data.layers:
        raise ValueError("所选强度层不存在，请重新选择。")
    if not feature_only(data) and not mass_only:
        validate_intensity_layer(data, layer)
    matrix = data.X if layer in {"", "X"} else data.layers[layer]
    values = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    if not np.isfinite(values).all():
        raise ValueError("注释展示需要有限矩阵数值。")
    if not mass_only and (values < 0).any():
        raise ValueError("同位素检测需要有限、非负的未变换强度，请选择原始强度层。")
    samples = feature_samples(data)
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
    from .lipid_names import record_species

    masses = database["EXACT_MASS"].to_numpy(dtype=float)
    records = database.to_dict(orient="records")
    record_indices = np.arange(len(records))
    reference_adducts = (
        database["reference_adduct"].to_numpy() if "reference_adduct" in database else None
    )
    rows = []
    for adduct in parameters["adducts"]:
        spec = ADDUCTS[adduct]
        if parameters["polarity"] != "both" and spec["polarity"] != parameters["polarity"]:
            raise ValueError("所选加合物与搜索极性不一致。")
        shift = adduct_shift(adduct)
        indices = record_indices
        theoretical_mz = masses + shift
        if reference_adducts is not None:
            reference = reference_adducts == adduct
            theoretical_mz[reference] = database.loc[reference, "reference_mz"].to_numpy(
                dtype=float
            )
            eligible = record_indices[(reference_adducts == "") | reference]
            indices = eligible[np.argsort(theoretical_mz[eligible], kind="stable")]
        indexed_mz = theoretical_mz[indices]
        ppm = parameters["annotation_ppm"] * 1e-6
        for feature_id, query in zip(feature_ids, mz, strict=True):
            # Query-relative bounds are converted back to theoretical-relative ppm bounds.
            low, high = query / (1 + ppm), query / (1 - ppm)
            start, end = np.searchsorted(
                indexed_mz, [np.nextafter(low, -np.inf), np.nextafter(high, np.inf)]
            )
            for index in indices[start:end]:
                record = records[index]
                source_sha256 = record.get("database_sha256", database_identity["sha256"])
                source_record_id = record.get("database_record_id", record["record_id"])
                theoretical = theoretical_mz[index]
                error = (query - theoretical) / theoretical * 1e6
                if abs(error) > np.nextafter(parameters["annotation_ppm"], np.inf):
                    continue
                identity = json.dumps([source_sha256, feature_id, source_record_id, adduct])
                candidate = {
                    "candidate_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                    "feature_id": feature_id,
                    "query_mz": float(query),
                    "database_id": record["record_id"],
                    "database_record_id": source_record_id,
                    "name": str(record["COMMON_NAME"]),
                    "species": record_species(record),
                    "formula": str(record["FORMULA"]),
                    "adduct": adduct,
                    "polarity": spec["polarity"],
                    "theoretical_mz": float(theoretical),
                    "ppm_error": float(error),
                    "abs_ppm_error": float(abs(error)),
                    "database_sha256": source_sha256,
                    "database_source": record.get(
                        "database_source", database_identity.get("source", "local")
                    ),
                    "database_filename": record.get(
                        "database_filename", database_identity.get("filename", "")
                    ),
                    "ms2_status": ms2_status(record),
                    "source_ms2_status": record.get("ms2_status", "not_supplied"),
                    "ms2_evidence": record.get("ms2_evidence", []),
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
                if record.get("reference_adduct"):
                    candidate.update({key: record[key] for key in REFERENCE_ION_FIELDS})
                rows.append(candidate)
    return rows


def annotate_lipids(data, database, database_identity, parameters, rules):
    rules = validate_rules(rules, ADDUCTS)
    mass_only = feature_only(data) or parameters.get("mass_only", False)
    parameters = {**parameters, "mass_only": mass_only}
    if not mass_only and (
        parameters.get("resolution") is None
        or not np.isfinite(parameters["resolution"])
        or parameters["resolution"] <= 0
    ):
        raise ValueError("同位素计算需要明确提供正的采集分辨率。")
    ids, mz, values, samples, layer, identity = dataset_inputs(
        data, parameters["intensity_layer"], mass_only=mass_only
    )
    rows = rank_candidates(mass_candidates(database, ids, mz, parameters, database_identity), rules)
    if mass_only:
        relations, diagnostics = (
            [],
            [
                {
                    "message": "仅精确质量候选模式：不计算同位素比例或相关网络。",
                    "kind": "mass_only",
                }
            ],
        )
    else:
        relations, diagnostics = isotope_evidence(rows, mz, ids, values, samples, parameters)
    import pyopenms

    version = {
        "schema_version": 1,
        "input_identity": identity,
        "intensity_layer": layer,
        "mass_only": mass_only,
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
        "review_revision": 0,
        "annotation_names": {},
        "linked_annotations": {},
        "audit": [],
        "review_conflicts": [],
    }
    from .lipid_spectrum import make_adduct_relations

    version["adduct_relations"] = make_adduct_relations(rows)
    from .lipid_network import apply_support, build_network, intensity_layers

    if mass_only:
        return version
    if (layer or "X") not in intensity_layers(data)["raw"]:
        raise ValueError("辅助注释需要有未变换、未插补溯源的原始强度层。")
    version["network"] = build_network(data, version, values, ids, samples)
    apply_support(version)
    rank_candidates(rows, rules)
    return version


def annotation_store(data):
    value = json.loads(data.uns.get(STORAGE_KEY, '{"schema_version":1,"active":"","versions":[]}'))
    if value.get("schema_version") != 1:
        raise ValueError("不支持的注释版本格式。")
    return value


def version_valid(data, version):
    try:
        inputs = dataset_inputs(
            data, version["intensity_layer"], mass_only=version.get("mass_only", False)
        )
        if inputs[-1] != version["input_identity"]:
            return False
        if "network" in version:
            from .lipid_network import network_inputs

            identity = network_inputs(
                data, inputs[2], inputs[3], version["network"]["parameters"], inputs[4]
            )[-1]
            return identity == version["network"]["input_identity"]
        return True
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
        if version.get("mass_only", False):
            raise ValueError("仅精确质量候选模式未建立原始强度证据，请选择全部或指定加合物。")
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
