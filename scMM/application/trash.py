"""Reviewable, reversible removal of saved projects and processed results."""
# ruff: noqa: RUF001

import errno
import hashlib
import json
import os
import shutil
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
    def __init__(self, store, roots, *, active_paths=lambda: (), trash_root=None):
        self.store = store
        roots = [StorageRoot("项目结果", store.root), *roots]
        self.catalog = StorageCatalog(roots)
        self.active_paths = active_paths
        self.trash_root = Path(
            trash_root
            or os.environ.get("SCMM_RECYCLE_ROOT")
            or Path.home() / "data/results/recycle"
        ).absolute()

    def _target(self, label, value):
        root = self.catalog.root(label).path
        lexical = Path(value).expanduser()
        if not lexical.is_absolute():
            lexical = root / lexical
        if ".." in lexical.parts or any(p.is_symlink() for p in (lexical, *lexical.parents)):
            raise PermissionError("不能删除符号链接或含上级跳转的路径")
        path = self.catalog.resolve(label, lexical)
        if path == root or path == self.store.root or _overlaps(path, self.trash_root):
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
                # Reopening a project records its own folder as the workspace source.
                # This provenance is not a reference to every obsolete snapshot inside it.
                if target.is_relative_to(folder):
                    references = [ref for ref in references if ref != folder]
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
                if task_root.is_relative_to(self.trash_root) or task_root.is_symlink():
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
                if path.is_relative_to(self.trash_root) or path.is_symlink():
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
        self._prepare_trash()
        with ExitStack() as locks:
            locks.enter_context(project_lock(self.trash_root))
            folders = self._project_folders()
            for root in sorted({self.store.root, *(folder.parent for folder in folders)}):
                locks.enter_context(project_lock(root))
            for folder in folders:
                locks.enter_context(project_lock(folder))
            if self.plan(plan["label"], plan["path"]) != plan:
                raise RuntimeError("所选内容已改变，请重新预览删除计划")
            original = Path(plan["path"])
            trash = self.trash_root
            entry = trash / f"{beijing_time(compact=True)}_{uuid4().hex[:12]}"
            entry.mkdir()
            record = {**plan, "deleted_at": utc_now(), "status": "moved"}
            write_json(entry / "record.json", record)
            self._transfer(original, entry / "payload")
        return entry

    def list_trash(self):
        entries = []
        self._validate_trash()
        for entry in self.trash_root.glob("*/record.json"):
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
        self._prepare_trash()
        with project_lock(self.trash_root), project_lock(self.store.root):
            entry = Path(value)
            records = {r["entry"]: r for r in self.list_trash()}
            if str(entry) not in records:
                raise PermissionError("请选择当前回收区条目")
            record = records[str(entry)]
            if record.get("retention_version") == 1:
                from .retention_cleanup import restore_cleanup

                return restore_cleanup(self, entry, record)
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
            self._transfer(entry / "payload", original)
            shutil.rmtree(entry)
        return original

    def _validate_trash(self):
        if ".." in self.trash_root.parts or any(
            p.is_symlink() for p in (self.trash_root, *self.trash_root.parents)
        ):
            raise PermissionError("回收区路径不能含符号链接或上级跳转")

    def _prepare_trash(self):
        self._validate_trash()
        self.trash_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _transfer(source, target):
        """Move across storage devices only after a complete verified copy."""
        try:
            os.rename(source, target)
            return
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
        staging = target.with_name(f".transfer-{uuid4().hex}")
        try:
            if source.is_dir():
                shutil.copytree(source, staging)
            else:
                shutil.copy2(source, staging)
            originals = (
                sorted(p for p in source.rglob("*") if p.is_file()) if source.is_dir() else [source]
            )
            for original in originals:
                copied = staging / original.relative_to(source) if source.is_dir() else staging
                with original.open("rb") as left, copied.open("rb") as right:
                    if (
                        hashlib.file_digest(left, "sha256").digest()
                        != hashlib.file_digest(right, "sha256").digest()
                    ):
                        raise OSError("跨存储移动校验失败，原内容已保留")
            os.rename(staging, target)
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
        finally:
            if staging.is_dir():
                shutil.rmtree(staging)
            elif staging.exists():
                staging.unlink()

    def clear(self):
        """Clear a locked inventory; reject unsafe content before deleting anything."""
        self._prepare_trash()
        with ExitStack() as locks:
            locks.enter_context(project_lock(self.trash_root))
            folders = self._project_folders()
            for root in sorted({self.store.root, *(folder.parent for folder in folders)}):
                locks.enter_context(project_lock(root))
            for folder in folders:
                locks.enter_context(project_lock(folder))
            entries = sorted(p for p in self.trash_root.iterdir() if p.name != ".project.lock")
            plans = []
            for entry in entries:
                record_path = entry / "record.json"
                if record_path.is_file() and not record_path.is_symlink():
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    if not isinstance(record, dict):
                        raise ValueError("回收记录无法核实，请先检查回收区")
                    if record.get("retention_version") == 1 and record.get("status") not in {
                        "moved",
                        "restored",
                    }:
                        raise RuntimeError("存在未完成的策略清理，请先恢复回收条目再永久清空")
                self._check_usage(entry)
                plans.append((entry, self._inventory(entry)))
            removed, errors = 0, []
            for entry, inventory in plans:
                try:
                    if self._inventory(entry) != inventory:
                        raise RuntimeError("回收条目已改变，请刷新后重试")
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                    removed += 1
                except (OSError, RuntimeError) as exc:
                    errors.append(f"{entry.name}：{exc}")
            if errors:
                raise RuntimeError(f"已清理 {removed} 项；未清理：" + "；".join(errors))
            return removed
