#!/usr/bin/env python3
"""Read-only, redacted checks of source files, archives and reachable Git history.

Pattern checks are a reproducible guard, not proof that a repository contains no secrets.
Never print matching values. History inspection does not rewrite refs or delete objects.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "github_token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b",
    "aws_access_key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "slack_token": rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
    "credential_url": rb"https?://[^\s/:\"<>]+:[^\s/@\"<>]+@",
    "literal_secret": rb"(?i)\b(?:password|passwd|api_key|secret_key|access_token|client_secret)[\"']?\s*[=:]\s*[\"'][^\"'\n]{12,}[\"']",
    "personal_home": rb"/(?:home|Users)/[A-Za-z0-9_.-]+/[^\s\"'<>]*",
    "private_ip": rb"(?<![\d.])(?:192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})(?![\d.])",
}
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


def findings(data, name, object_id=None):
    result = []
    if data.startswith(b"SQLite format 3\x00"):
        result.append({"kind": "database_file", "file": name})
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, data):
            result.append(
                {
                    "kind": kind,
                    "file": name,
                    "line": data[: match.start()].count(b"\n") + 1,
                    **({"object": object_id} if object_id else {}),
                }
            )
    if name.endswith(".ipynb"):
        try:
            notebook = json.loads(data)
            if any(
                cell.get("outputs") or cell.get("execution_count") is not None
                for cell in notebook.get("cells", [])
                if cell.get("cell_type") == "code"
            ):
                result.append(
                    {
                        "kind": "notebook_output",
                        "file": name,
                        **({"object": object_id} if object_id else {}),
                    }
                )
        except (ValueError, TypeError):
            result.append({"kind": "invalid_notebook", "file": name})
    basename = Path(name).name
    if (
        basename in {".env", ".pypirc", "id_rsa", "id_ed25519"}
        or (basename.startswith(".env.") and basename != ".env.example")
    ) or name.endswith((".sqlite3", ".sqlite", ".operations-token", ".initial.txt")):
        result.append({"kind": "credential_file", "file": name})
    return result


def archive_findings(data, name):
    result = []
    if name.endswith((".whl", ".zip")):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_ARCHIVE_BYTES:
                return [{"kind": "archive_too_large", "file": name}]
            for info in archive.infolist():
                if not info.is_dir():
                    result.extend(findings(archive.read(info), f"{name}!{info.filename}"))
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            if sum(info.size for info in members) > MAX_ARCHIVE_BYTES:
                return [{"kind": "archive_too_large", "file": name}]
            for info in members:
                if info.isfile():
                    result.extend(findings(archive.extractfile(info).read(), f"{name}!{info.name}"))
    return result


def current_files(root):
    names = (
        subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )
        .decode()
        .split("\0")
    )
    result, count = [], 0
    for name in names:
        path = root / name
        if not name or not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        result.extend(findings(data, name))
        result.extend(archive_findings(data, name))
        count += 1
    # Ignored distributions and static assets are still release surfaces.
    for directory in ("dist", "build", "scMM/api/static"):
        for path in (root / directory).rglob("*"):
            if path.is_file() and not path.is_symlink():
                name = str(path.relative_to(root))
                data = path.read_bytes()
                result.extend(findings(data, name))
                result.extend(archive_findings(data, name))
                count += 1
    return {
        "files": count,
        "counts": dict(collections.Counter(x["kind"] for x in result)),
        "findings": result,
    }


def history(root):
    objects = subprocess.check_output(
        ["git", "-C", str(root), "rev-list", "--objects", "--all"]
    ).splitlines()
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    result, count = [], 0
    try:
        for entry in objects:
            parts = entry.split(b" ", 1)
            identity = parts[0]
            name = parts[1].decode(errors="replace") if len(parts) > 1 else ""
            process.stdin.write(identity + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            if header[1] == b"blob":
                result.extend(findings(data, name, identity.decode()))
                result.extend(archive_findings(data, name))
                count += 1
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    return {
        "objects": len(objects),
        "blobs": count,
        "counts": dict(collections.Counter(x["kind"] for x in result)),
        "findings": result,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--history",
        action="store_true",
        help="Audit all locally reachable refs; never rewrites history",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = {"current": current_files(args.root)}
    if args.history:
        report["history"] = history(args.root)
    if args.report:
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                key: {k: v for k, v in value.items() if k != "findings"}
                for key, value in report.items()
            }
        )
    )
    return int(any(value["findings"] for value in report.values()))


if __name__ == "__main__":
    raise SystemExit(main())
