# ruff: noqa: RUF001
"""Explicit XML acquisition hints; never infer a resolution reference mass."""

import re

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
        return {
            "windows": [],
            "resolutions": [],
            "note": "当前 RAW 协议不提供采集分辨率，请核对仪器记录；未自动更改参数。",
        }
    windows, resolutions, scans = _xml_settings(path)
    return {
        "windows": [list(v) for v in sorted(set(windows)) if 0 < v[0] < v[1]],
        "resolutions": sorted(set(v for v in resolutions if np.isfinite(v) and v > 0)),
        "ms1_scans_inspected": scans,
        "note": "采集记录的分辨率未确认参考质量，不自动视为 m/z 200 处分辨率；请核对后手动填写。",
    }
