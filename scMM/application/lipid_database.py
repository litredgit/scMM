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
    return {"directory": str(root), "files": files, "available": bool(files), "source": LMSD_URL}


def _read_database(path):
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
    frame["EXACT_MASS"] = pd.to_numeric(frame["EXACT_MASS"], errors="coerce")
    invalid = ~np.isfinite(frame["EXACT_MASS"]) | (frame["EXACT_MASS"] <= 0)
    frame = frame.loc[~invalid].copy().fillna("")
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
    frame["record_id"] = [str(v) if v else f"record-{i}" for i, v in enumerate(frame["LM_ID"])]
    if frame["record_id"].duplicated().any():
        raise ValueError("数据库存在重复物质 ID。")
    frame = frame.sort_values("EXACT_MASS", kind="stable").reset_index(drop=True)
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
        filename = filename or files[-1]["filename"]
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


def prepare_database():
    root = database_root()
    root.mkdir(parents=True, exist_ok=True)
    with _LOCK, project_lock(root):
        if database_status()["available"]:
            _, identity = load_database()
            return identity
        with TemporaryDirectory(prefix=".download-", dir=root) as temporary:
            directory = Path(temporary)
            archive = directory / "download.zip"
            request = urllib.request.Request(
                LMSD_URL, headers={"User-Agent": "scMM/0.2 lipid annotation"}
            )
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                archive.open("xb") as handle,
            ):
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > 128 * 1024 * 1024:
                        raise ValueError("数据库下载超过 128 MiB 限制。")
                    handle.write(block)
            try:
                with zipfile.ZipFile(archive) as zipped:
                    entries = [v for v in zipped.infolist() if v.filename.lower().endswith(".sdf")]
                    if len(entries) != 1 or entries[0].file_size > 1024**3:
                        raise ValueError("数据库压缩包需包含一个不超过 1 GiB 的 SDF。")
                    sdf = directory / "database.sdf"
                    with zipped.open(entries[0]) as source, sdf.open("xb") as target:
                        shutil.copyfileobj(source, target)
            except zipfile.BadZipFile as exc:
                raise ValueError("数据库压缩包损坏，请重新准备数据库。") from exc
            _read_database(sdf)
            digest = file_digest(sdf)
            target = root / f"LMSD_{digest[:16]}.sdf"
            metadata = {
                "source": LMSD_URL,
                "downloaded_at": datetime.now(UTC).isoformat(),
                "sha256": digest,
                "license": "CC BY 4.0",
                "archive_member": entries[0].filename,
            }
            write_json(target.with_suffix(".json"), metadata)
            os.replace(sdf, target)
        return load_database(target.name)[1]
