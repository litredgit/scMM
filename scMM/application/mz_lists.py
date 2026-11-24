"""Versioned ion m/z lists for targeted extraction."""
# ruff: noqa: RUF001

import csv
import hashlib
import io
import math
from functools import lru_cache
from pathlib import PurePath

import numpy as np

from scMM.util.lipid_isotopes import ADDUCTS, adduct_shift

from .lipid_database import BUILTIN_DATABASES, load_database

MAX_TARGETS = 20_000


def _digest(masses):
    return hashlib.sha256(np.asarray(masses, dtype="<f8").tobytes()).hexdigest()


def _record(identifier, name, masses, origin):
    values = sorted(set(masses))
    if not values or len(values) > MAX_TARGETS:
        raise ValueError(f"清单须包含 1–{MAX_TARGETS} 个不同的 m/z。")
    if any(not math.isfinite(mz) or mz <= 0 for mz in values):
        raise ValueError("m/z 须为有限正数。")
    return {
        "id": identifier,
        "name": name,
        "sha256": _digest(values),
        "origin": origin,
        "mz": values,
    }


@lru_cache(maxsize=len(BUILTIN_DATABASES))
def _preset(identifier):
    frame, source = load_database(identifier)
    ions = []
    for row in frame.to_dict(orient="records"):
        if "reference_mz" in row:
            ions.append((row["reference_mz"], row["reference_adduct"], row["record_id"]))
            continue
        for observation in row["source_observations"]:
            adduct = observation["adduct"]
            if adduct in ADDUCTS and observation["charge"] == ADDUCTS[adduct]["charge"]:
                mz = (row["EXACT_MASS"] + adduct_shift(adduct)) / abs(observation["charge"])
                ions.append((mz, adduct, row["record_id"]))
    return _record(
        identifier,
        source["label"],
        (mz for mz, _, _ in ions),
        {
            "type": "database",
            "database_sha256": source["sha256"],
            "adducts": sorted({adduct for _, adduct, _ in ions}),
            "ions": sorted(set(ions)),
        },
    )


def summary(record):
    origin = {key: value for key, value in record["origin"].items() if key != "ions"}
    return {
        "id": record["id"],
        "name": record["name"],
        "sha256": record["sha256"],
        "count": len(record["mz"]),
        "origin": origin,
    }


def catalog(project):
    return [
        *[summary(_preset(identifier)) for identifier in BUILTIN_DATABASES],
        *map(summary, project.manifest.get("mz_lists", {}).values()),
    ]


def resolve(project, identifier):
    if identifier in BUILTIN_DATABASES:
        return _preset(identifier)
    record = project.manifest.get("mz_lists", {}).get(identifier)
    if record is None:
        raise ValueError("请选择当前项目中可用的 m/z 清单。")
    if _digest(record["mz"]) != record["sha256"]:
        raise ValueError("项目 m/z 清单摘要不一致。")
    return record


def snapshot(project):
    return resolve(project, project.manifest.get("feature_list_id"))


def effective_masses(record, params):
    targets = np.asarray(record["mz"], dtype=np.float64)
    selected = targets[(targets >= params.mz_min) & (targets <= params.mz_max)]
    if not selected.size:
        raise ValueError("所选 m/z 清单在当前提取范围内没有目标。")
    return selected


def reference_alignment(params, references=None, ppm=None):
    if references is None:
        references = params.reference_mz
    if not np.size(references):
        references = (params.ref_mz,)
    return np.atleast_1d(references), params.reference_ppm_tol if ppm is None else ppm


def parse(text):
    """Accept one numeric column or a CSV/TSV with a named m/z column."""
    clean = text.lstrip("\ufeff").strip()
    first = clean.splitlines()[0] if clean else ""
    delimiter = "\t" if "\t" in first else ","
    rows = csv.reader(io.StringIO(clean, newline=""), delimiter=delimiter, strict=True)
    result = []
    try:
        header = next(rows, [])
        keys = [key.strip().lower().replace(" ", "") for key in header]
        columns = [i for i, key in enumerate(keys) if key in {"mz", "m/z", "m_z", "m.z"}]
        if len(columns) > 1 or (not columns and len(header) != 1):
            raise ValueError("请使用单列 m/z 值，或提供一个明确的 mz / m/z 表头。")
        column = columns[0] if columns else 0
        if not columns:
            rows = csv.reader(io.StringIO(clean, newline=""), delimiter=delimiter, strict=True)
        for row in rows:
            if not row or not any(value.strip() for value in row):
                continue
            try:
                if len(row) != len(header):
                    raise ValueError
                mz = float(row[column])
                if not math.isfinite(mz) or mz <= 0:
                    raise ValueError
            except ValueError as exc:
                raise ValueError(f"第 {rows.line_num} 行需要一个有限正数 m/z。") from exc
            result.append(mz)
    except csv.Error as exc:
        raise ValueError(f"第 {rows.line_num} 行的 CSV / TSV 格式无效。") from exc
    return result


def add(project, name, masses, origin):
    name = name.strip()
    if not name:
        raise ValueError("请输入清单名称。")
    record = _record("", name, masses, origin)
    lists = project.manifest.setdefault("mz_lists", {})
    for existing in lists.values():
        if all(existing[key] == record[key] for key in ("name", "sha256", "origin")):
            return summary(existing)
    from uuid import uuid4

    record["id"] = uuid4().hex
    lists[record["id"]] = record
    project.dirty = True
    return summary(record)


def imported(project, filename, name, text):
    filename = PurePath(filename.replace("\\", "/")).name
    return add(
        project,
        name or filename,
        parse(text),
        {
            "type": "upload",
            "filename": filename,
            "file_sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
    )
