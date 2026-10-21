"""Private signed all-workspace maintenance checkpoints with verified model restore."""

# ruff: noqa: RUF001
import hashlib
import json
import os
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

from .projects import Project, write_json
from .state_codec import StateCodec
from .workbench import AnalysisWorkspace
from .workspace_state import BrowserWorkspace


class RecoveryStore:
    def __init__(self, config):
        # Stable private location, independent of configurable scientific/cache roots.
        self.root = Path(config.path).parent / (Path(config.path).stem + ".recovery")
        if self.root.is_symlink():
            raise ValueError("Recovery directory cannot be a symbolic link")
        self.root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.key = self.root / "key"
        if not self.key.exists():
            descriptor = os.open(self.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(Fernet.generate_key())
        if self.key.is_symlink() or self.key.stat().st_mode & 0o077:
            raise ValueError("Recovery key must be a private ordinary file")
        self.cipher = Fernet(self.key.read_bytes())
        self.lock = threading.RLock()

    def snapshot(self, manager):
        with self.lock, manager._lock, ExitStack() as stack:
            workspaces = list(manager._workspaces.values())
            for workspace in sorted(workspaces, key=lambda w: w.id):
                if not workspace.lock.acquire(blocking=False):
                    raise ValueError("工作区仍在计算，请等待任务结束。")
                stack.callback(workspace.lock.release)
                if workspace.preview_job and not workspace.preview_job["future"].done():
                    raise ValueError("仍有原始预览任务，请等待结束。")
            import shutil
            import sys

            import numpy as np
            import pandas as pd
            import psutil
            from anndata import AnnData
            from scipy import sparse

            seen = set()

            def estimate(value):
                if id(value) in seen:
                    return 0
                seen.add(id(value))
                if isinstance(value, np.ndarray):
                    return value.nbytes
                if sparse.issparse(value):
                    return value.data.nbytes + value.indices.nbytes + value.indptr.nbytes
                if isinstance(value, pd.DataFrame):
                    return int(value.memory_usage(deep=True, index=True).sum())
                if isinstance(value, AnnData):
                    return (
                        estimate(value.X)
                        + estimate(dict(value.layers))
                        + estimate(value.obs)
                        + estimate(value.var)
                        + estimate(dict(value.uns))
                        + estimate(dict(value.obsm))
                    )
                if isinstance(value, dict):
                    return sum(estimate(k) + estimate(v) for k, v in value.items())
                if isinstance(value, (list, tuple)):
                    return sum(estimate(v) for v in value)
                if isinstance(value, str):
                    return sys.getsizeof(value)
                from scMM.analysis.supervised import SupervisedAnalyzer

                if isinstance(value, SupervisedAnalyzer):
                    return estimate(vars(value))
                return 128

            estimated = sum(
                estimate(w.client_state if hasattr(w, "client_state") else {})
                + estimate(vars(w.project.workspace) if w.project else {})
                + estimate(w.project.views if w.project else {})
                for w in workspaces
            )
            required = max(64 * 1024**2, estimated * 3)
            if shutil.disk_usage(self.root).free < required:
                raise ValueError("维护暂存磁盘空间不足，请先释放空间；尚未更新服务。")
            if psutil.virtual_memory().available < estimated * 1.5 + 64 * 1024**2:
                raise ValueError("维护恢复验证的可用内存不足，请减少并行工作区后重试。")
            directory = self.root / uuid4().hex
            directory.mkdir(mode=0o700)
            codec = StateCodec(directory)
            records = []
            try:
                for workspace in workspaces:
                    record = {
                        "raw": None,
                        "preview_job": None,
                        "id": workspace.id,
                        "owner_id": workspace.owner_id,
                        "revision": workspace.revision,
                        "client_state": getattr(workspace, "client_state", {}),
                        "project": None,
                    }
                    if workspace.raw:
                        record["raw"] = {
                            "sample_id": workspace.raw["sample_id"],
                            "identity": workspace.raw["preview"].open_identity,
                            "frames": workspace.raw["frames"],
                        }
                    if workspace.preview_job:
                        job = workspace.preview_job
                        record["preview_job"] = {k: v for k, v in job.items() if k != "future"}
                        record["preview_job"]["completed_error"] = (
                            str(job["future"].exception()) if job["future"].exception() else None
                        )
                        record["preview_job"]["completed_result"] = (
                            None if job["future"].exception() else job["future"].result()
                        )
                    project = workspace.project
                    if project is not None:
                        record["project"] = {
                            key: getattr(project, key)
                            for key in (
                                "folder",
                                "manifest",
                                "saved_reports",
                                "views",
                                "dirty",
                                "saved_token",
                                "report_token",
                            )
                        }
                        record["project"]["workspace"] = dict(vars(project.workspace))
                    records.append(record)
                state = codec.encode(
                    {"workspaces": records, "pages": getattr(manager, "maintenance_pages", {})}
                )
                # Verify every data artifact and every trained pipeline before publication.
                restored = codec.decode(state)
                if len(restored["workspaces"]) != len(records):
                    raise ValueError("恢复数量不一致。")
                encrypted = self.cipher.encrypt(
                    json.dumps(state, ensure_ascii=False, allow_nan=False).encode()
                )
                (directory / "state.enc").write_bytes(encrypted)
                manifest = {
                    "schema": 1,
                    "id": directory.name,
                    "created": time.time(),
                    "workspaces": len(records),
                    "files": {
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in directory.iterdir()
                    },
                    "verified": True,
                }
                sealed = self.cipher.encrypt(json.dumps(manifest).encode())
                (directory / "manifest.enc").write_bytes(sealed)
                for path in directory.iterdir():
                    os.chmod(path, 0o600)
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
                write_json(self.root / "current.json", {"id": directory.name})
                return manifest
            except BaseException:
                import shutil

                shutil.rmtree(directory)
                raise

    def restore(self, manager):
        pointer = self.root / "current.json"
        if not pointer.exists():
            return 0
        identity = json.loads(pointer.read_text())["id"]
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Invalid recovery ID")
        directory = self.root / identity
        manifest = json.loads(self.cipher.decrypt((directory / "manifest.enc").read_bytes()))
        if manifest["schema"] != 1 or manifest["id"] != identity or not manifest["verified"]:
            raise ValueError("Invalid recovery manifest")
        for name, digest in manifest["files"].items():
            if (
                Path(name).name != name
                or (directory / name).is_symlink()
                or hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest
            ):
                raise ValueError("Recovery checksum failed")
        state = json.loads(self.cipher.decrypt((directory / "state.enc").read_bytes()))
        payload = StateCodec(directory).decode(state)
        records = payload["workspaces"]
        candidate = {}
        for record in records:
            workspace = BrowserWorkspace(
                id=record["id"], owner_id=record["owner_id"], revision=record["revision"]
            )
            workspace.client_state = record["client_state"]
            if record["project"] is not None:
                fields = record["project"]
                attributes = fields.pop("workspace")
                # Project-root changes retain original folder references; no file migration.
                project = Project(**fields)
                project.workspace = AnalysisWorkspace()
                project.workspace.__dict__.update(attributes)
                if project.workspace.data is not None:
                    project.workspace._validate(project.workspace.data)
                import numpy as np

                from scMM.analysis.supervised import SupervisedAnalyzer

                from .workbench import dense

                for entry in project.workspace.results.values():
                    model = entry[1]
                    if isinstance(model, SupervisedAnalyzer):
                        data = project.workspace.require_data()
                        if (
                            model.feature_names != data.var_names.astype(str).tolist()
                            or not model.obs_names.isin(data.obs_names).all()
                        ):
                            raise ValueError("Recovered model dataset identity differs")
                        source = data[model.obs_names, :]
                        matrix = source.X if model.layer is None else source.layers[model.layer]
                        if not np.array_equal(model.X, dense(matrix)):
                            raise ValueError("Recovered model training matrix differs")
                workspace.project = project
            if record.get("raw"):
                from .raw_preview import RawPreviewService

                raw = record["raw"]
                sample = next(s for s in workspace.project.samples if s["id"] == raw["sample_id"])
                try:
                    preview = RawPreviewService(manager.storage).open(
                        sample["storage"], sample["path"]
                    )
                    if preview.open_identity != raw["identity"]:
                        raise ValueError("Recovery raw source identity differs")
                    workspace.raw = {
                        "sample_id": raw["sample_id"],
                        "preview": preview,
                        "frames": raw["frames"],
                    }
                except (OSError, ValueError, KeyError):
                    # Keep the complete scientific state, while refusing a changed/revoked raw input.
                    workspace.client_state["raw_unavailable"] = (
                        "原始目录授权或文件身份已改变，原始图保留为只读历史；请重新打开授权文件。"
                    )
                    views = workspace.client_state.get("views", {})
                    if "raw" in views:
                        views["raw"]["opened"] = ""
            if record.get("preview_job"):
                from concurrent.futures import Future

                job = record["preview_job"]
                future = Future()
                error = job.pop("completed_error")
                result = job.pop("completed_result")
                if error:
                    future.set_exception(ValueError(error))
                else:
                    future.set_result(result)
                workspace.preview_job = {**job, "future": future}
            candidate[workspace.id] = workspace
        with manager._lock:
            if manager._workspaces:
                raise ValueError("Cannot restore over live workspaces")
            if hasattr(manager, "store"):
                manager.store.recovered_folders.update(
                    w.project.folder.resolve() for w in candidate.values() if w.project is not None
                )
            manager._workspaces.update(candidate)
            manager.maintenance_pages = payload["pages"]
        for workspace in candidate.values():
            manager.publish_ai(workspace)
        pointer.rename(self.root / "restored.json")
        return len(candidate)
