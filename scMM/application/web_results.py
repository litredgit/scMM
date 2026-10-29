"""Precision-preserving result downloads, exports and protected saved-item management."""
# ruff: noqa: RUF001

import json
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pandas as pd

from .projects import child_path
from .result_catalog import RESULTS
from .trash import SavedItems, _references


class ResultWorkflow:
    def active_paths(self):
        # Take a stable reference snapshot without acquiring workspace locks under the manager lock.
        with self._lock:
            self._prune()
            workspaces = list(self._workspaces.values())
            openings = list(self._project_openings)
        return openings + [
            w.project.folder for w in workspaces if not w.closed and w.project is not None
        ]

    @contextmanager
    def retention_operation(self, path):
        folder = Path(path).resolve()
        with self._lock:
            if folder in self._retention_operations or folder in self.active_paths():
                from .workspace_state import WorkspaceError

                raise WorkspaceError(
                    "项目正在打开、仍在工作区使用或正在清理，请先关闭后重试", code="retention_busy"
                )
            self._retention_operations.add(folder)
        try:
            yield
        finally:
            with self._lock:
                self._retention_operations.discard(folder)

    def restore_saved(self, entry):
        manager = self.saved_items()
        record = next((r for r in manager.list_trash() if r["entry"] == entry), None)
        if record and record.get("retention_version") == 1:
            with self.retention_operation(record["path"]):
                return manager.restore(entry)
        return manager.restore(entry)

    def saved_items(self):
        return SavedItems(
            self.store,
            [r for r in self.results.roots if r.label != "项目结果"],
            active_paths=self.active_paths,
            trash_root=getattr(self, "trash_root", None),
        )

    @contextmanager
    def scoped_cleanup(self, scope):
        if scope is None:
            yield
            return
        # Refuse busy peers instead of waiting while holding the caller's lock.
        # Keep all live references stable through the final check and file move,
        # including unsaved imports from this project into a different project.
        with self._lock, ExitStack() as locks:
            for peer in self._workspaces.values():
                if not peer.lock.acquire(blocking=False):
                    raise RuntimeError("其他工作区正在执行操作 请稍后重新检查清理计划")
                locks.callback(peer.lock.release)
            yield

    def project_saved_items(self, workspace, scope):
        if scope is None:
            return self.saved_items()
        project = workspace.require_project()

        def active_paths():
            # Caller holds this workspace's lock. Other sessions protect their
            # whole project; this session protects actual unsaved references.
            paths = list(self.active_paths())
            paths.remove(project.folder)
            refs = list(_references([project.manifest, project.views], project.folder))
            refs.extend(_references({"source": project.workspace.source}, project.folder))
            for data in (project.workspace.data, project.workspace._original):
                if data is not None:
                    refs.extend(_references(dict(data.uns), project.folder))
            paths.extend(ref for ref in refs if ref != project.folder)
            for peer in self._workspaces.values():
                other = peer.project
                if peer is workspace or peer.closed or other is None:
                    continue
                paths.extend(_references([other.manifest, other.views], other.folder))
                paths.extend(_references({"source": other.workspace.source}, other.folder))
                for data in (other.workspace.data, other.workspace._original):
                    if data is not None:
                        paths.extend(_references(dict(data.uns), other.folder))
            if workspace.preview_job and not workspace.preview_job["future"].done():
                paths.append(project.folder)
            # Workers may still create or reuse any project-local cache.
            for path in (project.folder / "processing").rglob("state.json"):
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("status") not in {
                    "completed",
                    "succeeded",
                    "failed",
                    "stopped",
                    "interrupted",
                }:
                    paths.append(project.folder)
                    break
            return paths

        manager = self.saved_items()
        manager.active_paths = active_paths
        return manager

    @staticmethod
    def artifact_paths(project, scope):
        """Only recognized direct children can use the current-project cleanup gate."""
        if scope == "snapshots":
            return sorted((project.folder / "snapshots").glob("*"), reverse=True)
        if scope == "exports":
            return sorted((project.folder / "exports").glob("*.h5ad"), reverse=True)
        if scope == "previews":
            return sorted((project.folder / "processing").glob("preview-*"), reverse=True)
        if scope == "batches":
            from .project_batch import batches

            return [path.parent for path in batches(project)]
        raise ValueError("未知的项目产物类型")

    def check_artifact_path(self, workspace, scope, path):
        project = workspace.require_project()
        path = Path(path)
        if path not in self.artifact_paths(project, scope) or path.is_symlink():
            raise ValueError("请选择当前项目中可识别的对应产物")
        if scope == "previews" and not (path / "identity.json").is_file():
            raise ValueError("预览缓存不完整，保留待核实")
        return path

    def saved_artifacts(self, identity, scope):
        with self.access(identity) as workspace, self.scoped_cleanup(scope):
            project = workspace.require_project()
            manager = self.project_saved_items(workspace, scope)
            rows = []
            for path in self.artifact_paths(project, scope):
                if path.name.startswith(".") or path.name == "preview-jobs":
                    continue
                row = {"path": str(path), "name": path.name, "files": None, "bytes": None}
                try:
                    self.check_artifact_path(workspace, scope, path)
                    count, size, _ = manager._inventory(path)
                    row.update(files=count, bytes=size)
                    plan = manager.plan("项目结果", path)
                    row.update(files=plan["files"], bytes=plan["bytes"], protection="")
                except (OSError, ValueError, RuntimeError) as exc:
                    row["protection"] = str(exc)
                rows.append(row)
            return rows

    def export_dataset(self, identity, revision, root, directory, filename):
        with self.access(identity) as workspace:
            workspace.check(revision)
            path = workspace.require_project().workspace.save_h5ad(
                self.results, root, directory, filename
            )
            return {"workspace": self.view(workspace), "value": {"path": str(path)}}

    def download_content(self, identity, kind, key=""):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            state = project.workspace
            if kind == "merge_preview":
                return self.merge_preview_download(identity, key), "application/zip"
            if kind == "merge_audit":
                from .merge_audit import audit_bundle

                return audit_bundle(state, key), "application/zip"
            if kind == "time_result":
                return self.time_download(identity, key), "application/zip"
            if kind in {"quality_pdf", "report_zip"}:
                from .reporting import report_artifact

                return report_artifact(project, self.result_value, kind, key)
            if kind in RESULTS and RESULTS[kind].download.endswith(".csv"):
                return self.result_value(project, kind)["table"].to_csv(index=False).encode(
                    "utf-8"
                ), "text/csv; charset=utf-8"
            if kind == "supervised":
                return json.dumps(
                    self.result_value(project, kind),
                    ensure_ascii=False,
                    default=lambda v: v.tolist(),
                ).encode("utf-8"), "application/json"
            if kind == "matrix":
                from .matrix_export import matrix_csv

                return matrix_csv(state.require_data()), "text/csv; charset=utf-8"
            elif kind == "embedding":
                data = state.require_data()
                if key not in data.obsm:
                    raise ValueError("嵌入不存在或已失效。")
                frame = pd.DataFrame(data.obsm[key], index=data.obs_names)
            elif kind == "qc":
                frame = state.qc()["cell"]
            elif kind == "history":
                frame = pd.DataFrame(state.history())
            elif kind == "raw":
                if not workspace.raw or key not in workspace.raw["frames"]:
                    raise ValueError("请先生成该原始谱图。")
                preview = workspace.raw["preview"]
                from .preview_cache import file_identity

                if preview.open_identity != file_identity(preview.path):
                    raise ValueError("原始文件已改变，请重新打开。")
                frame = workspace.raw["frames"][key]
            elif kind == "batch_log":
                path = self.batch_path(project, key).with_name("worker.log")
                return path.read_bytes(), "text/plain; charset=utf-8"
            elif kind == "snapshot":
                reference = project.manifest["artifacts"].get("current")
                if not reference:
                    raise ValueError("当前项目尚无已保存的数据快照。")
                return child_path(project.folder, reference), "application/octet-stream"
            elif kind == "figure":
                if key not in project.views.get("figures", {}):
                    raise ValueError("图形不存在或已失效。")
                from .web_analysis import stored_figure

                return json.dumps(
                    stored_figure(project.views["figures"][key]), ensure_ascii=False
                ).encode("utf-8"), "application/json"
            else:
                raise ValueError("不支持的下载类型。")
            return frame.to_csv(index=True).encode("utf-8"), "text/csv; charset=utf-8"

    def runtime(self):
        with self._lock:
            self._prune()
            workspaces = list(self._workspaces.values())
        unsaved = 0
        busy = 0
        for workspace in workspaces:
            if not workspace.lock.acquire(blocking=False):
                busy += 1
                continue
            try:
                if not workspace.closed:
                    unsaved += bool(workspace.project and workspace.project.unsaved)
                    busy += bool(
                        workspace.preview_job and not workspace.preview_job["future"].done()
                    )
            finally:
                workspace.lock.release()
        return {"unsaved_workspaces": unsaved, "busy_workspaces": busy}
