"""MS/MS availability is distinct from a match bound to current measured input."""

import numpy as np


def ms2_status(record, *, input_identity=None):
    evidence = record.get("ms2_evidence", [])
    supplied = record.get("source_ms2_status", record.get("ms2_status", "not_supplied"))
    if not isinstance(evidence, list):
        return "unknown"
    matches = []
    available = False
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if input_identity and (
            item.get("kind") == "measured_msms_match"
            and item.get("input_identity") == input_identity
            and item.get("feature_id") == record.get("feature_id")
            and item.get("database_sha256") == record.get("database_sha256")
            and item.get("database_record_id") == record.get("database_record_id")
            and item.get("measured_sha256")
            and item.get("reference_sha256")
            and type(item.get("passes_threshold")) is bool
        ):
            matches.append(item["passes_threshold"])
        if item.get("kind") == "reference_msms_spectrum":
            try:
                peaks = np.asarray(item.get("peaks", []), dtype=float)
                available |= bool(
                    peaks.ndim == 2
                    and peaks.shape[1] == 2
                    and len(peaks)
                    and np.isfinite(peaks).all()
                    and (peaks[:, 0] > 0).all()
                    and (peaks[:, 1] >= 0).all()
                    and peaks[:, 1].sum() > 0
                )
            except (TypeError, ValueError):
                pass
    if matches:
        return "matched" if any(matches) else "no_match"
    if available:
        return "available"
    if supplied == "not_supplied" and not evidence:
        return "not_supplied"
    return "unknown"
