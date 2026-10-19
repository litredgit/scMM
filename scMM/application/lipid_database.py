"""Versioned local LMSD downloads and bounded, indexed SDF loading."""
# ruff: noqa: RUF001

import hashlib
import json
import os
import shutil
import threading
import urllib.request
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from scMM.util.annotation import parse_sdf_record

from .projects import project_lock, write_json

LMSD_URL = "https://lipidmaps.org/files/?ext=sdf.zip&file=LMSD"
DATABASE_ROOT = Path("~/data/results/databases/lipidmaps").expanduser()
_LOCK = threading.RLock()


def database_root():
    if os.environ.get("SCMM_SERVER_CONFIG_ACTIVE") == "1":
        configured = os.environ.get("SCMM_LIPID_DATABASE_DIR")
        if not configured:
            raise ValueError("未配置注释数据库目录，请由管理员设置 lipid_database_dir。")
        path = Path(configured).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise NotADirectoryError("注释数据库配置必须指向有效目录。")
        return path
    return (
        Path(os.environ.get("SCMM_LIPID_DATABASE_DIR", str(DATABASE_ROOT))).expanduser().resolve()
    )


def database_status():
    try:
        root = database_root()
    except (ValueError, OSError) as exc:
        # Browsing persisted annotations must not require the original optional database.
        return {
            "directory": os.environ.get("SCMM_LIPID_DATABASE_DIR", "未配置"),
            "files": [],
            "available": False,
            "source": LMSD_URL,
            "error": str(exc),
        }
    files = []
    if root.is_dir():
        for path in sorted(root.iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".sdf":
                files.append({"filename": path.name, "bytes": path.stat().st_size})
    provenance = root / "database_provenance.json"
    active = json.loads(provenance.read_text()) if provenance.is_file() else {}
    return {
        "directory": str(root),
        "files": files,
        "available": bool(files),
        "source": LMSD_URL,
        "active": active.get("filename", ""),
        "provenance": active,
    }


def _read_database(path, *, include_invalid=False):
    records, lines = [], []
    with path.open(encoding="utf-8-sig", errors="strict") as handle:
        for line in handle:
            if line.strip() == "$$$$":
                if lines:
                    records.append(parse_sdf_record("".join(lines)))
                lines = []
            else:
                lines.append(line)
    if any(line.strip() for line in lines):
        raise ValueError("SDF 末尾记录不完整，缺少 $$$$。")
    frame = pd.DataFrame(records)
    if "EXACT_MASS" not in frame or "FORMULA" not in frame:
        raise ValueError("数据库需要 EXACT_MASS 和 FORMULA 字段。")
    frame["source_record"] = np.arange(len(frame))
    frame["source_exact_mass"] = frame["EXACT_MASS"].fillna("")
    frame["EXACT_MASS"] = pd.to_numeric(frame["EXACT_MASS"], errors="coerce")
    invalid = ~np.isfinite(frame["EXACT_MASS"]) | (frame["EXACT_MASS"] <= 0)
    frame["valid_exact_mass"] = ~invalid
    frame = (frame if include_invalid else frame.loc[~invalid]).copy().fillna("")
    if frame.empty:
        raise ValueError("数据库没有有效的精确质量记录。")
    for key in (
        "LM_ID",
        "COMMON_NAME",
        "NAME",
        "ABBREVIATION",
        "CATEGORY",
        "MAIN_CLASS",
        "SUB_CLASS",
        "INCHI_KEY",
    ):
        if key not in frame:
            frame[key] = ""
    frame["COMMON_NAME"] = frame["COMMON_NAME"].where(frame["COMMON_NAME"].ne(""), frame["NAME"])
    frame["COMMON_NAME"] = frame["COMMON_NAME"].where(
        frame["COMMON_NAME"].ne(""), frame["record_title"]
    )
    frame["record_id"] = [
        str(v) if v else f"record-{i}"
        for i, v in zip(frame["source_record"], frame["LM_ID"], strict=True)
    ]
    if frame["record_id"].duplicated().any():
        raise ValueError("数据库存在重复物质 ID。")
    from scMM.util.lipid_names import record_species

    frame["species"] = [record_species(row) for row in frame.to_dict(orient="records")]
    if not include_invalid:
        frame = frame.sort_values("EXACT_MASS", kind="stable")
    frame = frame.reset_index(drop=True)
    return frame, int(invalid.sum())


def file_digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@lru_cache(maxsize=2)
def _load_cached(path, size, modified):
    path = Path(path)
    before = path.stat()
    frame, invalid = _read_database(path)
    digest = file_digest(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("数据库读取期间发生改变，请重试。")
    metadata = path.with_suffix(".json")
    source = json.loads(metadata.read_text()) if metadata.is_file() else {"source": "local"}
    return frame, {
        **source,
        "filename": path.name,
        "sha256": digest,
        "records": len(frame),
        "invalid_mass_records": invalid,
        "missing_formula_records": int(frame["FORMULA"].eq("").sum()),
    }


def load_database(filename=""):
    root = database_root()
    with _LOCK:
        files = database_status()["files"]
        if not files:
            raise FileNotFoundError("本地尚无脂质数据库，请先准备数据库。")
        filename = filename or database_status().get("active") or files[-1]["filename"]
        if (
            Path(filename).name != filename
            or "\\" in filename
            or not filename.lower().endswith(".sdf")
        ):
            raise ValueError("请选择数据库目录内的 SDF 文件。")
        path = root / filename
        if path.is_symlink() or path.resolve().parent != root:
            raise PermissionError("数据库路径不可越界或使用符号链接。")
        stat = path.stat()
        return _load_cached(str(path), stat.st_size, stat.st_mtime_ns)


def prepare_database(*, force=False, archive_path=None, expected_sha256=None):
    """Publish a complete validated version; keep every previous version available."""
    root = database_root()
    root.mkdir(parents=True, exist_ok=True)
    with _LOCK, project_lock(root):
        if database_status()["available"] and not force and archive_path is None:
            return load_database()[1]
        with TemporaryDirectory(prefix=".download-", dir=root) as temporary:
            directory = Path(temporary)
            archive = directory / "download.zip"
            if archive_path is not None:
                shutil.copyfile(archive_path, archive)
            else:
                request = urllib.request.Request(
                    LMSD_URL, headers={"User-Agent": "scMM LMSD database updater"}
                )
                with (
                    urllib.request.urlopen(request, timeout=60) as response,
                    archive.open("xb") as handle,
                ):
                    total = 0
                    while block := response.read(1024 * 1024):
                        total += len(block)
                        if total > 128 * 1024**2:
                            raise ValueError("Database archive exceeds 128 MiB")
                        handle.write(block)
            archive_digest = file_digest(archive)
            if expected_sha256 and archive_digest != expected_sha256:
                raise ValueError("Database archive SHA256 does not match the requested version")
            try:
                with zipfile.ZipFile(archive) as zipped:
                    entries = [
                        entry
                        for entry in zipped.infolist()
                        if entry.filename.lower().endswith(".sdf")
                    ]
                    if len(entries) != 1 or entries[0].file_size > 1024**3:
                        raise ValueError("Expected one SDF of at most 1 GiB")
                    sdf = directory / "database.sdf"
                    with zipped.open(entries[0]) as source, sdf.open("xb") as target:
                        shutil.copyfileobj(source, target)
            except zipfile.BadZipFile as exc:
                raise ValueError("数据库压缩包无效。") from exc
            full_frame, invalid = _read_database(sdf, include_invalid=True)
            frame = full_frame.loc[full_frame["valid_exact_mass"]].copy()
            digest = file_digest(sdf)
            target = root / f"LMSD_{digest[:16]}.sdf"
            derived = directory / "derived"
            derived.mkdir()
            metadata_path = derived / "LMSD_metadata.csv.gz"
            full_frame.to_csv(
                metadata_path, index=False, compression={"method": "gzip", "mtime": 0}
            )
            keys = ["FORMULA", "CATEGORY", "MAIN_CLASS", "species"]
            collapsed = (
                frame.groupby(keys, sort=True, dropna=False)
                .agg(
                    EXACT_MASS=("EXACT_MASS", "first"),
                    records=("record_id", "size"),
                    record_ids=("record_id", lambda values: json.dumps(list(values))),
                )
                .reset_index()
            )
            collapsed_path = derived / "LMSD_collapsed_formula_species.csv.gz"
            collapsed.to_csv(
                collapsed_path, index=False, compression={"method": "gzip", "mtime": 0}
            )
            version = (
                root
                / "versions"
                / f"{archive_digest[:16]}-{file_digest(metadata_path)[:12]}-{file_digest(collapsed_path)[:12]}"
            )
            version.parent.mkdir(exist_ok=True)
            now = datetime.now(UTC)
            archive_name = f"LMSD_download_{now:%Y%m%d}.sdf.zip"
            shutil.copyfile(archive, derived / archive_name)
            metadata = {
                "source": LMSD_URL,
                "source_url": LMSD_URL,
                "source_page": "https://lipidmaps.org/databases/lmsd/download",
                "retrieved_date": now.date().isoformat(),
                "downloaded_at": now.isoformat(),
                "download_bytes": archive.stat().st_size,
                "archive_sha256": archive_digest,
                "sha256": digest,
                "sdf_sha256": digest,
                "filename": target.name,
                "license": "CC BY 4.0; LIPID MAPS LMSD",
                "archive_member": entries[0].filename,
                "records": len(frame),
                "source_records": len(full_frame),
                "invalid_mass_records": invalid,
                "collapsed_records": len(collapsed),
                "version_directory": str(version.relative_to(root)),
                "files": {
                    path.name: {"sha256": file_digest(path), "bytes": path.stat().st_size}
                    for path in derived.iterdir()
                },
            }
            # The root provenance keeps the archive hash requested by the administrator.
            provenance = {**metadata, "sha256": archive_digest}
            write_json(derived / "database_provenance.json", provenance)
            if not version.exists():
                os.replace(derived, version)
            else:
                provenance = json.loads((version / "database_provenance.json").read_text())
                for name, info in provenance["files"].items():
                    if file_digest(version / name) != info["sha256"]:
                        raise ValueError("Existing derived version failed integrity verification")
                metadata = {**provenance, "sha256": digest}
            if not target.exists():
                os.replace(sdf, target)
            elif file_digest(target) != digest:
                raise ValueError("Existing database version failed integrity verification")
            write_json(target.with_suffix(".json"), metadata)
            # Publish the active pointer only after all SDF and derived files are complete.
            write_json(root / "database_provenance.json", provenance)
            _load_cached.cache_clear()
        return load_database(target.name)[1]
