"""Describe saved content without loading matrices or changing retention."""
# ruff: noqa: RUF001

import re
from datetime import UTC, datetime

from .projects import child_path


class ResultCatalog:
    def __init__(self, store, root):
        self.store = store
        self.root = root
        self._projects = {}

    def project(self, path):
        for folder in (path, *path.parents):
            if not folder.is_relative_to(self.root):
                break
            if folder not in self._projects:
                try:
                    self._projects[folder] = self.store._manifest(folder)
                except (OSError, ValueError, KeyError):
                    self._projects[folder] = None
            if self._projects[folder] is not None:
                return folder, self._projects[folder]
        return None, None

    def describe(self, path):
        folder, manifest = self.project(path)
        role, detail, internal = "目录" if path.is_dir() else "独立 H5AD", "", False
        protected = ""
        project_path = None
        revision = None
        if manifest:
            project_path = str(folder) if folder.parent == self.store.root else None
            revision = manifest["revision"]
            relative = path.relative_to(folder)
            artifacts = {
                key: child_path(folder, value)
                for key, value in manifest["artifacts"].items()
                if isinstance(value, str)
            }
            if path == folder:
                role = "项目（推荐打开）"
                detail = "打开项目可恢复当前矩阵、完整预处理起点和只读图/报告。"
            elif path == artifacts.get("current"):
                role, internal = "当前快照", True
                protected = "项目清单正在引用，不能单独删除。"
                detail = "上次保存的当前矩阵；完整恢复请打开所属项目。"
            elif path == artifacts.get("baseline"):
                role, internal = "恢复起点", True
                protected = "完整恢复所需，不能单独删除。"
                detail = "完整预处理起点，不是最新处理结果。"
            elif relative.parts[0] == "snapshots":
                internal = True
                match = re.search(r"_r(\d+)(?:_|$)", "/".join(relative.parts))
                revision = int(match[1]) if match else None
                if any(
                    path == value.parent or path in value.parents for value in artifacts.values()
                ):
                    role, protected = "当前快照目录", "包含项目清单引用的文件，不能单独删除。"
                else:
                    role = "历史快照"
                    detail = "旧保存产物；删除前仍需检查项目引用和活动任务。"
            elif relative.parts[0] == "processing":
                internal = True
                match = re.search(r"_r(\d+)(?:_|$)", "/".join(relative.parts))
                revision = int(match[1]) if match else None
                if any(part.startswith("preview") for part in relative.parts):
                    role = "预览缓存 / 任务"
                    detail = "用于细胞预览、复用或诊断，不代表已审核纳入的数据。"
                else:
                    role = "逐样本提取 / 批次"
                    detail = "提取与审核的中间产物；可能仍被项目溯源引用。"
            elif relative.parts[0] == "exports":
                role = "独立导出目录" if path.is_dir() else "独立导出 H5AD"
                detail = "主动导出的独立矩阵；不是完整项目备份，删除前检查引用。"
        elif path.is_dir() and (path / ".meta").is_file():
            role = "处理结果目录"
            detail = "CLI/API 标准结果目录；可整体导入。"
        elif not path.is_dir():
            detail = "外部或独立矩阵文件；来源与处理状态需核对内容，删除前检查引用。"
        if manifest and folder.parent != self.store.root:
            protected = "属于其他项目根，请到所属环境打开或管理；本环境仅可导入矩阵。"
        return {
            "role": role,
            "detail": detail,
            "internal": internal,
            "project_name": manifest["name"] if manifest else None,
            "project_path": project_path,
            "revision": revision,
            "modified_at": manifest["saved_at"]
            if manifest and path == folder
            else datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            "protection": protected,
        }

    def latest(self, directory, entries):
        """Prefer saved user data, never baseline/cache/partial sample files."""
        candidates = [
            entry for entry in entries if not entry["directory"] and not entry["internal"]
        ]
        folder, manifest = self.project(directory)
        projects = [(folder, manifest)] if manifest else []
        for entry in entries:
            if entry["role"] == "项目（推荐打开）":
                projects.append(self.project(self.root / entry["path"]))
        for project_folder, project_manifest in projects:
            exports = child_path(project_folder, "exports")
            if exports.is_dir():
                for export in exports.glob("*.h5ad"):
                    if (
                        export.is_symlink()
                        or not export.is_file()
                        or not export.resolve().is_relative_to(self.root)
                    ):
                        continue
                    candidates.append(
                        {
                            "name": export.name,
                            "path": str(export.relative_to(self.root)),
                            "directory": False,
                            "bytes": export.stat().st_size,
                            **self.describe(export),
                        }
                    )
            reference = project_manifest["artifacts"].get("current")
            if not reference:
                continue
            path = child_path(project_folder, reference)
            if not path.is_file() or path.is_symlink() or not path.is_relative_to(self.root):
                continue
            candidates.append(
                {
                    "name": path.name,
                    "path": str(path.relative_to(self.root)),
                    "directory": False,
                    "bytes": path.stat().st_size,
                    **self.describe(path),
                    "modified_at": project_manifest["saved_at"],
                }
            )

        def timestamp(row):
            try:
                value = datetime.fromisoformat(row["modified_at"])
                return value.replace(tzinfo=UTC) if value.tzinfo is None else value
            except ValueError:
                return datetime.min.replace(tzinfo=UTC)

        return max(candidates, key=timestamp, default=None)
