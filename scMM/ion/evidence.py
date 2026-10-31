"""Scoped external assertions and restricted text spectra; no automatic MS/MS search."""

import re
from copy import deepcopy

import numpy as np

from .identity import json_identity

KINDS = {"blank", "standard", "bulk_msms", "experience", "literature", "user_review", "tracer"}


def normalize_evidence(records, *, source):
    """Validate whole candidate import before any application state is changed."""
    json_identity(source)
    result, seen = [], set()
    for record in records:
        row = deepcopy(dict(record))
        if row.get("kind") not in KINDS or not isinstance(row.get("scope"), dict):
            raise ValueError("evidence kind and explicit scope are required")
        target = row.get("target", {})
        if not isinstance(target, dict) or target.get("kind") not in {
            "feature",
            "ec",
            "candidate",
            "relation",
            "unmapped",
        }:
            raise ValueError("explicit evidence target kind required")
        if target["kind"] != "unmapped" and (not target.get("id") or not target.get("version")):
            raise ValueError("evidence target requires ID and version")
        spectrum = row.get("peaks", [])
        if spectrum:
            peaks = np.asarray(spectrum, dtype=float)
            if (
                peaks.ndim != 2
                or peaks.shape[1] != 2
                or not np.isfinite(peaks).all()
                or (peaks[:, 0] <= 0).any()
                or (peaks[:, 1] < 0).any()
            ):
                raise ValueError("invalid evidence peak table")
            row["peaks"] = peaks[np.argsort(peaks[:, 0], kind="stable")].tolist()
        row["scope_status"] = "declared" if row["scope"] else "unknown"
        if row["kind"] == "bulk_msms":
            metadata = row.setdefault("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("MS/MS metadata must be a mapping")
            for alias in ("precursormz", "precursor m/z"):
                if metadata.get(alias) and "precursor_mz" not in metadata:
                    metadata["precursor_mz"] = float(metadata[alias])
            if metadata.get("pepmass") and "precursor_mz" not in metadata:
                metadata["precursor_mz"] = float(str(metadata["pepmass"]).split()[0])
            for key in (
                "precursor_mz",
                "charge",
                "polarity",
                "adduct",
                "isolation_window",
                "collision_energy",
                "instrument",
                "sample_pool",
            ):
                metadata.setdefault(key, None)
            for key in (
                "precursor_mz",
                "charge",
                "polarity",
                "adduct",
                "isolation_window",
                "collision_energy",
                "instrument",
                "sample_pool",
            ):
                if isinstance(metadata[key], str) and metadata[key].strip().lower() in {
                    "",
                    "unknown",
                    "na",
                    "n/a",
                }:
                    metadata[key] = None
            if metadata["precursor_mz"] is not None:
                metadata["precursor_mz"] = float(metadata["precursor_mz"])
                if not np.isfinite(metadata["precursor_mz"]) or metadata["precursor_mz"] <= 0:
                    raise ValueError("invalid MS/MS precursor mass")
            if metadata["charge"] is not None and isinstance(metadata["charge"], str):
                match = re.fullmatch(r"([1-9][0-9]*)([+-])", metadata["charge"].strip())
                if match:
                    metadata["source_charge"] = metadata["charge"]
                    metadata["charge"] = int(match[1]) * (1 if match[2] == "+" else -1)
            row["limitations"] = [key for key, value in metadata.items() if value is None]
            row["transfer_scope"] = "specified_pool_not_individual_cell_identity"
        row["source"] = deepcopy(source)
        row["mapping_status"] = "unmatched" if target["kind"] == "unmapped" else "requires_review"
        row["review"] = "pending"
        identity = json_identity(row)
        if identity in seen:
            raise ValueError("duplicate evidence record")
        seen.add(identity)
        result.append({"evidence_id": identity, **row})
    return result


def parse_text_spectra(content, *, format):
    """Parse only MGF/MSP metadata and peaks, without interpreting executable content."""
    if format not in {"mgf", "msp"}:
        raise ValueError("supported spectrum formats are mgf and msp")
    if not isinstance(content, str) or len(content) > 10_000_000:
        raise ValueError("invalid or oversized spectrum text")
    spectra, current, declared = [], None, None
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if format == "mgf" and line.upper() == "BEGIN IONS":
            if current is not None:
                raise ValueError("nested MGF spectrum")
            current = {"metadata": {}, "peaks": []}
            continue
        if format == "mgf" and line.upper() == "END IONS":
            if current is None:
                raise ValueError("unmatched MGF terminator")
            spectra.append(current)
            current = None
            continue
        if format == "msp" and line.lower().startswith("name:"):
            if current is not None:
                if declared is not None and len(current["peaks"]) != declared:
                    raise ValueError("MSP peak count mismatch")
                spectra.append(current)
            current, declared = (
                {"metadata": {"title": line.split(":", 1)[1].strip()}, "peaks": []},
                None,
            )
            continue
        if current is None:
            raise ValueError("spectrum content outside a record")
        delimiter = "=" if format == "mgf" else ":"
        if delimiter in line and not line[0].isdigit():
            key, value = line.split(delimiter, 1)
            key = key.strip().lower()
            if key in current["metadata"]:
                raise ValueError("duplicate spectrum metadata field")
            current["metadata"][key] = value.strip()
            if key.replace(" ", "") == "numpeaks":
                declared = int(value)
            continue
        fields = line.replace("\t", " ").split()
        if len(fields) < 2:
            raise ValueError("invalid spectrum peak row")
        mz, intensity = map(float, fields[:2])
        if not np.isfinite([mz, intensity]).all() or mz <= 0 or intensity < 0:
            raise ValueError("invalid spectrum peak values")
        current["peaks"].append([mz, intensity])
    if current is not None:
        if format == "mgf":
            raise ValueError("unterminated MGF spectrum")
        if declared is not None and len(current["peaks"]) != declared:
            raise ValueError("MSP peak count mismatch")
        spectra.append(current)
    return spectra


def record_review(target, *, version, decision, reviewer, timestamp, reason, scope):
    """Application supplies authenticated reviewer and server timestamp."""
    if not isinstance(target, dict) or not version or not isinstance(scope, dict):
        raise ValueError("review requires explicit target, version and scope")
    if (
        decision not in {"accepted", "rejected", "pending"}
        or not reviewer
        or not timestamp
        or not reason.strip()
    ):
        raise ValueError("review requires decision, identity, time and reason")
    row = {
        "target": target,
        "version": version,
        "decision": decision,
        "reviewer": reviewer,
        "timestamp": timestamp,
        "reason": reason,
        "scope": scope,
    }
    return {"review_id": json_identity(row), **deepcopy(row)}


def identification_assertion(
    *, scheme, version, level, criteria, evidence_ids, scope, structure_level="unresolved"
):
    """Keep standards separate and retain claimed criteria; never infer a level from rank."""
    if (
        scheme not in {"MSI", "Schymanski", "LSI", "custom"}
        or not version
        or not isinstance(criteria, dict)
        or not scope
    ):
        raise ValueError("explicit reporting standard, criteria and scope required")
    return {
        "scheme": scheme,
        "scheme_version": version,
        "level": level,
        "criteria": deepcopy(criteria),
        "evidence_ids": list(evidence_ids),
        "scope": deepcopy(scope),
        "structure_level": structure_level,
        "assignment_origin": "explicit_assertion_requires_review",
        "criteria_verified": False,
    }


def link_external_evidence(records, targets, *, mapping=None, ppm=5.0):
    """Preview exact/versioned links; mass matches never silently choose a nearest target."""
    if not np.isfinite(ppm) or ppm < 0:
        raise ValueError("invalid evidence mapping tolerance")
    mapping = mapping or {}
    by_ref = {(row["kind"], row["id"], row["version"]): row for row in targets}
    if len(by_ref) != len(targets):
        raise ValueError("duplicate evidence target identity")
    links = []
    for record in records:
        supplied = mapping.get(record["evidence_id"])
        reference = record["target"]
        if supplied is not None:
            references = supplied
        elif reference["kind"] != "unmapped":
            references = [reference]
        else:
            observed = record.get("metadata", {}).get("precursor_mz")
            references = (
                [
                    {"kind": t["kind"], "id": t["id"], "version": t["version"]}
                    for t in targets
                    if observed is not None
                    and t.get("mz") is not None
                    and abs(float(observed) - t["mz"]) / t["mz"] * 1e6 <= ppm
                ]
                if observed is not None
                else []
            )
        valid, rejected = [], []
        for ref in references:
            target = by_ref.get((ref["kind"], ref["id"], ref["version"]))
            if target is None:
                rejected.append("unknown_or_stale_target")
                continue
            metadata = record.get("metadata", {})
            if (
                metadata.get("polarity")
                and target.get("polarity")
                and metadata["polarity"] != target["polarity"]
            ):
                rejected.append("polarity_conflict")
                continue
            samples = set(record["scope"].get("sample_ids", []))
            target_samples = set(target.get("sample_ids", []))
            if samples and target_samples and not samples & target_samples:
                rejected.append("sample_scope_conflict")
                continue
            valid.append(
                {
                    "target": deepcopy(ref),
                    "sample_ids": sorted(
                        samples & target_samples if samples and target_samples else samples
                    ),
                    "scope_verified": bool(samples and target_samples),
                    "transfer_scope": record.get("transfer_scope", "declared_scope_only"),
                }
            )
        status = (
            "matched"
            if len(valid) == 1
            else "ambiguous"
            if valid
            else "rejected"
            if rejected
            else "unmatched"
        )
        links.append(
            {
                "evidence_id": record["evidence_id"],
                "mapping_status": status,
                "links": valid,
                "rejected_reasons": rejected,
                "review": "pending",
            }
        )
    return links
