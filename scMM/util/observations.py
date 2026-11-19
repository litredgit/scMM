"""Read the declared observation unit without inferring biological replication."""

import json


def observation_kind(data):
    """Existing cell datasets default to cell; module imports declare cell or sample."""
    encoded = data.uns.get("scmm_exchange_json")
    if encoded is None:
        return "cell"
    try:
        metadata = json.loads(encoded)
        if (
            not isinstance(metadata, dict)
            or type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != 1
        ):
            raise ValueError
        kind = metadata.get("observation_kind", "cell")
        if kind not in {"cell", "sample"}:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid declared observation unit") from exc
    return kind
