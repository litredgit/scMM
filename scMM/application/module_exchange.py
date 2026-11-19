"""Portable, versioned module handoffs with isolated validation before publication.

The complete format wraps the existing project snapshot contract. It therefore
keeps immutable measurement roots, all views/branches, L3 evidence, preprocessing
baselines and read-only reports together rather than projecting the active matrix.
"""

# ruff: noqa: RUF001
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import stat
import zipfile
from contextlib import suppress
from copy import deepcopy
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Literal

import numpy as np
import pandas as pd
from anndata import AnnData, read_h5ad
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from scMM.file.ion_bundle import validate_hdf5_container
from scMM.ion.identity import axis_identity
from scMM.ion.semantics import value_states
from scMM.util.intensity import intensity_states

from .project_references import iter_project_artifacts
from .projects import ProjectStore, child_path, write_json
from .tasks import utc_now
from .web_projects import prepare_mapping, project_candidate
from .workbench import AnalysisWorkspace, dense

MODULES = {"extraction", "annotation", "statistics"}
METADATA_KEY = "scmm_exchange_json"
MAX_UPLOAD_BYTES = 200_000_000
MAX_EXPANDED_BYTES = 2_000_000_000
MAX_FILES = 10000


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Artifact(_Contract):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0, le=MAX_EXPANDED_BYTES)


class _ValueState(_Contract):
    space: Literal["linear_abundance", "log_abundance", "standard_score", "other", "unknown"]
    imputed: bool
    normalization: list[dict]
    history: list[dict]


class ExchangeManifest(_Contract):
    """Exact version-one wire structure; scientific table metadata stays extensible."""

    schema_version: Literal[1]
    kind: Literal["scmm_module_exchange"]
    source_module: Literal["extraction", "annotation", "statistics"]
    created_at: str = Field(min_length=1, max_length=100)
    native_project: Literal["project/project.json"]
    quantitation_available: bool
    observation_kind: Literal["cell", "sample"]
    matrix_orientation: Literal["observations_by_features"]
    missing_values: Literal["preserved_in_native_sources; active_matrix_finite"]
    feature_identity: Literal["stable_feature_id; root_and_view_mapping_in_native_catalogue"]
    intensity_unit: str = Field(min_length=1, max_length=1000)
    intensity_states: dict[str, Literal["raw", "normalized", "transformed", "unknown"]]
    value_states: dict[str, _ValueState]
    raw_spectra: Literal["external_references"]
    models: Literal["excluded"]
    complete_catalogue: bool
    files: dict[str, _Artifact] = Field(min_length=1, max_length=MAX_FILES)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value


def _manifest(value):
    try:
        return ExchangeManifest.model_validate(value).model_dump()
    except ValidationError as exc:
        raise ValueError("不支持的 scMM 模块交换协议：清单含未声明、缺少或不合法的字段。") from exc


def exchange_metadata(data):
    if data is None or METADATA_KEY not in data.uns:
        return {}
    try:
        value = json.loads(data.uns[METADATA_KEY])
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError
        return value
    except (TypeError, ValueError) as exc:
        raise ValueError("不支持或损坏的模块交换元数据。") from exc


def _validate_module(module):
    if module not in MODULES:
        raise ValueError("请选择细胞提取、特征注释或统计分析板块。")


def module_status(manager, identity, module):
    _validate_module(module)
    with manager.access(identity) as workspace:
        project = workspace.project
        data = project.workspace.data if project is not None else None
        metadata = exchange_metadata(data)
        quantitative = data is not None and data.n_obs > 0
        return {
            "module": module,
            "protocol_version": 1,
            "quantitation_available": quantitative,
            "feature_only": data is not None and data.n_obs == 0,
            "observations": data.n_obs if data is not None else 0,
            "features": data.n_vars if data is not None else 0,
            "observation_kind": metadata.get("observation_kind", "cell"),
            "imports": ["package", "h5ad", "matrix_csv"]
            + (["feature_csv"] if module == "annotation" else []),
            "exports": (
                ["package", "csv", "h5ad", "features"] if data is not None else ["package"]
            ),
            "has_catalogue": project is not None and project.ion_state is not None,
            "source": project.workspace.source if project is not None else "",
            "notice": "仅有特征表，可做质量候选注释；统计分析需要定量矩阵。"
            if data is not None and not quantitative
            else "",
        }


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def export_package(project, module):
    """Snapshot in a private directory; never save or publish the user's project."""
    _validate_module(module)
    with TemporaryDirectory(prefix="scmm-module-export-") as temporary:
        root = Path(temporary)
        proxy = project_candidate(project)
        proxy.folder = root / "project"
        proxy.folder.mkdir()
        (proxy.folder / "snapshots").mkdir()
        proxy.manifest.update(revision=0, artifacts={})
        proxy.manifest["schema_version"] = 2 if proxy.ion_state is not None else 1
        write_json(proxy.folder / "project.json", proxy.manifest)
        store = ProjectStore(root)
        store.save(proxy)
        paths = [
            proxy.folder / "project.json",
            *iter_project_artifacts(proxy.manifest, proxy.folder),
        ]
        files = {path.relative_to(root).as_posix(): path.read_bytes() for path in paths}
        data = project.workspace.data
        metadata = exchange_metadata(data)
        description = {
            "schema_version": 1,
            "kind": "scmm_module_exchange",
            "source_module": module,
            "created_at": utc_now(),
            "native_project": "project/project.json",
            "quantitation_available": data is not None and data.n_obs > 0,
            "observation_kind": metadata.get("observation_kind", "cell"),
            "matrix_orientation": "observations_by_features",
            "missing_values": "preserved_in_native_sources; active_matrix_finite",
            "feature_identity": "stable_feature_id; root_and_view_mapping_in_native_catalogue",
            "intensity_unit": metadata.get("intensity_unit", "unknown"),
            "intensity_states": intensity_states(data) if data is not None else {},
            "value_states": value_states(data) if data is not None else {},
            "raw_spectra": "external_references",
            "models": "excluded",
            "complete_catalogue": project.ion_state is not None,
            "files": {
                name: {"sha256": _sha(content), "bytes": len(content)}
                for name, content in files.items()
            },
        }
        description = _manifest(description)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _json_bytes(description))
            for name, content in files.items():
                archive.writestr(name, content)
        return stream.getvalue()


def _extract_archive(content, folder, *, max_bytes, max_files):
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("交换包超过上传大小限制。")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > max_files or sum(item.file_size for item in entries) > max_bytes:
                raise ValueError("交换包解压后超过文件数或大小限制。")
            seen, written = set(), 0
            for item in entries:
                path = PurePosixPath(item.filename)
                if (
                    not path.parts
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in item.filename
                    or ":" in item.filename
                    or item.filename.casefold() in seen
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1
                ):
                    raise ValueError("交换包包含不安全路径、重复文件或加密文件。")
                seen.add(item.filename.casefold())
                target = folder.joinpath(*path.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("交换包解压超过资源限制。")
                        output.write(chunk)
    except zipfile.BadZipFile as exc:
        raise ValueError("文件不是完整的 scMM 交换 ZIP。") from exc


def read_package(content, *, max_bytes=MAX_EXPANDED_BYTES, max_files=MAX_FILES):
    try:
        return _read_package(content, max_bytes=max_bytes, max_files=max_files)
    except (AttributeError, KeyError, TypeError, UnicodeError, OSError) as exc:
        raise ValueError("交换包结构或项目引用不完整，当前数据未改变。") from exc


def _read_package(content, *, max_bytes, max_files):
    """Return a detached native project only after the whole dependency closure passes."""
    with TemporaryDirectory(prefix="scmm-module-import-") as temporary:
        root = Path(temporary)
        _extract_archive(content, root, max_bytes=max_bytes, max_files=max_files)
        description = _manifest(json.loads((root / "manifest.json").read_text(encoding="utf-8")))
        expected = description["files"]
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        if actual != {"manifest.json", *expected}:
            raise ValueError("交换包文件清单不完整或包含未声明文件。")
        scientific_bytes = 0
        for name, record in expected.items():
            path = child_path(root, name)
            if (
                not isinstance(record, dict)
                or type(record.get("bytes")) is not int
                or path.stat().st_size != record.get("bytes")
                or _sha(path.read_bytes()) != record.get("sha256")
            ):
                raise ValueError("交换包文件大小或校验摘要不一致。")
            if path.suffix.lower() == ".h5ad":
                scientific_bytes += validate_hdf5_container(path, max_bytes=max_bytes)
                if scientific_bytes > max_bytes:
                    raise ValueError("交换包科学数组超过资源限制。")
            elif path.suffix.lower() != ".json":
                raise ValueError("交换包包含不支持的产物类型。")
        project = ProjectStore(root).open(root / "project")
        referenced = {
            p.relative_to(root).as_posix()
            for p in iter_project_artifacts(project.manifest, project.folder)
        }
        if referenced | {"project/project.json"} != set(expected):
            raise ValueError("交换包的项目引用闭包不完整。")
        data = project.workspace.data
        metadata = exchange_metadata(data)
        if description["observation_kind"] != metadata.get(
            "observation_kind", "cell"
        ) or description["intensity_unit"] != metadata.get("intensity_unit", "unknown"):
            raise ValueError("交换包声明的观测类型或强度单位与矩阵不一致。")
        if description.get("quantitation_available") is not (data is not None and data.n_obs > 0):
            raise ValueError("交换包声明的定量状态与矩阵不一致。")
        if description.get("complete_catalogue") is not (project.ion_state is not None):
            raise ValueError("交换包声明的离子目录状态不一致。")
        if description.get("intensity_states") != (
            intensity_states(data) if data is not None else {}
        ) or description.get("value_states") != (value_states(data) if data is not None else {}):
            raise ValueError("交换包的强度来源或数值空间声明与矩阵不一致。")
        project.workspace.source = "imported_module_exchange"
        if project.ion_state is not None:
            for entry in project.ion_state["branches"].values():
                entry["workspace"]["source"] = "imported_module_exchange"
        return project, description


def _read_csv(text):
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    except csv.Error as exc:
        raise ValueError("CSV 文件无法解析。") from exc
    rows = [row for row in rows if any(value.strip() for value in row)]
    if not rows or len(rows[0]) < 1 or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("CSV 不能为空，各行列数必须一致。")
    header = [value.strip() for value in rows[0]]
    if len(header) != len(set(header)) or any(not key for key in header):
        raise ValueError("CSV 列名必须非空且唯一。")
    return pd.DataFrame(rows[1:], columns=header)


def _stable_ids(values, label):
    values = pd.Index([str(value).strip() for value in values])
    if not values.is_unique or any(not value for value in values):
        raise ValueError(f"{label} ID 必须非空且唯一。")
    return values


def _metadata_table(text, index, key):
    if not text.strip():
        return pd.DataFrame(index=index)
    table = _read_csv(text)
    if key not in table:
        raise ValueError(f"配套元数据必须含 {key} 列。")
    table.index = _stable_ids(table.pop(key), key)
    if set(table.index) != set(index):
        raise ValueError(f"{key} 与矩阵的 ID 必须完整一一对应。")
    return table.loc[index].copy()


def import_matrix_csv(
    text,
    *,
    observations_csv="",
    features_csv="",
    orientation="observations_rows",
    observation_kind="cell",
    source="uploaded_matrix.csv",
):
    table = _read_csv(text)
    if table.shape[1] < 2 or table.empty:
        raise ValueError("定量矩阵至少需要一个观测和一个特征。")
    identifiers = _stable_ids(table.iloc[:, 0], "行")
    values = table.iloc[:, 1:].copy()
    values.index = identifiers
    group = None
    if orientation == "observations_columns":
        group_rows = [key for key in values.index if key.casefold() in {"group", "class", "label"}]
        if len(group_rows) > 1:
            raise ValueError("矩阵只能有一行 Group、Class 或 Label。")
        if group_rows:
            group = values.loc[group_rows[0]].copy()
            values = values.drop(group_rows)
        values = values.T
    elif orientation == "observations_rows":
        group_columns = [
            key for key in values.columns if key.casefold() in {"group", "class", "label"}
        ]
        if len(group_columns) > 1:
            raise ValueError("矩阵只能有一列 Group、Class 或 Label。")
        if group_columns:
            group = values.pop(group_columns[0])
    else:
        raise ValueError("不支持的矩阵方向。")
    obs_ids = _stable_ids(values.index, "观测")
    feature_ids = _stable_ids(values.columns, "特征")
    if min(values.shape) < 1:
        raise ValueError("定量矩阵至少需要一个观测和一个特征。")
    try:
        matrix = values.apply(pd.to_numeric, errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("矩阵含非数值或缺失值；请先明确处理，空白不会自动填零。") from exc
    if not np.isfinite(matrix).all():
        raise ValueError("矩阵必须为有限数值；缺失值与零不能自动互换。")
    obs = _metadata_table(observations_csv, obs_ids, "observation_id")
    var = _metadata_table(features_csv, feature_ids, "feature_id")
    if group is not None:
        group.index = obs_ids
        if "group" in obs and not obs["group"].astype(str).equals(group.astype(str)):
            raise ValueError("矩阵分组与配套观测元数据中的 group 不一致。")
        obs["group"] = group.astype(str)
    sample_assignment = "provided"
    if "sample" not in obs and "sample_id" not in obs:
        if observation_kind == "sample":
            obs["sample"] = obs.index.astype(str)
            sample_assignment = "observation_ids"
        else:
            obs["sample"] = "External data"
            sample_assignment = "single_external_source"
    if "mz" in var:
        var["mz"] = _mz_values(var["mz"])
    else:
        with suppress(ValueError):
            var["mz"] = _mz_values(pd.Series(feature_ids))
    data = AnnData(matrix, obs=obs, var=var)
    data.uns[METADATA_KEY] = json.dumps(
        {
            "schema_version": 1,
            "kind": "quantitative_matrix",
            "feature_only": False,
            "quantitation_available": True,
            "observation_kind": observation_kind,
            "source_kind": "external_matrix",
            "source_name": source,
            "matrix_orientation": orientation,
            "intensity_unit": "unknown",
            "sample_assignment": sample_assignment,
            "biological_replication": "unknown",
            "missing_value_policy": "reject_missing_preserve_zero",
        }
    )
    AnalysisWorkspace._validate(data)
    return data


def _mz_values(values):
    try:
        result = pd.to_numeric(values, errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("m/z 必须为有限正数。") from exc
    if not np.isfinite(result).all() or (result <= 0).any():
        raise ValueError("m/z 必须为有限正数。")
    return result


def import_feature_csv(text, *, source="uploaded_features.csv", observation_kind="cell"):
    table = _read_csv(text)
    if "mz" not in table or table.empty:
        raise ValueError("独立特征表必须含非空 mz 列，可选 feature_id 与其他注释字段。")
    table.index = _stable_ids(
        table.pop("feature_id")
        if "feature_id" in table
        else [f"feature_{n + 1}" for n in range(len(table))],
        "特征",
    )
    table["mz"] = _mz_values(table["mz"])
    data = AnnData(
        np.empty((0, len(table)), dtype=np.float64),
        obs=pd.DataFrame(index=pd.Index([], dtype=str)),
        var=table,
    )
    data.uns[METADATA_KEY] = json.dumps(
        {
            "schema_version": 1,
            "kind": "feature_only",
            "feature_only": True,
            "quantitation_available": False,
            "observation_kind": observation_kind,
            "source_kind": "external_feature_table",
            "source_name": source,
            "intensity_unit": "not_available",
        }
    )
    AnalysisWorkspace._validate(data)
    return data


def _uploaded_bytes(values):
    try:
        content = base64.b64decode(values.get("file_base64", ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("上传内容编码不完整。") from exc
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件为空或超过大小限制。")
    return content


def _safe_import_samples(project, manager):
    for sample in project.samples:
        if not sample.get("path"):
            sample["result_only"] = True
            continue
        try:
            manager.storage.resolve_raw_file(sample["storage"], sample["path"])
        except (OSError, ValueError, KeyError, PermissionError):
            sample["source_reference"] = {
                "path": sample["path"],
                "storage": sample.get("storage", ""),
            }
            sample.update(path="", storage="exchange", result_only=True)


def import_exchange(manager, identity, module, values):
    _validate_module(module)
    kind = values["format"]
    if kind == "feature_csv" and module != "annotation":
        raise ValueError("独立特征表请从特征注释板块导入；统计分析需要定量矩阵。")

    def action(workspace):
        project = workspace.project
        if kind == "package":
            imported, description = read_package(_uploaded_bytes(values))
            if (
                module == "statistics"
                and imported.workspace.data is not None
                and imported.workspace.data.n_obs == 0
            ):
                raise ValueError("该交换包仅有特征表，不能作为统计分析输入。")
            candidate = project_candidate(project)
            candidate.workspace = imported.workspace
            candidate.ion_state = imported.ion_state
            candidate.saved_reports = imported.saved_reports
            candidate.report_token = candidate.workspace.token
            candidate.views = imported.views
            preserved = {
                key: candidate.manifest[key]
                for key in (
                    "id",
                    "name",
                    "description",
                    "revision",
                    "created_at",
                    "saved_at",
                )
            }
            candidate.manifest = deepcopy(imported.manifest)
            candidate.manifest.update(preserved)
            candidate.manifest["artifacts"] = {}
            candidate.manifest["schema_version"] = 2 if candidate.ion_state is not None else 1
            candidate.manifest["module_exchange"] = {
                "schema_version": 1,
                "source_module": description["source_module"],
                "imported_at": utc_now(),
                "source_project_id": imported.manifest["id"],
            }
            _safe_import_samples(candidate, manager)
        else:
            content = None
            if kind == "h5ad":
                content = _uploaded_bytes(values)
                with TemporaryDirectory(prefix="scmm-exchange-h5ad-") as temporary:
                    path = Path(temporary) / "input.h5ad"
                    path.write_bytes(content)
                    validate_hdf5_container(path, max_bytes=MAX_EXPANDED_BYTES)
                    data = read_h5ad(path)
                if "scmm_source_view_json" in data.uns:
                    from scMM.file.ion_view import import_compound_source

                    candidate = project_candidate(project)
                    import_compound_source(candidate, content)
                    candidate.dirty = True
                    workspace.project = candidate
                    return
                AnalysisWorkspace._validate(data)
                axis_identity(data.obs_names)
                axis_identity(data.var_names)
                if METADATA_KEY not in data.uns:
                    data.uns[METADATA_KEY] = json.dumps(
                        {
                            "schema_version": 1,
                            "kind": "quantitative_matrix",
                            "feature_only": False,
                            "quantitation_available": True,
                            "observation_kind": values["observation_kind"],
                            "source_kind": "external_h5ad",
                            "source_name": values["filename"],
                            "intensity_unit": "unknown",
                            "biological_replication": "unknown",
                        }
                    )
                if module == "statistics" and data.n_obs == 0:
                    raise ValueError("该 H5AD 仅有特征表，统计分析需要定量矩阵。")
            else:
                text = values.get("matrix_csv", "")
                if not text:
                    try:
                        text = _uploaded_bytes(values).decode("utf-8-sig")
                    except UnicodeError as exc:
                        raise ValueError("CSV 必须使用 UTF-8 编码。") from exc
                if kind == "feature_csv":
                    data = import_feature_csv(
                        text, source=values["filename"], observation_kind=values["observation_kind"]
                    )
                else:
                    data = import_matrix_csv(
                        text,
                        observations_csv=values.get("observations_csv", ""),
                        features_csv=values.get("features_csv", ""),
                        orientation=values["orientation"],
                        observation_kind=values["observation_kind"],
                        source=values["filename"],
                    )
            candidate = project_candidate(project)
            if data.n_obs == 0:
                candidate.ion_state = None
                candidate.workspace = AnalysisWorkspace()
                candidate.workspace.replace(data, source=f"uploaded:{values['filename']}")
                candidate.manifest.update(schema_version=1, artifacts={})
                candidate.manifest["samples"] = []
                candidate.manifest.pop("sample_mapping", None)
                candidate.manifest.pop("sample_column", None)
                candidate.views = {}
            else:
                from .data_views import replace_measurement

                replace_measurement(
                    candidate,
                    data,
                    source=f"uploaded:{values['filename']}",
                    origin_kind="imported_feature",
                )
                candidate.manifest["samples"] = []
                candidate.manifest.pop("sample_mapping", None)
                prepare_mapping(candidate, "exchange")
                # An independent import must not remap inactive branches merely
                # because an unrelated source reused the same display sample name.
                candidate.workspace.sync_sample_metadata(
                    candidate.samples,
                    candidate.manifest.get("sample_mapping"),
                    candidate.manifest.get("sample_column", "sample"),
                )
            candidate.saved_reports = {}
            candidate.views.pop("figures", None)
            candidate.manifest["module_exchange"] = {
                "schema_version": 1,
                "source_module": "external",
                "imported_at": utc_now(),
                "format": kind,
            }
        candidate.validate_samples()
        candidate.dirty = True
        workspace.discard_views()
        workspace.project = candidate

    return manager.mutate(identity, values["revision"], action, operation="module_import")


def _feature_csv(data):
    frame = data.var.copy()
    frame.index.name = "feature_id"
    return frame.to_csv(float_format="%.17g").encode("utf-8-sig")


def _csv_package(project, module):
    data = project.workspace.require_features()
    obs = data.obs.copy()
    obs.index.name = "observation_id"
    matrix = pd.DataFrame(dense(data.X), index=data.obs_names, columns=data.var_names)
    matrix.index.name = "observation_id"
    metadata = {
        "schema_version": 1,
        "kind": "scmm_matrix_tables",
        "source_module": module,
        "quantitation_available": data.n_obs > 0,
        "matrix_orientation": "observations_rows",
        "observation_kind": exchange_metadata(data).get("observation_kind", "cell"),
        "source": project.workspace.source,
        "preprocessing_history": project.workspace.history(),
        "intensity_provenance": data.uns.get("scmm_intensity_provenance_json", ""),
        "value_semantics": data.uns.get("scmm_value_semantics_json", ""),
        "limitations": "Active matrix only. Use scmm-exchange.zip for complete roots, branches, evidence, baselines and reports.",
        "missing_values": "Metadata columns are text on CSV import; empty metadata fields represent blank text. Native packages preserve metadata nulls and types. Matrix values are finite and zero is preserved.",
        "intensity_unit": exchange_metadata(data).get("intensity_unit", "unknown"),
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("matrix.csv", matrix.to_csv(float_format="%.17g").encode("utf-8-sig"))
        archive.writestr("observations.csv", obs.to_csv().encode("utf-8-sig"))
        archive.writestr("features.csv", _feature_csv(data))
        archive.writestr("metadata.json", _json_bytes(metadata))
    return stream.getvalue()


def export_exchange(manager, identity, module, revision, format="package"):
    _validate_module(module)
    with manager.access(identity) as workspace:
        workspace.check(revision)
        project = workspace.require_project()
        if format == "package":
            return (
                export_package(project, module),
                "application/zip",
                f"scmm-{module}.scmm-exchange.zip",
            )
        if format == "csv":
            return _csv_package(project, module), "application/zip", f"scmm-{module}-tables.zip"
        data = project.workspace.require_features()
        if format == "features":
            return _feature_csv(data), "text/csv; charset=utf-8", f"scmm-{module}-features.csv"
        if format != "h5ad":
            raise ValueError("不支持的导出格式。")
        with TemporaryDirectory(prefix="scmm-module-h5ad-") as temporary:
            from .storage import StorageCatalog, StorageRoot

            storage = StorageCatalog([StorageRoot("export", Path(temporary))])
            path = project.workspace.save_h5ad(storage, "export", ".", "dataset.h5ad")
            return path.read_bytes(), "application/octet-stream", f"scmm-{module}.h5ad"
