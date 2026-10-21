"""Current-matrix QC PDF and a portable, non-executable analysis report bundle."""

# ruff: noqa: RUF001
import io
import json
import re
import zipfile
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from anndata import AnnData

from .quality import quality_metrics

MAX_REPORT_VALUES = 5_000_000


def report_tables(data):
    if min(data.shape) < 1 or data.n_obs > 100_000 or data.n_obs * data.n_vars > MAX_REPORT_VALUES:
        raise ValueError(
            "QC report requires non-empty data, at most 100000 cells and 5000000 matrix values"
        )
    values = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
    if not np.isfinite(values).all():
        raise ValueError("QC report requires a finite current matrix")
    obs = data.obs.copy()
    for key in obs.columns:
        if str(key).startswith("reference_intensity_"):
            try:
                obs[key] = pd.to_numeric(obs[key], errors="raise")
            except (ValueError, TypeError) as exc:
                raise ValueError("reference intensities must be numeric or missing") from exc
            if np.isinf(obs[key].to_numpy(dtype=float, na_value=np.nan)).any():
                raise ValueError("reference intensities cannot contain infinity")
    source = obs.get("source_file", pd.Series("unknown", index=obs.index)).astype("string")
    missing = "（缺失来源）"
    while missing in set(source.dropna()):
        missing += "·"
    obs["source_file"] = source.mask(source.str.strip().eq("")).fillna(missing)
    # Share only the read-only X array; never copy unrelated historical layers/models.
    try:
        with np.errstate(over="raise", invalid="raise"):
            metrics = quality_metrics(AnnData(values, obs=obs, var=data.var.copy()))
    except FloatingPointError as exc:
        raise ValueError("current intensity scale cannot be summarized safely") from exc
    cells = metrics["cell"]
    if not np.isfinite(cells["total_intensity"]).all():
        raise ValueError("current intensity scale cannot be summarized safely")
    if "cell_id" in cells:
        renamed = "obs_cell_id"
        while renamed in cells:
            renamed += "_"
        cells = cells.rename(columns={"cell_id": renamed})
    cells.insert(0, "cell_id", data.obs_names.astype(str))
    sources = cells.groupby("source_file", sort=False, observed=True).agg(
        cells=("cell_id", "size"),
        median_total=("total_intensity", "median"),
        median_detected=("detected_features", "median"),
    )
    return {"cells": cells, "sources": sources, "zero_fraction": float(np.mean(values == 0))}


def quality_report_bytes(data, metadata, *, reports=None, tables=None):
    """Render vector distributions and paginated Chinese text; no model execution."""
    try:
        from reportlab.graphics.shapes import Drawing, Line, Rect, String
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            LongTable,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:
        raise ImportError("PDF reports require scMM[web] and reportlab") from exc
    tables = report_tables(data) if tables is None else tables
    if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    normal = ParagraphStyle(
        "scmm-report", fontName="STSong-Light", fontSize=10, leading=15, wordWrap="CJK"
    )
    heading = ParagraphStyle("scmm-heading", parent=normal, fontSize=15, leading=22, spaceAfter=8)
    story = []

    def text(value, *, title=False):
        story.append(
            Paragraph(escape(str(value)).replace("\n", "<br/>"), heading if title else normal)
        )
        story.append(Spacer(1, 5))

    def table(rows, widths=None):
        rows = [[Paragraph(escape(str(v)), normal) for v in row] for row in rows]
        item = LongTable(rows, colWidths=widths, repeatRows=1, hAlign="LEFT", splitInRow=1)
        item.setStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
            ]
        )
        story.append(item)
        story.append(Spacer(1, 10))

    text("当前数据 QC 与分析报告", title=True)
    labels = {
        "report_schema": "报告格式",
        "created_at": "生成时间（UTC）",
        "scmm_version": "软件版本",
        "project": "项目",
        "dataset_id": "数据 ID",
        "dataset_revision": "数据修订",
        "matrix": "强度矩阵",
        "source": "数据来源",
        "unsaved": "存在未保存修改",
        "loaded_project_revision": "已载入项目修订",
        "last_saved_snapshot": "上次保存快照",
        "available_results": "当前有效分析",
        "scope": "报告范围",
        "embeddings": "嵌入及附件映射",
    }
    for key, value in metadata.items():
        if key not in {"history", "figures", "omitted_figures"}:
            text(
                f"{labels.get(key, key)}: {_json_text(value) if isinstance(value, (dict, list)) else value}"
            )
    text(
        "本报告描述导出时的当前矩阵，不等同于保存项目。细胞数不等于生物重复；质量候选、细胞级相关或模型拟合不构成结构鉴定/独立验证。"
    )
    text(
        f"细胞数：{data.n_obs}；特征数：{data.n_vars}；当前矩阵零值比例：{tables['zero_fraction']:.6g}"
    )
    text("来源与当前矩阵汇总", title=True)
    sources = tables["sources"]
    limit = 500
    table(
        [
            ["来源", "细胞数", "总强度中位数", "检出特征中位数"],
            *[
                [
                    name,
                    int(row.cells),
                    f"{row.median_total:.1e}",
                    f"{row.median_detected:.1f}".rstrip("0").rstrip("."),
                ]
                for name, row in sources.head(limit).iterrows()
            ],
        ],
        [235, 60, 100, 100],
    )
    if len(sources) > limit:
        text(
            f"PDF 仅列前 {limit} 个来源；完整来源和逐细胞数值在报告 ZIP 或 QC CSV 下载中，不按 PDF 显示精度舍入。"
        )

    for column, title in (
        ("total_intensity", "细胞总强度分布"),
        ("detected_features", "细胞检出特征数分布"),
    ):
        text(title, title=True)
        counts, edges = np.histogram(tables["cells"][column], bins=40)
        drawing = Drawing(490, 145)
        maximum = max(1, int(counts.max()))
        for index, count in enumerate(counts):
            drawing.add(
                Rect(
                    25 + index * 11,
                    20,
                    10,
                    100 * int(count) / maximum,
                    fillColor=colors.HexColor("#0072B2"),
                    strokeColor=None,
                )
            )
        drawing.add(Line(25, 20, 465, 20))
        number_format = ".1e" if column == "total_intensity" else ".1f"
        drawing.add(
            String(25, 3, format(edges[0], number_format), fontName="STSong-Light", fontSize=9)
        )
        drawing.add(
            String(410, 3, format(edges[-1], number_format), fontName="STSong-Light", fontSize=9)
        )
        drawing.add(
            String(25, 128, f"最大细胞数：{maximum}；箱数：40", fontName="STSong-Light", fontSize=9)
        )
        story.append(drawing)

    reference = [name for name in tables["cells"] if str(name).startswith("reference_intensity_")]
    if reference:
        story.append(PageBreak())
        text("观测元数据中的参考强度（不重提取、不重新匹配质量）", title=True)
        rows = [["参考列", "有限细胞数", "中位数", "最小值", "最大值"]]
        for key in reference[:200]:
            values = tables["cells"][key].dropna()
            rows.append(
                [
                    key,
                    len(values),
                    *[
                        f"{value:.1e}" if np.isfinite(value) else "未定义"
                        for value in (values.median(), values.min(), values.max())
                    ],
                ]
            )
        table(rows, [225, 65, 65, 65, 65])
        if len(reference) > 200:
            text("PDF 参考列摘要限前 200 列；完整元数据在 QC CSV 和报告 ZIP 中。")
    story.append(PageBreak())
    text("处理历史与有效分析", title=True)
    history = metadata.get("history", [])
    if not history:
        text("没有可读取的处理历史；这不证明上游未预处理。")
    for step in history[-200:]:
        value = _json_text(step)
        text(
            value
            if len(value) <= 1400
            else value[:1400] + "…（PDF 摘要截断，完整参数见 history.json）"
        )
    if len(history) > 200:
        text("PDF 仅列最后 200 步；完整历史在报告 ZIP 的 history.json。")
    if reports is None:
        text("本次下载为 QC PDF；有效分析及完整参数附件请下载当前分析报告 ZIP。")
    elif not reports:
        text("当前没有有效分析结果；未为生成报告而额外运行分析。")
    for name, report in (reports or {}).items():
        text(name, title=True)
        value = _json_text(report.get("summary", {}))
        text(value[:6000] + ("…（完整值见 results.json）" if len(value) > 6000 else ""))
        if "table" in report:
            text(
                f"完整结果表 {len(report['table'])} 行，见 results/{name}.csv；PDF 不以截断摘要代替完整导出。"
            )
    text(
        "完整表和未舍入参数请使用报告 ZIP。该报告不保存可执行模型、AI 凭据或个人聊天；项目保存和维护恢复仍使用各自入口。"
    )
    target = io.BytesIO()

    def footer(canvas, doc):
        canvas.setFont("STSong-Light", 8)
        canvas.drawString(42, 25, f"scMM · {metadata.get('dataset_id', '')} · 第 {doc.page} 页")

    SimpleDocTemplate(
        target,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=42,
        title="scMM 当前数据 QC 与分析报告",
        author="scMM",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return target.getvalue()


def _portable(value):
    if isinstance(value, np.ndarray):
        return _portable(value.tolist())
    if isinstance(value, np.generic):
        return _portable(value.item())
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_portable(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported report value type: {type(value).__name__}")


def _json_text(value):
    return json.dumps(_portable(value), ensure_ascii=False, allow_nan=False)


def report_bundle(data, metadata, reports, *, figures=None):
    if any(
        not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name) is None
        for name in reports
    ):
        raise ValueError("report result names must be simple identifiers")
    tables = report_tables(data)
    metadata = dict(metadata)
    embeddings = {}
    embedding_metadata = {}
    total_values = 0
    for number, (key, matrix) in enumerate(data.obsm.items(), 1):
        shape = getattr(matrix, "shape", ())
        if len(shape) != 2 or shape[0] != data.n_obs:
            raise ValueError("report embeddings must be two-dimensional and match cells")
        total_values += shape[0] * shape[1]
        if total_values > MAX_REPORT_VALUES:
            raise ValueError(
                "report embeddings exceed 5000000 values; export individual embeddings separately"
            )
        values = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
        if not np.issubdtype(values.dtype, np.number):
            raise ValueError("report embeddings must be numeric")
        filename = f"embeddings/embedding_{number:03d}.csv"
        embeddings[filename] = pd.DataFrame(
            values,
            index=data.obs_names.copy(),
            columns=[f"dimension_{i + 1}" for i in range(shape[1])],
        )
        embeddings[filename].index.name = "cell_id"
        embedding_metadata[str(key)] = {
            "file": filename,
            "dimensions": shape[1],
            "parameters": data.uns.get(f"{key}_params"),
        }
    metadata["embeddings"] = embedding_metadata
    figure_files = {}
    figure_metadata = {}
    export_bytes = 0
    for number, (name, source) in enumerate(sorted((figures or {}).items()), 1):
        figure = _portable(source)
        filename = f"figures/figure_{number:03d}.json"
        exports = figure.get("layout", {}).get("meta", {}).pop("export_tables", {})
        files = {}
        for table_number, (title, content) in enumerate(exports.items(), 1):
            if not isinstance(content, str):
                raise ValueError("figure report tables must be CSV text")
            export_bytes += len(content.encode("utf-8"))
            if export_bytes > 64 * 1024**2:
                raise ValueError(
                    "figure report tables exceed 64 MiB; export individual figures separately"
                )
            table_file = f"figures/figure_{number:03d}_table_{table_number:03d}.csv"
            files[str(title)] = table_file
            figure_files[table_file] = content
        figure_metadata[str(name)] = {"file": filename, "tables": files}
        figure_files[filename] = _json_text(figure)
    metadata["figures"] = figure_metadata
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "report.pdf", quality_report_bytes(data, metadata, reports=reports, tables=tables)
        )
        archive.writestr(
            "metadata.json",
            _json_text({k: v for k, v in metadata.items() if k != "history"}),
        )
        archive.writestr(
            "history.json",
            _json_text(metadata.get("history", [])),
        )
        archive.writestr("cell_qc.csv", tables["cells"].to_csv(index=False))
        archive.writestr("source_qc.csv", tables["sources"].to_csv())
        for filename, content in figure_files.items():
            archive.writestr(filename, content)
        for filename, frame in embeddings.items():
            archive.writestr(filename, frame.to_csv())
        summaries = {}
        for name, report in reports.items():
            summaries[name] = report.get("summary", {})
            if "table" in report:
                archive.writestr(f"results/{name}.csv", report["table"].to_csv(index=False))
            if "correlation" in report:
                archive.writestr(f"results/{name}_correlation.csv", report["correlation"].to_csv())
        archive.writestr("results.json", _json_text(summaries))
    return target.getvalue()
