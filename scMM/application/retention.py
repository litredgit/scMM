"""Read-only retention advice; never authorizes or performs removal."""
# ruff: noqa: RUF001

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from anndata import read_h5ad

from .preview_cache import PREVIEW_FILES, file_identity
from .tasks import utc_now
from .trash import _overlaps, _references

TERMINAL_STATES = {"succeeded", "completed", "failed", "stopped", "cancelled"}


def _json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("元数据不是对象")
    return value


def _safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PermissionError("路径含符号链接")
    return path


def _metadata_paths(manager):
    paths = set()

    def failed(error):
        raise error

    for root in {r.path for r in manager.catalog.roots}:
        for directory, children, files in os.walk(root, onerror=failed, followlinks=False):
            folder = Path(directory)
            if folder.is_relative_to(manager.trash_root):
                children.clear()
                continue
            for name in children:
                if (folder / name).is_symlink():
                    raise ValueError("引用扫描范围含符号链接目录")
            paths.update(folder / name for name in files if name in {"project.json", "state.json"})
    return paths


def _usage(manager):
    """Read each persisted matrix's provenance once, without loading X."""
    references, tasks, errors = [], [], []
    try:
        metadata = _metadata_paths(manager)
    except (OSError, ValueError):
        return [], [], ["引用扫描未完成（目录不可读或含符号链接），继续保留"], set(), {}
    manifests = {p for p in metadata if p.name == "project.json"}
    states = metadata - manifests
    evidence = {}

    def remember(path):
        _safe(path)
        evidence[path] = file_identity(path)

    for path in sorted(manifests):
        try:
            remember(path)
            manifest = manager.store._manifest(path.parent)
            refs = list(_references(manifest, path.parent))
            for key in ("current", "baseline"):
                value = manifest["artifacts"].get(key)
                if not value:
                    continue
                artifact = Path(value)
                artifact = _safe(path.parent / artifact)
                if not artifact.resolve().is_relative_to(path.parent.resolve()):
                    raise PermissionError("快照路径越界")
                remember(artifact)
                data = read_h5ad(artifact, backed="r")
                try:
                    refs.extend(_references(dict(data.uns), path.parent))
                finally:
                    data.file.close()
            references.append((path.parent, refs))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
            errors.append(f"项目引用无法核实：{path}")
    for path in sorted(states):
        try:
            remember(path)
            state = _json(path)
            status = state.get("status")
            if status in TERMINAL_STATES:
                continue
            if status not in {"queued", "running"}:
                raise ValueError("任务状态未知")
            request_path = path.with_name("request.json")
            remember(request_path)
            request = _json(_safe(request_path))
            refs = [path.parent, *_references([state, request], path.parent)]
            # A worker may create/reuse any cache in its own project.
            if request.get("project_folder"):
                refs.append(Path(request["project_folder"]).resolve())
            for parent in path.parents:
                if parent / "project.json" in manifests:
                    refs.append(parent)
                    break
            tasks.extend(refs)
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(f"任务状态或冻结请求无法核实：{path}")
    return references, tasks, errors, metadata, evidence


def _items(folder):
    for path in sorted((folder / "snapshots").iterdir()):
        if path.name == ".project.lock":
            continue
        yield (
            "历史快照",
            [path],
            not path.is_symlink()
            and path.is_dir()
            and (any(path.glob("*.h5ad")) or (path / "views.json").is_file()),
        )
    processing = folder / "processing"
    shared = {}
    for path in sorted(processing.iterdir()):
        if re.fullmatch(r"preview-[a-f0-9]{32}", path.name):
            yield (
                "预览缓存",
                [path],
                not path.is_symlink()
                and path.is_dir()
                and all((path / name).is_file() for name in (*PREVIEW_FILES, "identity.json")),
            )
        elif re.fullmatch(r"shared-[a-f0-9]{64}\.(npy|json)", path.name):
            shared.setdefault(path.stem, []).append(path)
        else:
            yield "任务、批次或未识别产物", [path], False
    for paths in shared.values():
        yield "共同特征缓存", paths, len(paths) == 2 and all(p.is_file() for p in paths)


def _policy(rows, *, min_age_days, keep_latest, now_ns):
    """Apply explicit retention guards independently within each artifact kind."""
    for name, value in (("min_age_days", min_age_days), ("keep_latest", keep_latest)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{name} 必须是非负整数或空值")
    enabled = min_age_days is not None or keep_latest is not None
    for kind in {row["kind"] for row in rows}:
        ordered = sorted(
            (
                r
                for r in rows
                if r["kind"] == kind
                and r["complete"]
                and r["modified_ns"] is not None
                and r["modified_ns"] <= now_ns
            ),
            key=lambda r: (-r["modified_ns"], r["paths"]),
        )
        # Keep every tie at the cutoff; path ordering must not decide data retention.
        cutoff = (
            ordered[min(keep_latest, len(ordered)) - 1]["modified_ns"]
            if keep_latest and ordered
            else None
        )
        for row in (r for r in rows if r["kind"] == kind):
            row["selected_for_cleanup"] = False
            if row["status"] != "candidate":
                continue
            reasons = []
            if not enabled:
                reasons.append("未设置保留策略，默认全部保留")
            if row["modified_ns"] is None or row["modified_ns"] > now_ns:
                reasons.append("修改时间无法核实或晚于检查时间，继续保留")
            else:
                if cutoff is not None and row["modified_ns"] >= cutoff:
                    reasons.append("属于该类最新保留数量（边界同时间项全部保留）")
                if (
                    min_age_days is not None
                    and now_ns - row["modified_ns"] < min_age_days * 86400 * 10**9
                ):
                    reasons.append("尚未达到最小年龄，继续保留")
            row["selected_for_cleanup"] = not reasons
            row["policy_reasons"] = reasons or ["满足显式策略，仅列为待审阅清理建议"]
    for row in rows:
        row.pop("modified_ns")
        row.pop("complete")
        row.setdefault("policy_reasons", ["保护或核实规则优先于保留策略"])


def retention_plan(manager, value, *, min_age_days=None, keep_latest=None):
    """Inspect a local project's snapshots/caches; default policy keeps everything.

    Unknown references block every recommendation. This advisory has no deletion
    token: later manual removal must obtain a fresh SavedItems plan.
    """
    # Validate before inspecting storage; a direct Python call has the same boundary as HTTP.
    _policy([], min_age_days=min_age_days, keep_latest=keep_latest, now_ns=0)
    now_ns = time.time_ns()
    folder = manager.store._folder(_safe(Path(value).absolute()))
    if folder.parent != manager.store.root:
        raise PermissionError("保留计划仅支持本环境项目根中的项目")
    manager.store._manifest(folder)
    for name in ("snapshots", "processing"):
        _safe(folder / name)
        if not (folder / name).is_dir():
            raise ValueError("项目缺少快照或处理目录，请先核实目录完整性")
    active_before = tuple(manager.active_paths())
    references, tasks, errors, metadata, evidence = _usage(manager)
    rows = []
    inventories = {}
    items = list(_items(folder))
    for kind, paths, recognized in items:
        status, reasons = "candidate", []
        files, size = 0, 0
        modified_ns = None
        try:
            for path in paths:
                item = manager._inventory(_safe(path))
                inventories[path] = item
                count, amount, _ = item
                files += count
                size += amount
                latest = max(
                    p.stat().st_mtime_ns
                    for p in ([path, *path.rglob("*")] if path.is_dir() else [path])
                )
                modified_ns = max(modified_ns or latest, latest)
            for path in paths:
                if any(_overlaps(path, Path(ref).resolve()) for ref in active_before if ref):
                    reasons.append("网页工作区仍在使用所属项目或产物")
                if any(_overlaps(path, ref) for ref in tasks):
                    reasons.append("未结束任务可能读取或写入该产物")
                for owner, refs in references:
                    # A reopened project's own folder is provenance, not every old snapshot.
                    if any(
                        _overlaps(path, ref)
                        for ref in refs
                        if not (owner == folder and ref == folder)
                    ):
                        reasons.append("当前清单、恢复起点或项目溯源仍在引用")
            if reasons:
                status = "protected"
            elif not recognized:
                status, reasons = "unknown", ["任务/批次诊断、未识别或不完整产物，继续保留"]
            else:
                reasons = ["未发现当前引用，仅列为人工审阅候选，默认保留"]
        except (OSError, ValueError, PermissionError):
            status, reasons, files, size = "unknown", ["无法安全核实内容，继续保留"], None, None
        rows.append(
            {
                "kind": kind,
                "paths": [str(p.relative_to(folder)) for p in paths],
                "status": status,
                "reasons": sorted(set(reasons)),
                "files": files,
                "bytes": size,
                "modified_ns": modified_ns,
                "complete": recognized and status != "unknown",
                "modified_at": (
                    datetime.fromtimestamp(modified_ns / 10**9, UTC).isoformat()
                    if modified_ns is not None
                    else None
                ),
            }
        )
    if tuple(manager.active_paths()) != active_before:
        errors.append("检查期间活动工作区发生变化，请重新生成计划")
    try:
        if list(_items(folder)) != items:
            errors.append("检查期间产物清单发生变化，请重新生成计划")
        if any(manager._inventory(_safe(path)) != item for path, item in inventories.items()):
            errors.append("检查期间产物发生变化，请重新生成计划")
        if _metadata_paths(manager) != metadata or any(
            file_identity(_safe(path)) != identity for path, identity in evidence.items()
        ):
            errors.append("检查期间项目引用或任务发生变化，请重新生成计划")
    except (OSError, ValueError):
        errors.append("检查结束时无法重新核实项目引用或任务，继续保留")
    if errors:
        for row in rows:
            if row["status"] == "candidate":
                row.update(status="unknown", reasons=["引用或会话状态未完整核实，继续保留"])
    _policy(rows, min_age_days=min_age_days, keep_latest=keep_latest, now_ns=now_ns)
    return {
        "project": str(folder),
        "generated_at": utc_now(),
        "read_only": True,
        "policy": "默认全部保留；显式策略只生成清理建议，不自动删除；回收区仍占用磁盘。",
        "policy_parameters": {"min_age_days": min_age_days, "keep_latest": keep_latest},
        "scope": "仅本项目 snapshots 与 processing；不包含导出、回收区及仓库外维护恢复包。",
        "warnings": errors,
        "items": rows,
        "candidate_bytes": sum(row["bytes"] for row in rows if row["status"] == "candidate"),
        "selected_bytes": sum(row["bytes"] for row in rows if row["selected_for_cleanup"]),
        "immediate_freed_bytes": 0,
    }
