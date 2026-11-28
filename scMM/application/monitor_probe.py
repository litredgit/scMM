"""Bounded subprocess probes; imports no scientific modules and never reads matrices."""
# ruff: noqa: RUF001

import json
import sys
from datetime import datetime
from pathlib import Path

import psutil

WORKERS = {
    "scMM.application.worker": "提取批次",
    "scMM.application.project_batch": "提取批次",
    "scMM.application.cell_preview": "细胞预览",
    "scMM.application.ion_worker": "离子归组",
    "scMM.plot._trend_worker": "趋势聚类",
}
TASK_PATHS = (
    "*/processing/*/state.json",
    "*/processing/preview-jobs/*/state.json",
    "*/state.json",
    "*/tasks/*/state.json",
    ".ion-jobs/*/job.json",
)


def worker_kind(args):
    for module, kind in WORKERS.items():
        if module in args:
            return kind
    return None


def worker_paths(args):
    return [Path(arg).resolve() for arg in args[3:] if Path(arg).is_absolute()]


def owned_by_roots(process, args, roots):
    paths = worker_paths(args)
    if any(path.is_relative_to(root) for root in roots for path in paths):
        return True
    if "scMM.plot._trend_worker" in args:
        project_root = process.environ().get("SCMM_PROJECT_ROOT")
        return bool(project_root and Path(project_root).resolve() in roots)
    return False


def read_json(path, root):
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("监控元数据路径越界")
    if path.stat().st_size > 1024**2:
        raise ValueError("监控元数据过大")
    return json.loads(path.read_text(encoding="utf-8"))


def task_scan(roots):
    tasks, incomplete, seen, pids = [], [], set(), set()
    roots = [Path(root).resolve(strict=True) for root in roots]
    for root in roots:
        # Fixed task-layout patterns avoid traversing spectra, H5AD and snapshot trees.
        candidates = set()
        for pattern in TASK_PATHS:
            for path in root.glob(pattern):
                candidates.add(path)
                if len(candidates) > 10000:
                    raise ValueError("任务记录超过监控扫描上限")
        for path in candidates:
            try:
                canonical = path.resolve(strict=True)
                if str(canonical) in seen:
                    continue
                seen.add(str(canonical))
                state = read_json(path, root)
                status = state.get("status")
                if status not in {
                    "queued",
                    "running",
                    "succeeded",
                    "completed",
                    "failed",
                    "stopped",
                    "interrupted",
                    "ready",
                    "cancelled",
                }:
                    incomplete.append("任务状态格式无法确认。")
                    continue
                request_path = path.with_name("request.json")
                request = read_json(request_path, root) if request_path.is_file() else {}
                project_folder = next(
                    (p for p in path.parents if (p / "project.json").is_file()), None
                )
                manifest = (
                    read_json(project_folder / "project.json", root) if project_folder else {}
                )
                if path.name == "job.json":
                    binding = state.get("binding")
                    project = binding.get("project") if isinstance(binding, dict) else None
                    if isinstance(project, str) and Path(project).is_absolute():
                        manifest_path = Path(project) / "project.json"
                        try:
                            canonical_manifest = manifest_path.resolve(strict=True)
                            project_root = next(
                                (base for base in roots if canonical_manifest.is_relative_to(base)),
                                None,
                            )
                            if project_root is not None:
                                binding_manifest = read_json(manifest_path, project_root)
                                if isinstance(binding_manifest, dict):
                                    manifest = binding_manifest
                        except (OSError, ValueError, RuntimeError):
                            pass  # Keep the task visible when its project is unavailable.
                created = state.get("created_at", request.get("created_at"))
                try:
                    started = (
                        datetime.fromisoformat(created).timestamp()
                        if created
                        else state.get("started_at")
                    )
                except (ValueError, TypeError):
                    started = None
                pid = state.get("pid")
                live = None
                if type(pid) is int and status in {"queued", "running"}:
                    try:
                        process = psutil.Process(pid)
                        args = process.cmdline()
                        live = any(
                            str(p) in args
                            for p in (canonical, request_path.resolve(), canonical.parent)
                        )
                        if live and (created_at := state.get("process_created_at")) is not None:
                            live = process.create_time() == created_at
                        if live:
                            pids.add(pid)
                    except psutil.Error:
                        live = False
                samples = state.get("samples", [])
                tasks.append(
                    {
                        "id": path.parent.name,
                        "project": manifest.get("name", "旧任务"),
                        "kind": "离子归组"
                        if path.name == "job.json"
                        else ("细胞预览" if "preview-jobs" in path.parts else "提取批次"),
                        "user_id": request.get("submitted_by", state.get("owner")),
                        "status": status,
                        "started_at": started,
                        "updated_at": path.stat().st_mtime,
                        "pid": pid if type(pid) is int else None,
                        "process_alive": live,
                        "completed": sum(s.get("status") == "succeeded" for s in samples),
                        "total": len(samples),
                        "message": str(state.get("message", state.get("error", "")))[:500],
                    }
                )
            except (ValueError, OSError, TypeError, AttributeError):
                incomplete.append("部分任务元数据不可读。")
    # Detached workers can outlive their API process or lose their state file.
    for process in psutil.process_iter(["pid", "cmdline"], ad_value=None):
        args = process.info["cmdline"] or []
        kind = worker_kind(args)
        if kind is None:
            continue
        try:
            owned = owned_by_roots(process, args, roots)
            if owned and process.pid not in pids:
                pids.add(process.pid)
                if kind == "趋势聚类":
                    started = process.create_time()
                    tasks.append(
                        {
                            "id": str(process.pid),
                            "project": "当前工作区",
                            "kind": kind,
                            "user_id": None,
                            "status": "running",
                            "started_at": started,
                            "updated_at": started,
                            "pid": process.pid,
                            "process_alive": True,
                            "completed": 0,
                            "total": 0,
                            "message": "",
                        }
                    )
                else:
                    incomplete.append("发现任务记录未关联的 worker，需核对。")
        except (psutil.Error, OSError):
            incomplete.append("部分 worker 身份不可读。")
    active = [t for t in tasks if t["status"] in {"queued", "running"}]
    recent = sorted(
        (t for t in tasks if t not in active), key=lambda t: t["updated_at"], reverse=True
    )[:200]
    return {"tasks": active + recent, "pids": sorted(pids), "incomplete": sorted(set(incomplete))}


def disks(roots):
    result = []
    for label, path in roots.items():
        try:
            usage = psutil.disk_usage(path)
            result.append(
                {"label": label, "total": usage.total, "free": usage.free, "used": usage.used}
            )
        except OSError:
            result.append({"label": label, "error": "存储不可用或不可读。"})
    return result


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        result = disks(request) if sys.argv[1] == "disks" else task_scan(request)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        # Paths and task-file bodies do not belong in monitoring error logs.
        print(json.dumps({"error": "监控探测失败，请核对配置目录与权限。"}))
        sys.exit(1)
