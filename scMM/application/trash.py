"""Reviewable, reversible removal of saved projects and processed results."""
# ruff: noqa: RUF001

import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from anndata import read_h5ad

from .naming import beijing_time
from .projects import project_lock, write_json
from .storage import SUPPORTED_RAW_SUFFIXES, StorageCatalog, StorageRoot
from .tasks import utc_now


def _overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def _references(value, folder):
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key
                in {
                    "current",
                    "baseline",
                    "views",
                    "artifact",
                    "source",
                    "data_source",
                    "path",
                    "output",
                    "result_path",
                }
                and isinstance(item, str)
                and item
            ):
                path = Path(item)
                yield (path if path.is_absolute() else folder / path).resolve()
            else:
                yield from _references(item, folder)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _references(item, folder)


class SavedItems:
    def __init__(self, store, roots, *, active_paths=lambda: ()):
        self.store = store
        roots = [StorageRoot("项目结果", store.root), *roots]
        self.catalog = StorageCatalog(roots)
        self.active_paths = active_paths

    def _target(self, label, value):
        root = self.catalog.root(label).path
        lexical = Path(value).expanduser()
        if not lexical.is_absolute():
            lexical = root / lexical
        if ".." in lexical.parts or any(p.is_symlink() for p in (lexical, *lexical.parents)):
            raise PermissionError("不能删除符号链接或含上级跳转的路径")
        path = self.catalog.resolve(label, lexical)
        if path == root or path == self.store.root or ".scmm-trash" in path.parts:
            raise PermissionError("不能删除存储根目录或回收区")
        for parent in path.parents:
            if (parent / "project.json").is_file() and parent.parent != self.store.root:
                raise PermissionError("这是其他项目根中的内容，请到所属环境管理")
        if path.is_dir() and (path / "project.json").is_file():
            self.store._folder(path)
            self.store._manifest(path)
            kind = "项目"
        elif path.is_file() and path.suffix.lower() == ".h5ad":
            kind = "H5AD 结果"
        elif path.is_dir() and (
            (path / ".meta").is_file()
            or ((path / "request.json").is_file() and (path / "state.json").is_file())
            or list(path.glob("*.h5ad"))
        ):
            kind = "结果目录"
        else:
            raise ValueError("请选择已保存项目、H5AD 文件或已识别的处理结果目录")
        return root, path, kind

    def _inventory(self, path):
        records, count, size = [], 0, 0
        for child in [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]:
            if child.is_symlink():
                raise PermissionError("所选内容含符号链接，不能移入回收区")
            if child.name == ".project.lock":
                continue
            if child.suffix.lower() in SUPPORTED_RAW_SUFFIXES:
                raise PermissionError("所选内容含原始谱文件，不能删除")
            stat = child.stat()
            if not child.is_file() and not child.is_dir():
                raise PermissionError("所选内容含特殊文件")
            records.append(
                (
                    str(child.relative_to(path)),
                    stat.st_ino,
                    stat.st_size if child.is_file() else 0,
                    stat.st_mtime_ns if child.is_file() else 0,
                    stat.st_ctime_ns if child.is_file() else 0,
                )
            )
            if child.is_file():
                count += 1
                size += stat.st_size
        digest = hashlib.sha256(json.dumps(records).encode()).hexdigest()
        return count, size, digest

    def _check_usage(self, target):
        for value in self.active_paths():
            if value and _overlaps(target, Path(value).resolve()):
                raise RuntimeError("项目或结果仍在网页会话中使用，请先保存并关闭相关项目")
        for folder in self._project_folders():
            manifest = self.store._manifest(folder)
            if folder != target:
                references = list(_references(manifest, folder))
                # H5AD also retains extraction-batch provenance after imports.
                for artifact in ("current", "baseline"):
                    if not manifest["artifacts"].get(artifact):
                        continue
                    current = folder / manifest["artifacts"][artifact]
                    data = read_h5ad(current, backed="r")
                    try:
                        references.extend(_references(dict(data.uns), folder))
                    finally:
                        data.file.close()
                if any(_overlaps(target, ref) for ref in references):
                    raise RuntimeError(f"结果仍被项目“{manifest['name']}”引用，不能删除")
            for state_path in (folder / "processing").rglob("state.json"):
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("status") not in {"queued", "running"}:
                    continue
                request_path = state_path.with_name("request.json")
                request = (
                    json.loads(request_path.read_text(encoding="utf-8"))
                    if request_path.exists()
                    else {}
                )
                if _overlaps(target, state_path) or any(
                    _overlaps(target, ref) for ref in _references(request, state_path.parent)
                ):
                    raise RuntimeError("所选内容关联未结束任务，请等待任务结束后再删除")
        if target.is_dir():
            for state_path in target.rglob("state.json"):
                if json.loads(state_path.read_text(encoding="utf-8")).get("status") in {
                    "queued",
                    "running",
                }:
                    raise RuntimeError("所选目录中仍有未结束任务")
        for root in {r.path for r in self.catalog.roots}:
            for task_root in root.rglob(".scmm-tasks"):
                if ".scmm-trash" in task_root.parts or task_root.is_symlink():
                    continue
                for state_path in task_root.glob("*/state.json"):
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if state.get("status") not in {"queued", "running"}:
                        continue
                    request_path = state_path.with_name("request.json")
                    request = (
                        json.loads(request_path.read_text(encoding="utf-8"))
                        if request_path.exists()
                        else {}
                    )
                    if any(
                        _overlaps(target, ref)
                        for ref in _references([state, request], state_path.parent)
                    ):
                        raise RuntimeError("所选结果关联未结束的处理任务")

    def _project_folders(self):
        folders = {Path(row["path"]) for row in self.store.list()}
        for root in {r.path for r in self.catalog.roots}:
            for path in root.rglob("project.json"):
                if ".scmm-trash" in path.parts or path.is_symlink():
                    continue
                try:
                    self.store._manifest(path.parent)
                except (ValueError, KeyError):
                    continue
                folders.add(path.parent)
        return sorted(folders)

    def plan(self, label, value):
        root, path, kind = self._target(label, value)
        self._check_usage(path)
        count, size, fingerprint = self._inventory(path)
        return {
            "label": label,
            "path": str(path),
            "root": str(root),
            "kind": kind,
            "files": count,
            "bytes": size,
            "fingerprint": fingerprint,
        }

    def move(self, plan):
        with ExitStack() as locks:
            folders = self._project_folders()
            for root in sorted({self.store.root, *(folder.parent for folder in folders)}):
                locks.enter_context(project_lock(root))
            for folder in folders:
                locks.enter_context(project_lock(folder))
            if self.plan(plan["label"], plan["path"]) != plan:
                raise RuntimeError("所选内容已改变，请重新预览删除计划")
            root, original = Path(plan["root"]), Path(plan["path"])
            trash = root / ".scmm-trash"
            if trash.is_symlink():
                raise PermissionError("回收区不能是符号链接")
            trash.mkdir(exist_ok=True)
            entry = trash / f"{beijing_time(compact=True)}_{uuid4().hex[:12]}"
            entry.mkdir()
            record = {**plan, "deleted_at": utc_now(), "status": "moved"}
            write_json(entry / "record.json", record)
            os.rename(original, entry / "payload")
        return entry

    def list_trash(self):
        entries = []
        for root in {r.path for r in self.catalog.roots}:
            trash = root / ".scmm-trash"
            if trash.is_symlink():
                continue
            for entry in trash.glob("*/record.json"):
                if (
                    entry.is_symlink()
                    or entry.parent.is_symlink()
                    or not (entry.parent / "payload").exists()
                ):
                    continue
                try:
                    record = json.loads(entry.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                if (
                    not isinstance(record, dict)
                    or not {"root", "path", "deleted_at", "kind"} <= record.keys()
                ):
                    continue
                entries.append({**record, "entry": str(entry.parent)})
        return sorted(entries, key=lambda row: row["deleted_at"], reverse=True)

    def restore(self, value):
        with project_lock(self.store.root):
            entry = Path(value)
            records = {r["entry"]: r for r in self.list_trash()}
            if str(entry) not in records:
                raise PermissionError("请选择当前回收区条目")
            record = records[str(entry)]
            root, original = Path(record["root"]), Path(record["path"])
            if (
                root not in {r.path for r in self.catalog.roots}
                or not original.is_absolute()
                or ".." in original.parts
                or original == root
                or not original.resolve().is_relative_to(root)
            ):
                raise PermissionError("恢复路径越过存储根目录")
            if any(p.is_symlink() for p in (original, *original.parents)):
                raise PermissionError("恢复路径含符号链接")
            if original.exists():
                raise FileExistsError("原路径已有同名内容，不能覆盖；请先处理冲突")
            if not original.parent.is_dir():
                raise FileNotFoundError("原父目录不存在，请先恢复所属项目")
            self._inventory(entry / "payload")
            os.rename(entry / "payload", original)
            write_json(entry / "record.json", {**record, "status": "restored"})
        return original
