"""Bounded local compound/evidence ingestion from authorized storage roots."""

import csv
import hashlib
import io
import json

from scMM.ion.annotation import build_compound_index
from scMM.ion.evidence import normalize_evidence, parse_text_spectra
from scMM.util.annotation import parse_sdf_record


def read_local_text(storage, label, selected_path, *, max_bytes=500_000_000):
    path = storage.resolve(label, selected_path)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("local import is not a file or exceeds configured size budget")
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("local import exceeds configured size budget")
    return content.decode("utf-8-sig", errors="strict"), {
        "filename": path.name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def table_records(text, *, delimiter):
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = reader.fieldnames
    if not fields or len(fields) != len(set(fields)) or any(not field for field in fields):
        raise ValueError("table columns must be nonempty and unique")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("table row has missing or extra columns")
    return rows


def load_compound_database(
    storage,
    label,
    selected_path,
    *,
    namespace,
    field_mapping=None,
    max_bytes=500_000_000,
    formula_mass_ppm=1.0,
):
    text, source = read_local_text(storage, label, selected_path, max_bytes=max_bytes)
    suffix = source["filename"].rsplit(".", 1)[-1].lower()
    if suffix == "sdf":
        if not text.rstrip().endswith("$$$$"):
            raise ValueError("SDF final record is incomplete")
        records = [parse_sdf_record(block.strip()) for block in text.split("$$$$") if block.strip()]
        mapping = field_mapping or {
            "record_id": "LM_ID",
            "name": "COMMON_NAME",
            "formula": "FORMULA",
            "exact_mass": "EXACT_MASS",
        }
        rows = [
            {
                **record,
                **{canonical: record.get(original, "") for canonical, original in mapping.items()},
            }
            for record in records
        ]
    elif suffix in {"csv", "tsv"}:
        records = table_records(text, delimiter="\t" if suffix == "tsv" else ",")
        rows = (
            [
                {
                    canonical: record.get(original, "")
                    for canonical, original in field_mapping.items()
                }
                for record in records
            ]
            if field_mapping
            else records
        )
    else:
        raise ValueError("compound databases must use CSV, TSV or SDF")
    for row in rows:
        if row.get("namespace") and row["namespace"] != namespace:
            raise ValueError("record namespace conflicts with selected database namespace")
        row["namespace"] = namespace
    return build_compound_index(
        rows,
        source={**source, "kind": "local_compound_database", "namespace": namespace},
        formula_mass_ppm=formula_mass_ppm,
    )


def load_external_evidence(storage, label, selected_path, *, max_bytes=10_000_000):
    text, source = read_local_text(storage, label, selected_path, max_bytes=max_bytes)
    suffix = source["filename"].rsplit(".", 1)[-1].lower()
    if suffix == "json":
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("evidence JSON must contain a record list")
    elif suffix in {"csv", "tsv"}:
        rows = table_records(text, delimiter="\t" if suffix == "tsv" else ",")
        for row in rows:
            for key in ("target", "scope", "metadata", "peaks"):
                if row.get(key):
                    row[key] = json.loads(row[key])
    elif suffix in {"mgf", "msp"}:
        rows = [
            {"kind": "bulk_msms", "target": {"kind": "unmapped"}, "scope": {}, **spectrum}
            for spectrum in parse_text_spectra(text, format=suffix)
        ]
    else:
        raise ValueError("unsupported evidence format")
    return normalize_evidence(rows, source={**source, "kind": "local_evidence"})
