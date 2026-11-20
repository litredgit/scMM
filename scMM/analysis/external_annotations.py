# ruff: noqa: RUF001
"""Explicit annotation alignment and auditable spectral matches; no identity assertions."""

import hashlib
import io
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from scMM.ion.evidence import parse_text_spectra


def read_table(content, *, format="csv", header=True, transpose=False):
    if len(content) > 10_000_000:
        raise ValueError("注释表超过大小限制。")
    if format not in {"csv", "tsv"}:
        raise ValueError("请选择 CSV 或 TSV。")
    frame = pd.read_csv(
        io.StringIO(content),
        sep="\t" if format == "tsv" else ",",
        dtype=str,
        header=0 if header else None,
        keep_default_na=False,
    )
    if transpose:
        frame = frame.set_index(frame.columns[0]).T.reset_index()
    frame.columns = frame.columns.astype(str)
    if not frame.columns.is_unique:
        raise ValueError("注释表字段名不能重复。")
    return frame


def align_annotations(
    data,
    frame,
    *,
    mapping,
    source_key,
    target_key="feature_id",
    ppm=5.0,
    mode="key",
    row_positions=None,
):
    if not mapping or len(set(mapping.values())) != len(mapping) or not all(mapping.values()):
        raise ValueError("请选择字段映射，目标字段不得重复或为空。")
    protected = {
        "mz",
        "feature_id",
        "zero_fraction",
        "isotope_order",
        "isotope_parent",
        "deisotope_role",
    }
    if any(
        k in protected or k.startswith(("scmm_", "ion_", "feature_keep_")) for k in mapping.values()
    ):
        raise ValueError("不能覆盖科学字段、稳定编号或筛选标签；请使用新的注释字段名。")
    if set(mapping) - set(frame):
        raise ValueError("导入字段不存在。")
    rows = []
    positions = []
    if row_positions is not None and (
        len(set(row_positions)) != len(row_positions)
        or any(i < 0 or i >= len(frame) for i in row_positions)
    ):
        raise ValueError("导入行号无效。")
    selected = set(range(len(frame)) if row_positions is None else row_positions)
    if mode == "position":
        if len(frame) != data.n_vars:
            raise ValueError("显式按顺序导入时，表格行数必须等于当前特征数。")
        matches = [[i] if i in selected else [] for i in range(data.n_vars)]
    elif mode == "key":
        if source_key not in frame:
            raise ValueError("请选择导入匹配字段。")
        if target_key != "feature_id" and target_key not in data.var:
            raise ValueError("当前特征匹配字段不存在。")
        observed = data.var_names if target_key == "feature_id" else data.var[target_key]
        if target_key == "mz":
            observed = np.asarray(observed, float)
            masses = pd.to_numeric(frame[source_key], errors="coerce").to_numpy(float)
            valid = np.flatnonzero(np.isfinite(masses) & (masses > 0))
            matches = [
                list(valid[np.abs(m - masses[valid]) / masses[valid] * 1e6 <= ppm])
                for m in observed
            ]
        else:
            keys = frame[source_key].astype(str).str.strip().to_numpy()
            matches = [
                list(np.flatnonzero((keys == str(m).strip()) & (keys != ""))) for m in observed
            ]
        matches = [[i for i in ids if i in selected] for ids in matches]
    else:
        raise ValueError("必须显式选择按键或按顺序匹配。")
    for feature, matched in zip(data.var_names, matches, strict=True):
        rows.append(
            {
                "feature_id": str(feature),
                "status": "unmatched"
                if not matched
                else "matched"
                if len(matched) == 1
                else "ambiguous",
                "source_rows": json.dumps([int(i) + 1 for i in matched]),
                **{
                    target: frame.iloc[matched[0]][column] if len(matched) == 1 else ""
                    for column, target in mapping.items()
                },
            }
        )
        positions.append(matched[0] if len(matched) == 1 else -1)
    return pd.DataFrame(rows), np.asarray(positions) >= 0


def write_annotations(data, table, matched, *, mapping, clear_unmatched=False):
    if (table.status == "ambiguous").any():
        raise ValueError("存在一对多匹配；请修正表格或匹配键后再应用。")
    result = data.copy()
    for target in mapping.values():
        values = (
            result.var[target].astype(object).copy()
            if target in result.var and not clear_unmatched
            else pd.Series("", index=result.var_names, dtype=object)
        )
        values.iloc[np.flatnonzero(matched)] = table.loc[matched, target].to_numpy()
        result.var[target] = values
    return result


def fragment_match(observed, reference, ppm):
    a = np.asarray(observed, float).reshape(-1, 2)
    b = np.asarray(reference, float).reshape(-1, 2)
    if not len(a) or not len(b) or a[:, 1].sum() <= 0 or b[:, 1].sum() <= 0:
        return None, []
    a = a[np.argsort(a[:, 0])]
    b = b[np.argsort(b[:, 0])]
    pairs = []
    for j, (mz, _) in enumerate(b):
        lo, hi = np.searchsorted(
            a[:, 0], [mz * (1 - ppm * 1e-6), mz * (1 + ppm * 1e-6)], side="left"
        )
        # Inclusive high boundary.
        hi = np.searchsorted(a[:, 0], mz * (1 + ppm * 1e-6), side="right")
        if len(pairs) + hi - lo > 200000:
            raise ValueError("碎片质量匹配组合过多，请先整理谱图。")
        for i in range(lo, hi):
            pairs.append((abs(a[i, 0] - mz), i, j))
    used_a = set()
    used_b = set()
    matches = []
    for _, i, j in sorted(pairs):
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        matches.append(
            {
                "observed_mz": float(a[i, 0]),
                "reference_mz": float(b[j, 0]),
                "ppm_error": float((a[i, 0] / b[j, 0] - 1) * 1e6),
                "observed_intensity": float(a[i, 1]),
                "reference_intensity": float(b[j, 1]),
            }
        )
    score = sum(
        np.sqrt(r["observed_intensity"] * r["reference_intensity"]) for r in matches
    ) / np.sqrt(a[:, 1].sum() * b[:, 1].sum())
    return float(score), matches


def _metadata(spectrum):
    return {k.lower().replace(" ", "").replace("_", ""): v for k, v in spectrum["metadata"].items()}


def precursor(spectrum):
    meta = _metadata(spectrum)
    value = meta.get("pepmass", meta.get("precursormz", meta.get("parent", "")))
    try:
        number = float(str(value).split()[0])
    except (ValueError, IndexError):
        return None
    return number if np.isfinite(number) and number > 0 else None


def spectrum_polarity(spectrum):
    metadata = _metadata(spectrum)
    polarity = str(metadata.get("ionmode", metadata.get("polarity", ""))).strip().lower()
    if polarity in {"positive", "pos", "+"}:
        return "positive"
    if polarity in {"negative", "neg", "-"}:
        return "negative"
    charge = str(metadata.get("charge", "")).strip()
    if charge.endswith("+") or (charge and charge[0] != "-" and charge.isdigit()):
        return "positive"
    if charge.endswith("-") or charge.startswith("-"):
        return "negative"
    return None


def msms_search(
    data,
    *,
    measured,
    library,
    measured_format="mgf",
    library_format="mgf",
    precursor_ppm=10.0,
    fragment_ppm=20.0,
    minimum_score=0.5,
    minimum_matches=3,
    sample_pool,
    polarity,
    collision_energy="",
    instrument="",
):
    if not sample_pool.strip():
        raise ValueError("请填写样本池和证据适用范围。")
    observed = parse_text_spectra(measured, format=measured_format)
    references = parse_text_spectra(library, format=library_format)
    if len(observed) * len(references) > 1_000_000:
        raise ValueError("谱库组合超过上限，请按前体质量拆分输入。")
    if "mz" not in data.var:
        raise ValueError("当前变量轴没有 m/z；请在测量特征视图搜索，再显式关联候选证据。")
    identities = {
        k: hashlib.sha256(v.encode()).hexdigest()
        for k, v in [("measured", measured), ("library", library)]
    }
    masses = data.var.mz.to_numpy(float)
    rows = []
    budget = 0
    for oi, spectrum in enumerate(observed):
        if spectrum_polarity(spectrum) not in {None, polarity}:
            raise ValueError("实测谱极性与声明极性不一致。")
        mass = precursor(spectrum)
        if mass is None:
            raise ValueError(f"实测谱 {oi + 1} 缺少有效前体 m/z。")
        features = np.flatnonzero(np.abs(masses - mass) / mass * 1e6 <= precursor_ppm)
        for ri, reference in enumerate(references):
            if spectrum_polarity(reference) not in {None, polarity}:
                continue
            refmass = precursor(reference)
            if refmass is None:
                raise ValueError(f"参考谱 {ri + 1} 缺少有效前体 m/z。")
            if abs(mass - refmass) / refmass * 1e6 > precursor_ppm:
                continue
            budget += len(spectrum["peaks"]) * len(reference["peaks"])
            if budget > 20_000_000:
                raise ValueError("MS/MS 搜索组合超过上限，请缩小谱库或拆分输入。")
            score, matches = fragment_match(spectrum["peaks"], reference["peaks"], fragment_ppm)
            metadata = _metadata(reference)
            measured_meta = _metadata(spectrum)
            # Retain each scan and each candidate, including failed matches.
            for position in features:
                rows.append(
                    {
                        "feature_id": str(data.var_names[position]),
                        "candidate_id": f"{identities['library']}:{ri}",
                        "name": metadata.get("name", metadata.get("title", f"library:{ri + 1}")),
                        "measured_scan": measured_meta.get(
                            "scans", measured_meta.get("title", str(oi + 1))
                        ),
                        "library_scan": ri + 1,
                        "measured_index": oi,
                        "precursor_mz": mass,
                        "library_precursor_mz": refmass,
                        "score": score,
                        "matched_fragments": len(matches),
                        "passes_threshold": bool(
                            score is not None
                            and score >= minimum_score
                            and len(matches) >= minimum_matches
                        ),
                        "fragments_json": json.dumps(matches),
                        "sample_pool": sample_pool,
                        "polarity": polarity,
                        "collision_energy": collision_energy,
                        "instrument": instrument,
                        "scope": "pool_evidence_not_individual_cell_identity",
                    }
                )
    columns = [
        "feature_id",
        "candidate_id",
        "name",
        "measured_scan",
        "library_scan",
        "measured_index",
        "precursor_mz",
        "library_precursor_mz",
        "score",
        "matched_fragments",
        "passes_threshold",
        "fragments_json",
        "sample_pool",
        "polarity",
        "collision_energy",
        "instrument",
        "scope",
    ]
    table = pd.DataFrame(rows, columns=columns)
    figure = go.Figure(
        go.Scatter(
            x=table.matched_fragments,
            y=table.score,
            mode="markers",
            customdata=table[["feature_id", "name"]].to_numpy(),
            hovertemplate="Feature: %{customdata[0]}<br>Candidate: %{customdata[1]}<br>Matched fragments: %{x}<br>Similarity: %{y}<extra></extra>",
        )
    )
    figure.update_layout(
        title="MS/MS candidate evidence",
        xaxis_title="Matched fragments",
        yaxis_title="Square-root intensity cosine",
        meta={
            "notes": [
                "每条实测扫描与参考候选独立保留；分数不是概率。池化 MS/MS 不证明逐细胞身份；未命中或缺失证据不能视为排除候选。"
            ],
            "source_sha256": identities,
            "scope": sample_pool,
            "spectra": {"measured": observed, "library": references},
            "match_rows": rows,
            "export_tables": {"candidates": table.to_csv(index=False)},
        },
    )
    return figure
