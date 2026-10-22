"""Read-only processed merge inputs, immutable identities and bounded resource checks."""
# ruff: noqa: RUF001

import hashlib
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
from scipy import sparse

from .preview_cache import digest_file, file_identity
from .workbench import read_dataset

MAX_VALUES = 20_000_000


def extra_values(value):
    if isinstance(value, (np.ndarray, pd.DataFrame)) or sparse.issparse(value):
        return int(np.prod(value.shape))
    if isinstance(value, dict):
        return sum(extra_values(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(extra_values(item) for item in value)
    return 1


def check_size(data):
    if (
        data.X is None
        or min(data.shape) < 1
        or data.n_obs > 20000
        or data.n_vars > 10000
        or data.n_obs * data.n_vars > 5_000_000
    ):
        raise ValueError("合并输入工程上限：2 万细胞、500 万矩阵值，且两轴非空")
    if not data.obs_names.is_unique or not data.var_names.is_unique:
        raise ValueError("合并输入需要唯一稳定细胞/特征 ID")
    for frame in (data.obs, data.var):
        if not frame.columns.is_unique or any(not isinstance(key, str) for key in frame.columns):
            raise ValueError("元数据列名须为唯一字符串")
    total = data.X.size if not sparse.issparse(data.X) else np.prod(data.shape)
    total += sum(np.prod(value.shape) for value in data.layers.values())
    if data.raw is not None:
        if not data.raw.var_names.is_unique:
            raise ValueError("raw 的稳定特征 ID 不唯一，不能静默重命名或混合")
        total += np.prod(data.raw.shape)
    total += extra_values(dict(data.uns))
    if total > MAX_VALUES:
        raise ValueError("输入 X/层/raw/元数据超过 2000 万存储值工程上限")
    return int(total)


def identity(data):
    """Hash values/types/axes; never pickle, execute metadata or mutate the input."""
    digest = hashlib.sha256()

    def feed(value, depth=0):
        if depth > 64:
            raise ValueError("合并元数据嵌套过深")
        if sparse.issparse(value):
            value = value.tocsr(copy=True)
            feed((value.shape, value.data, value.indices, value.indptr), depth + 1)
        elif isinstance(value, pd.Categorical):
            feed((value.codes, value.categories.tolist(), value.ordered), depth + 1)
        elif isinstance(value, pd.Series):
            feed(value.to_frame(), depth + 1)
        elif isinstance(value, pd.Index):
            feed((value.tolist(), value.name), depth + 1)
        elif isinstance(value, pd.DataFrame):
            feed(
                (
                    list(value.index),
                    list(value.columns),
                    value.index.name,
                    [str(t) for t in value.dtypes],
                ),
                depth + 1,
            )
            for column in value:
                series = value[column]
                if isinstance(series.dtype, pd.CategoricalDtype):
                    feed((series.cat.categories.tolist(), series.cat.ordered), depth + 1)
            digest.update(pd.util.hash_pandas_object(value, index=True).values.tobytes())
        elif isinstance(value, np.ndarray):
            feed((str(value.dtype), value.shape), depth + 1)
            if value.dtype.hasobject:
                feed(value.tolist(), depth + 1)
            else:
                digest.update(np.ascontiguousarray(value).tobytes())
        elif isinstance(value, dict):
            for key in sorted(value):
                feed((key, value[key]), depth + 1)
        elif isinstance(value, (list, tuple)):
            digest.update(str(len(value)).encode())
            for item in value:
                feed(item, depth + 1)
        elif isinstance(value, np.generic):
            feed(value.item(), depth + 1)
        elif value is pd.NA or value is pd.NaT:
            digest.update(b"missing")
        elif isinstance(value, (date, datetime)):
            feed(value.isoformat(), depth + 1)
        elif isinstance(value, bytes):
            digest.update(b"bytes:" + value)
        elif value is None or isinstance(value, (str, int, float, bool)):
            digest.update(json.dumps(value, ensure_ascii=False).encode())
            digest.update(b";")
        else:
            raise ValueError(f"不支持的合并元数据类型：{type(value).__name__}")

    feed(
        {
            "X": data.X,
            "obs": data.obs,
            "var": data.var,
            "layers": dict(data.layers),
            "uns": dict(data.uns),
        }
    )
    if data.raw is not None:
        feed((data.raw.X, data.raw.var))
    return digest.hexdigest()


def files_identity(storage, specification):
    path = storage.resolve(specification["root"], specification["path"])
    paths = (
        [path]
        if path.is_file()
        else [
            path / name
            for name in (
                ".meta",
                "data.csv",
                "peak_meta.csv",
                "feature_meta.csv",
                "feature_snr.csv",
            )
            if (path / name).exists()
        ]
    )
    if not paths:
        raise ValueError("请选择独立 H5AD 或 CSV 结果目录")
    if any(p.stat().st_size > 256 * 1024**2 for p in paths):
        raise ValueError("单输入文件超过 256 MiB 同步工程上限")
    result = []
    for selected in paths:
        resolved = storage.resolve(specification["root"], selected)
        before = file_identity(resolved)
        sha = digest_file(resolved)
        if file_identity(resolved) != before:
            raise ValueError("输入在身份核对中改变，请重新选择")
        result.append({**before, "sha256": sha})
    return result


def load_inputs(manager, project, specifications):
    result = []
    seen = set()
    seen_physical = set()
    total_values = 0
    total_bytes = 0
    for index, spec in enumerate(specifications):
        if spec["kind"] == "current":
            if "current" in seen:
                raise ValueError("当前工作区只能选择一次")
            seen.add("current")
            data = project.workspace.require_data()
            baseline = project.workspace._original
            before = {
                "current": identity(data),
                "baseline": identity(baseline),
                "token": list(project.workspace.token),
            }
            scope = "当前工作区完整起点"
            label = project.manifest["name"]
        else:
            path = manager.results.resolve(spec["root"], spec["path"])
            if str(path) in seen:
                raise ValueError("同一输入路径不能重复或通过别名重复选择")
            physical = (path.stat().st_dev, path.stat().st_ino)
            if physical in seen_physical:
                raise ValueError("同一输入不能通过硬链接或别名重复选择")
            seen_physical.add(physical)
            seen.add(str(path))
            before = files_identity(manager.results, spec)
            total_bytes += sum(item["size"] for item in before)
            if total_bytes > 512 * 1024**2:
                raise ValueError("合并输入文件总计超过 512 MiB 同步工程上限")
            if path.is_file() and path.suffix.lower() == ".h5ad":
                import h5py

                counts = []
                with h5py.File(path, "r") as handle:
                    handle.visititems(
                        lambda name, node, counts=counts: (
                            counts.append(int(node.size))
                            if isinstance(node, h5py.Dataset)
                            else None
                        )
                    )
                if sum(counts) + total_values > MAX_VALUES:
                    raise ValueError("H5AD 解码规模超过 2000 万存储值工程门限，未装载大矩阵")
            data = read_dataset(manager.results, spec["root"], spec["path"], trust_pickle=False)
            if files_identity(manager.results, spec) != before:
                raise ValueError("输入在读取中改变，未使用混合版本")
            baseline = data
            scope = "独立结果自身（不推断完整项目原起点）"
            label = path.name
        total_values += check_size(data)
        if baseline is not data:
            total_values += check_size(baseline)
        if total_values > MAX_VALUES:
            raise ValueError("来源当前矩阵及起点合计超过 2000 万存储值工程门限")
        result.append(
            {
                "id": f"m{index}",
                "spec": spec,
                "data": data,
                "baseline": baseline,
                "identity": before,
                "scope": scope,
                "label": label,
            }
        )
    return result


def recheck(manager, project, inputs):
    for entry in inputs:
        if entry["spec"]["kind"] == "current":
            now = {
                "current": identity(project.workspace.data),
                "baseline": identity(project.workspace._original),
                "token": list(project.workspace.token),
            }
        else:
            now = files_identity(manager.results, entry["spec"])
        if now != entry["identity"]:
            raise ValueError("合并输入已替换或改变，请重新预览；当前工作区未修改")
