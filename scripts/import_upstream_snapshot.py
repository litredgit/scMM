"""Archive an untracked source drop in local Git history without checking out branches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = ".upstream-snapshots.git"
BRANCH = "refs/heads/snapshots"
MIRROR = "refs/heads/vendor/snapshots"
METADATA = ".snapshot.json"
IGNORED_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", ".ruff_cache"}


def git(root, *arguments, data=None, index=None, required=True):
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    result = subprocess.run(
        ["git", "-C", str(root), *map(str, arguments)],
        input=data,
        capture_output=True,
        env=env,
    )
    if required and result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return result


def collect(source):
    if (source / "scMM" / "__init__.py").is_file():
        layout, prefix = "project", ""
    elif (source / "__init__.py").is_file() and (source / "file" / "data.py").is_file():
        layout, prefix = "package", "scMM/"
    else:
        raise ValueError("Expected a project containing scMM/ or an scMM package source directory")
    files, ignored = {}, []
    for directory, dirs, names in os.walk(source, followlinks=False):
        parent = Path(directory)
        for name in sorted(dirs):
            path = parent / name
            if name in IGNORED_DIRS:
                ignored.append(path.relative_to(source).as_posix() + "/")
                dirs.remove(name)
            elif path.is_symlink():
                raise ValueError(f"Symlink directories are not imported: {path}")
        dirs.sort()
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(source).as_posix()
            if name.endswith((".pyc", ".pyo")) or name == ".git":
                ignored.append(relative)
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Only regular source files are imported: {path}")
            target = prefix + relative
            if target == METADATA:
                raise ValueError(f"Source conflicts with reserved metadata path: {METADATA}")
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            files[target] = (mode, path.read_bytes())
    manifest = {
        name: {"mode": mode, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, (mode, content) in sorted(files.items())
    }
    return layout, files, manifest, sorted(ignored)


def local_excludes(project, source_name):
    location = git(project, "rev-parse", "--git-path", "info/exclude").stdout.decode().strip()
    path = Path(location)
    if not path.is_absolute():
        path = project / path
    previous = path.read_text() if path.exists() else ""
    lines = previous.splitlines()
    for name in (REPOSITORY, source_name):
        escaped = "".join("\\" + c if c in "\\*?[]#! " else c for c in name)
        pattern = f"/{escaped}/"
        if pattern not in lines:
            lines.append(pattern)
    updated = "\n".join(lines) + "\n"
    if updated != previous:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated)


def import_snapshot(project, source, *, name=None, received_date=None, claimed_base=None):
    project = project.resolve()
    source = source if source.is_absolute() else project / source
    if source.is_symlink():
        raise ValueError("The source directory must not be a symlink")
    source = source.resolve()
    if source.parent != project or not source.is_dir() or source.name == REPOSITORY:
        raise ValueError("Source must be a copied directory directly below the project root")
    if git(project, "ls-files", "--", source.name).stdout:
        raise ValueError(
            "Source already contains tracked project files; refusing to archive it as a drop"
        )
    name = name or source.name
    tag = f"refs/tags/snapshot/{name}"
    git(project, "check-ref-format", tag)
    if git(project, "symbolic-ref", "-q", "HEAD", required=False).stdout.decode().strip() == MIRROR:
        raise ValueError("Switch away from vendor/snapshots before importing")
    layout, files, manifest, ignored = collect(source)
    repository = project / REPOSITORY
    if not repository.exists():
        git(project, "init", "--bare", "--initial-branch=snapshots", repository)
        for key in ("user.name", "user.email"):
            value = git(project, "config", "--get", key).stdout.decode().strip()
            git(repository, "config", key, value)
    if git(repository, "rev-parse", "--is-bare-repository").stdout.strip() != b"true":
        raise ValueError(f"Not a bare repository: {repository}")
    existing = git(repository, "rev-parse", "--verify", tag, required=False)
    if existing.returncode == 0:
        metadata = json.loads(git(repository, "show", f"{tag}:{METADATA}").stdout)
        if metadata["files"] != manifest or metadata["layout"] != layout:
            raise ValueError(
                f"Snapshot {name} already exists with different content; use --name for a new version"
            )
        commit = existing.stdout.decode().strip()
        action = "Already archived"
    else:
        now = datetime.now(UTC)
        metadata = {
            "schema_version": 1,
            "source_directory": source.name,
            "layout": layout,
            "received_date": received_date or now.date().isoformat(),
            "imported_at": now.isoformat(),
            "claimed_base_commit": claimed_base,
            "history_note": "Commits record receipt order, not the author's original Git ancestry.",
            "ignored": ignored,
            "files": manifest,
        }
        files[METADATA] = (
            "100644",
            (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode(),
        )
        previous = git(repository, "rev-parse", "--verify", BRANCH, required=False)
        parent = previous.stdout.decode().strip() if previous.returncode == 0 else None
        with tempfile.TemporaryDirectory(prefix="scmm-snapshot-index-") as temporary:
            index = Path(temporary) / "index"
            git(repository, "read-tree", "--empty", index=index)
            entries = bytearray()
            for path, (mode, content) in sorted(files.items()):
                blob = git(repository, "hash-object", "-w", "--stdin", data=content).stdout.strip()
                entries.extend(mode.encode() + b" " + blob + b"\t" + path.encode() + b"\0")
            git(repository, "update-index", "-z", "--index-info", data=bytes(entries), index=index)
            tree = git(repository, "write-tree", index=index).stdout.decode().strip()
        parents = ["-p", parent] if parent else []
        message = f"snapshot: import {name}\n\nSource: {source.name}\nLayout: {layout}\n"
        commit = (
            git(repository, "commit-tree", tree, *parents, data=message.encode())
            .stdout.decode()
            .strip()
        )
        update = f"update {BRANCH} {commit} {parent}" if parent else f"create {BRANCH} {commit}"
        transaction = f"start\n{update}\ncreate {tag} {commit}\nprepare\ncommit\n"
        git(repository, "update-ref", "--stdin", data=transaction.encode())
        action = "Archived"
    # Fetch also copies objects into the main repository, so the comparison
    # branch survives loss of the separate local bare repository.
    git(project, "fetch", "--no-tags", str(repository), f"{BRANCH}:{MIRROR}")
    local_excludes(project, source.name)
    return {
        "action": action,
        "snapshot": name,
        "commit": commit,
        "files": len(manifest),
        "ignored": ignored,
        "layout": layout,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--name", help="Unique snapshot name; defaults to the copied directory name"
    )
    parser.add_argument("--received-date", help="Receipt date (YYYY-MM-DD); defaults to today")
    parser.add_argument("--claimed-base", help="Reported base commit, recorded as provenance only")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.received_date:
        datetime.strptime(args.received_date, "%Y-%m-%d")
    result = import_snapshot(
        args.project_root,
        args.source,
        name=args.name,
        received_date=args.received_date,
        claimed_base=args.claimed_base,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
