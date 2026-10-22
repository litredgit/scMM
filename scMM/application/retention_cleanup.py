"""Reviewed retention cleanup with complete recovery copies before removing sources."""
# ruff: noqa: RUF001

import errno
import hashlib
import json
import os
import re
import shutil
from contextlib import ExitStack, nullcontext
from pathlib import Path
from uuid import uuid4

from .naming import beijing_time
from .projects import project_lock, write_json
from .retention import _safe, retention_plan
from .tasks import utc_now


def _selected(advice):
    return [r for r in advice["items"] if r["selected_for_cleanup"]]


def cleanup_plan(manager, value, *, min_age_days=None, keep_latest=None):
    advice = retention_plan(manager, value, min_age_days=min_age_days, keep_latest=keep_latest)
    if advice["warnings"]:
        raise RuntimeError("引用或产物状态无法完整核实，不能生成清理计划")
    selected = _selected(advice)
    if not selected:
        raise ValueError("没有符合策略且可安全清理的产物，请先查看保留计划")
    folder = Path(advice["project"])
    members = [
        {"path": path, "inventory": manager._inventory(_safe(folder / path))}
        for row in selected
        for path in row["paths"]
    ]
    return {
        "retention_version": 1,
        "root": str(manager.store.root),
        "path": str(folder),
        "project_id": manager.store._manifest(folder)["id"],
        "kind": "快照与缓存策略清理",
        "policy_parameters": advice["policy_parameters"],
        "items": selected,
        "members": members,
        "files": sum(row["files"] for row in selected),
        "bytes": advice["selected_bytes"],
        "generated_at": advice["generated_at"],
    }


def _digest(manager, path):
    manager._inventory(_safe(path))
    records = []
    for child in [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]:
        _safe(child)
        if child.name == ".project.lock":
            continue
        if child.is_dir():
            value = "directory"
        else:
            with child.open("rb") as handle:
                value = hashlib.file_digest(handle, "sha256").hexdigest()
        records.append((str(child.relative_to(path)), value))
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()


def _copy(source, target):
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _sync_tree(path):
    for child in path.rglob("*") if path.is_dir() else [path]:
        if child.is_file():
            with child.open("rb") as handle:
                os.fsync(handle.fileno())
    if os.name == "posix":
        folders = (
            [*sorted((p for p in path.rglob("*") if p.is_dir()), reverse=True), path]
            if path.is_dir()
            else []
        )
        for folder in [*folders, path.parent]:
            descriptor = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _publish(temporary, target):
    """Publish with exclusive creation; never replace an intervening destination."""
    if temporary.is_dir():
        target.mkdir()
        for child in temporary.iterdir():
            _publish(child, target / child.name)
        shutil.copystat(temporary, target)
        temporary.rmdir()
    else:
        try:
            os.link(temporary, target)
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP}:
                raise
            # Some mounted result filesystems do not support hard links.
            created = False
            try:
                with temporary.open("rb") as source, target.open("xb") as output:
                    created = True
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                shutil.copystat(temporary, target)
            except Exception:
                if created:
                    target.unlink()
                raise
        temporary.unlink()


def _folder(manager, record):
    folder = _safe(Path(record["path"]))
    if (
        Path(record["root"]) != manager.store.root
        or not folder.is_absolute()
        or ".." in folder.parts
        or folder.parent != manager.store.root
    ):
        raise PermissionError("清理恢复仅支持所属环境项目根中的项目")
    manifest = manager.store._manifest(manager.store._folder(folder))
    if record.get("project_id") is not None and record["project_id"] != manifest["id"]:
        raise PermissionError("项目身份已改变，不能将归档恢复到其他项目")
    return folder


def execute_cleanup(manager, plan, *, check_allowed=lambda: None):
    """Revalidate the frozen selection, archive all members, then remove sources.

    Interrupted removal leaves a visible recovery entry. It is never eligible for
    permanent clearing until restoration has resolved the partial operation.
    """
    check_allowed()
    folder = _folder(manager, plan)
    manager._prepare_trash()
    with ExitStack() as locks:
        locks.enter_context(project_lock(manager.trash_root))
        folders = manager._project_folders()
        for root in sorted({manager.store.root, *(p.parent for p in folders)}):
            locks.enter_context(project_lock(root))
        for project in folders:
            locks.enter_context(project_lock(project))
        current = cleanup_plan(manager, folder, **plan["policy_parameters"])
        for key in ("root", "path", "project_id", "items", "members", "files", "bytes"):
            if current[key] != plan[key]:
                raise RuntimeError("清理清单或产物已改变，请重新查看清理计划")
        entry = manager.trash_root / f"{beijing_time(compact=True)}_{uuid4().hex[:12]}"
        entry.mkdir()
        payload = entry / "payload"
        payload.mkdir()
        record = {**plan, "deleted_at": utc_now(), "status": "prepared", "members": []}
        published = False
        try:
            for index, member in enumerate(plan["members"]):
                check_allowed()
                source = _safe(folder / member["path"])
                digest = _digest(manager, source)
                _copy(source, payload / str(index))
                if _digest(manager, payload / str(index)) != digest:
                    raise OSError("恢复副本校验失败，原件保留")
                record["members"].append({"path": member["path"], "digest": digest})
            # Fresh usage and identities after potentially slow cross-device copies.
            current = cleanup_plan(manager, folder, **plan["policy_parameters"])
            if current["items"] != plan["items"] or current["members"] != plan["members"]:
                raise RuntimeError("归档期间引用、策略清单或产物发生变化，原件保留")
            write_json(entry / "record.json", record)
            _sync_tree(entry)
            published = True
            check_allowed()
            for member in record["members"]:
                check_allowed()
                source = _safe(folder / member["path"])
                if _digest(manager, source) != member["digest"]:
                    raise RuntimeError("移走前产物发生变化，恢复副本已保留")
                _remove(source)
            record["status"] = "moved"
            write_json(entry / "record.json", record)
        except Exception:
            if not published:
                shutil.rmtree(entry)
            else:
                try:
                    restore_cleanup(manager, entry, record, locked=True)
                except Exception as recovery_error:
                    raise RuntimeError(
                        f"清理中断且自动恢复未完成，完整副本保留于 {entry}；"
                        "请刷新回收区并恢复，禁止直接永久清空"
                    ) from recovery_error
            raise
    return entry


def _missing(manager, archive, target, *, allow_partial):
    if not target.exists():
        return [(archive, target)]
    if _digest(manager, target) == _digest(manager, archive):
        return []
    if not allow_partial or not target.is_dir() or not archive.is_dir():
        raise FileExistsError("原路径已有不同内容，不能覆盖；请先处理冲突")
    # A failed recursive removal/restoration may leave a subset of the archive.
    # Verify all survivors before planning any write, and never replace survivors.
    for child in [target, *sorted(target.rglob("*"))]:
        corresponding = archive / child.relative_to(target)
        if not corresponding.exists() or child.is_dir() != corresponding.is_dir():
            raise FileExistsError("原目录含不同内容，不能覆盖；请先处理冲突")
        if child.is_file() and _digest(manager, child) != _digest(manager, corresponding):
            raise FileExistsError("原目录含不同内容，不能覆盖；请先处理冲突")
    missing = []
    for child in sorted(archive.rglob("*")):
        destination = target / child.relative_to(archive)
        if not destination.exists() and not any(
            p == destination or p in destination.parents for _, p in missing
        ):
            missing.append((child, destination))
    return missing


def restore_cleanup(manager, entry, record, *, locked=False):
    """Restore missing members; preserve matching originals after an interrupted move."""
    folder = _folder(manager, record)
    with nullcontext() if locked else project_lock(folder):
        members = record.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("清理恢复记录缺少完整成员")
        destinations, missing, seen = [], [], set()
        for index, member in enumerate(members):
            relative = Path(member["path"])
            parts = relative.parts
            if len(parts) != 2 or parts[0] not in {"snapshots", "processing"}:
                raise PermissionError("恢复成员路径越界")
            if parts[1] in {".", "..", ".project.lock"} or relative.is_absolute():
                raise PermissionError("恢复成员路径越界")
            if parts[0] == "processing" and not re.fullmatch(
                r"preview-[a-f0-9]{32}|shared-[a-f0-9]{64}\.(npy|json)", parts[1]
            ):
                raise PermissionError("恢复成员不是已识别缓存")
            target = _safe(folder / relative)
            if target in seen:
                raise ValueError("恢复成员重复")
            seen.add(target)
            archive = entry / "payload" / str(index)
            if record.get("status") == "restored":
                if _digest(manager, target) != member["digest"]:
                    raise RuntimeError("已恢复原件发生变化，请使用回收区清空处理残余归档")
                continue
            if _digest(manager, archive) != member["digest"]:
                raise RuntimeError("恢复副本内容发生变化，拒绝恢复")
            if not target.parent.is_dir():
                raise FileNotFoundError("原父目录不存在，请先恢复所属项目")
            missing.extend(
                _missing(
                    manager,
                    archive,
                    target,
                    allow_partial=record.get("status") in {"prepared", "restoring"},
                )
            )
            destinations.append((archive, target, member["digest"]))
        record = {**record, "status": "restoring"}
        write_json(entry / "record.json", record)
        for archive, target in missing:
            digest = _digest(manager, archive)
            temporary = target.with_name(f".restore-{uuid4().hex}")
            try:
                _copy(archive, temporary)
                if _digest(manager, temporary) != digest:
                    raise OSError("恢复写入校验失败，回收副本保留")
                if target.exists():
                    raise FileExistsError("恢复期间出现同名内容，回收副本保留")
                _publish(temporary, target)
            finally:
                if temporary.exists():
                    _remove(temporary)
        for _, target, digest in destinations:
            if _digest(manager, target) != digest:
                raise RuntimeError("恢复后内容复核失败，完整回收副本保留")
            _sync_tree(target)
        write_json(entry / "record.json", {**record, "status": "restored"})
        _sync_tree(entry)
        shutil.rmtree(entry)
    return folder
