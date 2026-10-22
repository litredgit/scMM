"""Precision-preserving result downloads, exports and protected saved-item management."""
# ruff: noqa: RUF001

import json
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from .projects import child_path
from .result_catalog import RESULTS
from .trash import SavedItems


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
                raise RuntimeError("项目正在打开、仍在工作区使用或正在清理，请先关闭后重试")
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
                frame = state.require_data().to_df()
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
