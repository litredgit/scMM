"""Project and sample operations using the service's existing transaction gate."""
# ruff: noqa: RUF001

import json
from copy import copy, deepcopy
from io import StringIO
from uuid import uuid4

import pandas as pd

from .identity import actor
from .result_catalog import (
    INDEPENDENT_PLOTS,
    REPORT_PLOTS,
    RESULT_PLOTS,
    project_result_identities,
    rebind_figure_identity,
    related_results,
    stale_metadata_results,
)
from .workbench import read_dataset
from .workspace_state import WorkspaceError


def project_candidate(project):
    """Copy mutable data/annotations before importing or synchronizing metadata."""
    candidate = copy(project)
    candidate.manifest = deepcopy(project.manifest)
    candidate.saved_reports = deepcopy(project.saved_reports)
    candidate.views = deepcopy(project.views)
    candidate.workspace = copy(project.workspace)
    candidate.workspace.results = dict(project.workspace.results)
    candidate.workspace._result_identities = dict(project.workspace._result_identities)
    if project.workspace.data is not None:
        candidate.workspace.data = project.workspace.data.copy()
        candidate.workspace._original = project.workspace._original.copy()
    return candidate


def sync_metadata(project):
    """Invalidate reports and saved plots using their recorded data dependencies."""
    before = set(project.workspace.results)
    previous_token = project.workspace.token
    previous_embeddings = (
        set(project.workspace.data.obsm) if project.workspace.data is not None else set()
    )
    changed = project.workspace.sync_sample_metadata(
        project.samples,
        project.manifest.get("sample_mapping"),
        project.manifest.get("sample_column", "sample"),
    )
    if not changed:
        if previous_token != project.workspace.token:
            for key, source in list(project.views.get("figures", {}).items()):
                try:
                    figure = json.loads(source) if isinstance(source, str) else source
                except (TypeError, ValueError):
                    continue
                if rebind_figure_identity(
                    figure,
                    project.workspace,
                    previous_token=previous_token,
                    kind=key,
                    identities=project_result_identities(project),
                ):
                    project.views["figures"][key] = figure
            project.report_token = project.workspace.token
        return
    stale = before - set(project.workspace.results)
    stale.update(stale_metadata_results(project.saved_reports, changed, readonly=True))
    stale = related_results(stale)
    for name in stale:
        project.saved_reports.pop(name, None)
    for name in stale:
        for figure in RESULT_PLOTS.get(name, ()):
            project.views.get("figures", {}).pop(figure, None)
    for key in INDEPENDENT_PLOTS:
        figure = project.views.get("figures", {}).get(key)
        if figure:
            metadata = figure["layout"]["meta"]
            if set(metadata.get("observation_dependencies", [])) & changed:
                project.views["figures"].pop(key)
            else:
                rebind_figure_identity(
                    figure,
                    project.workspace,
                    previous_token=previous_token,
                    kind=key,
                    identities=project_result_identities(project),
                )
    for key in REPORT_PLOTS:
        if key in project.views.get("figures", {}):
            source = project.views["figures"][key]
            try:
                figure = json.loads(source) if isinstance(source, str) else source
            except (TypeError, ValueError):
                # Opaque legacy views remain stored, without asserting their identity.
                continue
            rebind_figure_identity(
                figure,
                project.workspace,
                previous_token=previous_token,
                kind=key,
                identities=project_result_identities(project),
            )
            project.views["figures"][key] = figure
    removed_embeddings = previous_embeddings - set(project.workspace.require_data().obsm)
    if removed_embeddings:
        for key, source in list(project.views.get("figures", {}).items()):
            try:
                figure = json.loads(source) if isinstance(source, str) else source
            except (TypeError, ValueError):
                continue
            if not isinstance(figure, dict):
                continue
            if figure.get("layout", {}).get("meta", {}).get("embedding") in removed_embeddings:
                project.views["figures"].pop(key)
    project.report_token = project.workspace.token


def prepare_mapping(project, storage_label):
    data = project.workspace.require_data()
    source = project.manifest.get("sample_column")
    if source not in data.obs:
        source = next(
            (key for key in ("sample", "sample_id", "source_file") if key in data.obs), None
        )
    if source is None:
        project.manifest.pop("sample_column", None)
        project.manifest.pop("sample_mapping", None)
        return
    project.manifest["sample_column"] = source
    names = data.obs[source].dropna().astype(str).unique().tolist()
    if not project.samples:
        for name in names:
            rows = data.obs.loc[data.obs[source].astype(str).eq(name)]
            values = {
                key: str(rows[key].iloc[0])
                if key in rows
                and rows[key].nunique(dropna=False) == 1
                and pd.notna(rows[key].iloc[0])
                else ""
                for key in ("group", "subject", "batch")
            }
            project.samples.append(
                {
                    "id": uuid4().hex,
                    "name": name,
                    "path": "",
                    "storage": storage_label,
                    "parameters": None,
                    "result_only": True,
                    "metadata_unresolved": [
                        key
                        for key in ("group", "subject", "batch")
                        if key in rows and rows[key].nunique(dropna=False) > 1
                    ],
                    **values,
                }
            )
    matches = {sample["name"]: sample["id"] for sample in project.samples}
    # A newly imported dataset must not inherit a mapping from an unrelated import.
    project.manifest["sample_mapping"] = {name: matches[name] for name in names if name in matches}


class ProjectWorkflow:
    def create_project(self, identity, revision, name):
        def action(workspace):
            project = self.store.create(name, self.defaults)
            workspace.discard_views()
            workspace.project = project

        return self.mutate(
            identity, revision, action, require_project=False, operation="create_project"
        )

    def open_project(self, identity, revision, path):
        def action(workspace):
            folder = self.store._folder(path).resolve()
            with self._lock:
                if folder in self._retention_operations:
                    raise RuntimeError("项目正在执行缓存清理或恢复，请稍后重新打开")
                self._project_openings[folder] = self._project_openings.get(folder, 0) + 1
            try:
                project = self.store.open(folder)
                with self._lock:
                    workspace.discard_views()
                    workspace.project = project
            finally:
                with self._lock:
                    remaining = self._project_openings[folder] - 1
                    if remaining:
                        self._project_openings[folder] = remaining
                    else:
                        del self._project_openings[folder]

        return self.mutate(
            identity, revision, action, require_project=False, operation="open_project"
        )

    def close_project(self, identity, revision):
        def action(workspace):
            workspace.discard_views()
            workspace.project = None

        return self.mutate(
            identity, revision, action, require_project=False, operation="close_project"
        )

    def edit_project(self, identity, revision, name, description):
        def action(workspace):
            if not name.strip():
                raise ValueError("项目名称不能为空。")
            workspace.project.manifest.update(name=name.strip(), description=description)
            workspace.project.dirty = True

        return self.mutate(identity, revision, action)

    def add_samples(self, identity, revision, root, paths):
        def action(workspace):
            candidate = project_candidate(workspace.project)
            candidate.add_files(self.storage, root, paths)
            candidate.validate_samples()
            workspace.project = candidate

        return self.mutate(identity, revision, action)

    def _update_samples(self, identity, revision, update):
        def action(workspace):
            candidate = project_candidate(workspace.project)
            update(candidate)
            candidate.validate_samples()
            sync_metadata(candidate)
            candidate.dirty = True
            workspace.project = candidate

        return self.mutate(identity, revision, action)

    def edit_samples(self, identity, revision, edits):
        def update(candidate):
            lookup = {sample["id"]: sample for sample in candidate.samples}
            ids = [edit["id"] for edit in edits]
            if len(ids) != len(set(ids)) or set(ids) - lookup.keys():
                raise ValueError("样本 ID 重复或不属于当前项目。")
            for edit in edits:
                sample = lookup[edit["id"]]
                sample.update(
                    {key: str(value).strip() for key, value in edit.items() if key != "id"}
                )
                sample["metadata_unresolved"] = []

        return self._update_samples(identity, revision, update)

    def remove_samples(self, identity, revision, ids):
        def update(candidate):
            if set(ids) - {sample["id"] for sample in candidate.samples}:
                raise ValueError("请选择当前项目中的样本。")
            candidate.manifest["samples"] = [
                sample for sample in candidate.samples if sample["id"] not in ids
            ]

        return self._update_samples(identity, revision, update)

    def import_csv(self, identity, revision, text):
        def update(candidate):
            frame = pd.read_csv(StringIO(text.lstrip("\ufeff")), dtype=str, keep_default_na=False)
            if (
                "name" not in frame
                or set(frame.columns) - {"name", "group", "subject", "batch"}
                or frame.name.duplicated().any()
            ):
                raise ValueError("CSV 必须含唯一 name 列，仅支持 name/group/subject/batch。")
            samples = {sample["name"]: sample for sample in candidate.samples}
            if set(frame.name) - samples.keys():
                raise ValueError("CSV 中存在项目未添加的样本名称。")
            for _, row in frame.iterrows():
                sample = samples[row["name"]]
                sample.update(row.to_dict())
                sample["metadata_unresolved"] = [
                    key for key in sample.get("metadata_unresolved", []) if key not in frame.columns
                ]

        return self._update_samples(identity, revision, update)

    def relocate(self, identity, revision, sample_id, root, path):
        def update(candidate):
            resolved = self.storage.resolve_raw_file(root, path)
            sample = next((s for s in candidate.samples if s["id"] == sample_id), None)
            if sample is None:
                raise ValueError("请选择当前项目中的样本。")
            if any(s["id"] != sample_id and s["path"] == str(resolved) for s in candidate.samples):
                raise ValueError("该文件已关联其他样本。")
            sample.update(path=str(resolved), storage=root, result_only=False)
            for key in ("preview", "auto_mz_range", "range_initialized"):
                sample.pop(key, None)

        return self._update_samples(identity, revision, update)

    def import_dataset(self, identity, revision, root, path, trust_pickle):
        if trust_pickle and actor.get() is not None:
            raise WorkspaceError(
                "网页不支持导入可执行 pickle，请离线转换为 H5AD。", code="unsafe_import", status=403
            )

        def action(workspace):
            data = read_dataset(self.results, root, path, trust_pickle=trust_pickle)
            candidate = project_candidate(workspace.project)
            candidate.workspace.replace(data, source=str(self.results.resolve(root, path)))
            prepare_mapping(candidate, self.storage.roots[0].label)
            candidate.validate_samples()
            sync_metadata(candidate)
            candidate.saved_reports = {}
            candidate.views.pop("figures", None)
            candidate.dirty = True
            workspace.project = candidate

        return self.mutate(identity, revision, action, operation="import_dataset")

    def mapping(self, identity, source_key=None):
        with self.access(identity) as workspace:
            project = workspace.require_project()
            data = project.workspace.require_data()
            source_key = source_key or project.manifest.get("sample_column", "")
            if source_key and source_key not in data.obs:
                raise ValueError("样本来源字段不存在。")
            names = (
                []
                if not source_key
                else data.obs[source_key].dropna().astype(str).unique().tolist()
            )
            mapping = project.manifest.get("sample_mapping", {})
            valid_ids = {sample["id"] for sample in project.samples}
            rows = []
            for name in names:
                selected = mapping.get(name, "")
                if "sample_id" in data.obs:
                    linked = (
                        data.obs.loc[data.obs[source_key].astype(str).eq(name), "sample_id"]
                        .astype(str)
                        .unique()
                        .tolist()
                    )
                    if len(linked) == 1 and linked[0] in valid_ids:
                        selected = linked[0]
                rows.append({"value": name, "sample_id": selected if selected in valid_ids else ""})
            return {
                "source_key": source_key,
                "columns": list(map(str, data.obs.columns)),
                "rows": rows,
            }

    def map_samples(self, identity, revision, source_key, mapping):
        def update(candidate):
            data = candidate.workspace.require_data()
            if source_key not in data.obs:
                raise ValueError("样本来源字段不存在。")
            names = set(data.obs[source_key].dropna().astype(str))
            if set(mapping) - names or set(mapping.values()) - {s["id"] for s in candidate.samples}:
                raise ValueError("映射包含未知的结果样本或项目样本。")
            candidate.manifest.update(sample_column=source_key, sample_mapping=mapping)
            # Explicit remapping must take precedence over previous sample IDs.
            for dataset in (candidate.workspace.data, candidate.workspace._original):
                if "sample_id" not in dataset.obs:
                    dataset.obs["sample_id"] = ""
                values = dataset.obs[source_key].astype(str)
                selected = values.isin(mapping)
                dataset.obs.loc[selected, "sample_id"] = values.loc[selected].map(mapping)

        return self._update_samples(identity, revision, update)

    def save(self, identity, revision):
        def action(workspace):
            try:
                self.store.save(workspace.project)
            except RuntimeError as exc:
                if "another session" in str(exc):
                    raise WorkspaceError(
                        "项目已被其他会话保存，请重新打开后操作。", code="save_conflict"
                    ) from exc
                raise

        return self.mutate(identity, revision, action, operation="save")
