# ruff: noqa: RUF001
"""Explicit XML acquisition hints; never infer a resolution reference mass."""

import json
import re
import subprocess

import numpy as np
from defusedxml import ElementTree as ET


def _xml_settings(path, max_scans=32):
    windows, resolutions, groups = [], [], {}
    count = 0
    with open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "referenceableParamGroup":
                groups[element.get("id")] = [dict(item.attrib) for item in element]
            if tag not in {"spectrum", "scan"}:
                continue
            if tag == "scan" and "msLevel" not in element.attrib:
                continue
            params = [
                item.attrib
                for item in element.iter()
                if item.tag.rsplit("}", 1)[-1] in {"cvParam", "userParam"}
            ]
            for item in element.iter():
                if item.tag.endswith("referenceableParamGroupRef"):
                    params.extend(groups.get(item.get("ref"), []))
            level = element.get("msLevel") or next(
                (p.get("value") for p in params if p.get("accession") == "MS:1000511"), None
            )
            if str(level) == "1":
                count += 1
                lower = [float(p["value"]) for p in params if p.get("accession") == "MS:1000501"]
                upper = [float(p["value"]) for p in params if p.get("accession") == "MS:1000500"]
                if lower and upper:
                    windows.append((min(lower), max(upper)))
                elif tag == "scan" and element.get("lowMz") and element.get("highMz"):
                    windows.append((float(element.get("lowMz")), float(element.get("highMz"))))
                else:
                    filters = [
                        p.get("value", "") for p in params if p.get("accession") == "MS:1000512"
                    ]
                    filters.append(element.get("filterLine", ""))
                    for text in filters:
                        match = re.search(r"\[\s*([\d.]+)\s*-\s*([\d.]+)\s*\]", text)
                        if match:
                            windows.append(tuple(map(float, match.groups())))
                for p in params:
                    name = p.get("name", "").lower()
                    if p.get("value") and (
                        p.get("accession") == "MS:1000800"
                        or name in {"orbitrap resolution", "ft resolution", "resolution"}
                    ):
                        resolutions.append(float(p["value"]))
                if element.get("resolution"):
                    resolutions.append(float(element.get("resolution")))
            element.clear()
            if count >= max_scans:
                break
    return windows, resolutions, count


def acquisition_hints(path):
    if path.suffix.lower() == ".raw":
        return raw_acquisition_hints(path)
    windows, resolutions, scans = _xml_settings(path)
    return {
        "windows": [list(v) for v in sorted(set(windows)) if 0 < v[0] < v[1]],
        "resolutions": sorted(set(v for v in resolutions if np.isfinite(v) and v > 0)),
        "ms1_scans_inspected": scans,
        "note": "采集记录的分辨率未确认参考质量，不自动视为 m/z 200 处分辨率；请核对后手动填写。",
    }


def raw_acquisition_hints(path, *, command=None, timeout=30):
    """Read bounded acquisition metadata without consuming profile point arrays."""
    from .readers.thermo_raw import ThermoRawError, reader_command

    try:
        result = subprocess.run(
            [*(command or reader_command()), "--acquisition", str(path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ThermoRawError("RAW 采集信息读取超时，请稍后重试。") from exc
    if result.returncode:
        detail = result.stderr[-4096:].decode("utf-8", errors="replace")
        raise ThermoRawError(f"RAW 采集信息读取失败：{detail}")
    try:
        if len(result.stdout) > 1_000_000:
            raise ValueError("metadata exceeds size limit")
        data = json.loads(result.stdout)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("unsupported acquisition metadata version")
        count = data["ms1_scans_inspected"]
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 32:
            raise ValueError("invalid scan count")
        windows = np.asarray(data["windows"], dtype=float)
        if windows.size == 0:
            windows = np.empty((0, 2))
        if windows.ndim != 2 or windows.shape[1] != 2:
            raise ValueError("invalid mass window shape")
        resolutions = np.asarray(data["resolutions"], dtype=float)
        if (
            not np.isfinite(windows).all()
            or (windows <= 0).any()
            or (windows[:, 0] >= windows[:, 1]).any()
            or resolutions.ndim != 1
            or not np.isfinite(resolutions).all()
            or (resolutions <= 0).any()
        ):
            raise ValueError("invalid acquisition values")
        return {
            "windows": windows.tolist(),
            "resolutions": resolutions.tolist(),
            "resolution_records": data.get("resolution_records", []),
            "ms1_scans_inspected": count,
            "note": "读取 RAW 扫描设置与分辨率附加记录；未记录的字段显示未读取到。分辨率参考质量未经确认，请核对后手动填写。",
        }
    except (ValueError, KeyError, TypeError) as exc:
        raise ThermoRawError(f"RAW 采集信息协议无效，请核对 reader 版本：{exc}") from exc
