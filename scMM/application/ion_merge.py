"""Explicit EC alignment, preserving response assumptions and structural missingness."""

import json

import numpy as np
import pandas as pd
from anndata import AnnData

from scMM.ion.identity import dataset_identity, json_identity
from scMM.ion.semantics import unknown_state, value_states, write_value_states


def merge_compound_sources(sources, alignments):
    """Unmapped ECs remain separate; matching mass/name never creates an alignment."""
    if len(sources) < 2:
        raise ValueError("at least two compound sources required")
    source_ids = [source["source_id"] for source in sources]
    identities = [(source["root_id"], source["view_id"]) for source in sources]
    if len(set(source_ids)) != len(sources) or len(set(identities)) != len(sources):
        raise ValueError("duplicate compound source")
    known = {source["source_id"]: source for source in sources}
    mapping, definitions = {}, {}
    for row in alignments:
        source = known[row["source_id"]]
        variable = row["ec_id"]
        target = row["target_ec_id"]
        if not target or not row.get("response_comparable") or not row.get("reason", "").strip():
            raise ValueError("EC alignment requires explicit response comparability and reason")
        if variable not in source["data"].var_names or (row["source_id"], variable) in mapping:
            raise ValueError("unknown or multiply aligned EC")
        raw_role = source["data"].var.loc[variable].get("ion_role")
        role = json.loads(raw_role) if isinstance(raw_role, str) else raw_role
        if not isinstance(role, dict) or not role.get("species_id") or role.get("oligomer") != 1:
            raise ValueError("comparable fixed monomer quantifier metadata required")
        signature = (role["species_id"], role["charge"], role.get("isotope_shift"))
        if target in definitions and definitions[target] != signature:
            raise ValueError("different response systems require an unsupported calibration model")
        definitions[target] = signature
        mapping[(row["source_id"], variable)] = target
    variable_ids, origins, frames = [], {}, []
    for source in sources:
        data, key = source["data"], source["source_id"]
        if data.uns.get("scmm_variable_kind") != "empirical_compound":
            raise ValueError("feature/compound mixed merge is not supported")
        if value_states(data)["X"]["space"] != "linear_abundance":
            raise ValueError("compound merge requires a linear source view")
        targets = [
            mapping.get((key, str(variable)), f"{key}:{variable}") for variable in data.var_names
        ]
        if len(targets) != len(set(targets)):
            raise ValueError("one source cannot count multiple ECs into a single output")
        for variable, target in zip(data.var_names, targets, strict=True):
            if target not in origins:
                variable_ids.append(target)
                origins[target] = []
            origins[target].append(
                {
                    "source_id": key,
                    "root_id": source["root_id"],
                    "view_id": source["view_id"],
                    "ec_id": str(variable),
                    "quantifier_feature_id": str(
                        data.var.loc[variable].get("quantifier_feature_id", "")
                    ),
                }
            )
        obs = data.obs.copy()
        obs["merge_source_id"] = key
        obs["merge_original_cell_id"] = data.obs_names.astype(str)
        obs.index = [f"{key}:{value}" for value in data.obs_names]
        frames.append(obs)
    if len(set(index for frame in frames for index in frame.index)) != sum(
        len(frame) for frame in frames
    ):
        raise ValueError("namespaced merged cell IDs collide")
    output = np.full((sum(source["data"].n_obs for source in sources), len(variable_ids)), np.nan)
    availability = np.zeros(output.shape, dtype=bool)
    columns = {key: i for i, key in enumerate(variable_ids)}
    offset = 0
    for source in sources:
        data, key = source["data"], source["source_id"]
        values = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
        mask = data.layers["scmm_quantifiable"]
        mask = mask.toarray() if hasattr(mask, "toarray") else np.asarray(mask)
        if (
            mask.dtype.kind != "b"
            or np.isinf(values).any()
            or not np.array_equal(~mask, np.isnan(values))
        ):
            raise ValueError("source availability is inconsistent")
        for position, variable in enumerate(data.var_names):
            target = mapping.get((key, str(variable)), f"{key}:{variable}")
            column = columns[target]
            output[offset : offset + data.n_obs, column] = values[:, position]
            availability[offset : offset + data.n_obs, column] = mask[:, position]
        offset += data.n_obs
    var = pd.DataFrame(
        {
            "source_quantifiers": [
                json.dumps(origins[key], ensure_ascii=False) for key in variable_ids
            ]
        },
        index=variable_ids,
    )
    merged = AnnData(output, obs=pd.concat(frames), var=var)
    merged.layers["scmm_quantifiable"] = availability
    merged.uns["scmm_variable_kind"] = "empirical_compound"
    write_value_states(
        merged,
        {
            "X": {**unknown_state(), "space": "linear_abundance"},
            "scmm_quantifiable": unknown_state(),
        },
    )
    provenance = {
        "schema_version": 1,
        "source_identities": {
            s["source_id"]: dataset_identity(s["data"], allow_missing=True) for s in sources
        },
        "alignments": alignments,
        "mapping": origins,
    }
    provenance["merge_id"] = json_identity(provenance)
    merged.uns["scmm_compound_merge_json"] = json.dumps(
        provenance, ensure_ascii=False, allow_nan=False
    )
    return merged, provenance
