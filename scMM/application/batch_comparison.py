"""Read-only two-batch comparison using frozen requests and existing artifacts."""
# ruff: noqa: RUF001

import json

import pandas as pd
from anndata import read_h5ad

from .preview_cache import digest_file
from .project_batch import read_batch
from .projects import child_path


def compare_batches(path_a, path_b):
    if path_a == path_b:
        raise ValueError("请选择两个不同的处理批次")
    paths = (path_a, path_b)
    states = [read_batch(path) for path in paths]
    if any(state["status"] in {"queued", "running"} for state in states):
        raise ValueError("请等待两个批次结束后再比较")
    requests = [
        json.loads(path.with_name("request.json").read_text(encoding="utf-8")) for path in paths
    ]
    sources = [{s["id"]: s for s in request["samples"]} for request in requests]
    results = [{s["id"]: s for s in state["samples"]} for state in states]
    parameters, samples, frames, warnings = [], [], [], []

    def differences(scope, left, right):
        for key in sorted(left.keys() | right.keys()):
            a, b = left.get(key), right.get(key)
            parameters.append({"scope": scope, "parameter": key, "A": a, "B": b, "changed": a != b})

    global_options = [
        {
            **request["parameters"],
            **{key: request.get(key) for key in ("feature_strategy", "feature_merge_ppm")},
        }
        for request in requests
    ]
    differences("project", *global_options)
    for sample_id in dict.fromkeys([*sources[0], *sources[1]]):
        left, right = [source.get(sample_id, {}) for source in sources]
        a, b = [rows.get(sample_id, {}) for rows in results]
        known = bool(left.get("input_identity") and right.get("input_identity"))
        same_input = known and left["input_identity"] == right["input_identity"]
        identity = (
            "only_A"
            if not right
            else "only_B"
            if not left
            else "same"
            if same_input
            else "changed"
            if known
            else "unknown"
        )
        samples.append(
            {
                "sample_id": sample_id,
                "name_A": left.get("name"),
                "name_B": right.get("name"),
                "input": identity,
                "path_A": left.get("path"),
                "path_B": right.get("path"),
                "identity_A": left.get("input_identity"),
                "identity_B": right.get("input_identity"),
                "status_A": a.get("status", "missing"),
                "status_B": b.get("status", "missing"),
                "cells_A": a.get("cells"),
                "cells_B": b.get("cells"),
                "features_A": a.get("features"),
                "features_B": b.get("features"),
                "cell_difference": b["cells"] - a["cells"]
                if same_input and a.get("cells") is not None and b.get("cells") is not None
                else None,
                "error_A": a.get("error", ""),
                "error_B": b.get("error", ""),
            }
        )
        differences(sample_id, left.get("parameters", {}), right.get("parameters", {}))
        for index, (source, row) in enumerate(zip((left, right), (a, b), strict=True)):
            if row.get("status") != "succeeded":
                continue
            output = child_path(paths[index].parent, row["output"])
            try:
                expected = row.get("sha256")
                if expected and digest_file(output) != expected:
                    raise ValueError("提取产物摘要不匹配")
                from scMM.analysis.quality import quality_metrics

                data = read_h5ad(output)
                qc = quality_metrics(data)["cell"].copy()
                if expected and digest_file(output) != expected:
                    raise ValueError("提取产物在读取时改变")
                qc["cell_id"] = data.obs_names.astype(str)
                qc["sample_id"] = sample_id
                qc["sample_name"] = source.get("name", sample_id)
                qc["comparison_batch"] = "A" if index == 0 else "B"
                frames.append(qc)
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"{'A' if index == 0 else 'B'} / {sample_id}：QC 无法读取：{exc}")
        if identity == "unknown":
            warnings.append(f"{sample_id}：旧批次缺少输入身份，不能确认同一原始文件")
    return {
        "batch_A": str(path_a),
        "batch_B": str(path_b),
        "parameters": parameters,
        "samples": samples,
        "warnings": warnings,
        "qc": pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
    }
