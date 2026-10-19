"""Publication export and lossless, self-describing plot-data archives."""

import base64
import csv
import io
import json
import re
import zipfile

import numpy as np


def arrays(value):
    if isinstance(value, dict):
        if "bdata" in value and "dtype" in value:
            dtype = np.dtype(value["dtype"])
            if dtype.kind not in "iufb" or dtype.itemsize > 8:
                raise ValueError("Unsupported numeric plot array")
            result = np.frombuffer(base64.b64decode(value["bdata"], validate=True), dtype=dtype)
            if value.get("shape"):
                result = result.reshape(tuple(int(v.strip()) for v in value["shape"].split(",")))
            return arrays(result.tolist())
        return {key: arrays(item) for key, item in value.items()}
    if isinstance(value, list):
        return [arrays(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def data_archive(figure):
    figure = arrays(figure)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("figure.json", json.dumps(figure, ensure_ascii=False, allow_nan=False))
        metadata = figure.get("layout", {}).get("meta") or {}
        archive.writestr(
            "parameters.json", json.dumps(metadata, ensure_ascii=False, allow_nan=False)
        )
        for i, trace in enumerate(figure.get("data", [])):
            columns = {
                key: trace[key]
                for key in ("x", "y", "z", "text", "customdata", "labels", "values")
                if isinstance(trace.get(key), list)
            }
            for key in ("color", "size"):
                value = trace.get("marker", {}).get(key)
                if isinstance(value, list):
                    columns[f"marker_{key}"] = value
            if not columns:
                continue
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            if trace.get("type") == "heatmap":
                writer.writerow(["feature_id", "column_id", "display_value"])
                for row, values in enumerate(trace.get("z", [])):
                    for column, value in enumerate(values):
                        writer.writerow([trace["y"][row], trace["x"][column], value])
            else:
                writer.writerow(list(columns))
                for row in range(max(map(len, columns.values()))):
                    values = [
                        items[row] if row < len(items) else None for items in columns.values()
                    ]
                    writer.writerow(
                        [
                            json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                            for v in values
                        ]
                    )
            archive.writestr(f"trace_{i + 1}.csv", buffer.getvalue())
        for name, table in metadata.get("export_tables", {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}(?:\.csv)?", name):
                raise ValueError("Invalid plot table name")
            archive.writestr(name if name.endswith(".csv") else f"{name}.csv", table)
    return output.getvalue()


def publication_pdf(svg, width_mm, height_mm):
    """Convert the browser's actual SVG to vector PDF; prohibit external resources."""
    from pathlib import Path

    from defusedxml import ElementTree
    from matplotlib import get_data_path
    from reportlab.graphics import renderPDF
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from svglib.svglib import svg2rlg

    if len(svg.encode()) > 32 * 1024**2:
        raise ValueError("SVG exceeds export size limit")
    root = ElementTree.fromstring(svg, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("Expected an SVG document")
    for count, element in enumerate(root.iter(), 1):
        if count > 500_000 or element.tag.rsplit("}", 1)[-1].lower() in {"script", "foreignobject"}:
            raise ValueError("Unsupported SVG content")
        for key, value in element.attrib.items():
            name = key.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or "javascript:" in value.lower():
                raise ValueError("Active SVG content is not supported")
            if name == "href" and not (
                value.startswith("#")
                or value.startswith(("data:image/png;base64,", "data:image/jpeg;base64,"))
            ):
                raise ValueError("External SVG resources are not supported")
            for target in re.findall(r"url\(\s*['\"]?([^)'\"]+)", value, re.I):
                if not target.startswith("#"):
                    raise ValueError("External SVG resources are not supported")
        if element.tag.rsplit("}", 1)[-1] == "style" and re.search(
            r"@import|url\(", element.text or "", re.I
        ):
            raise ValueError("External SVG styles are not supported")
    family = "scMM-Sans"
    if family not in pdfmetrics.getRegisteredFontNames():
        fonts = Path(get_data_path()) / "fonts/ttf"
        for name, filename in (
            (family, "DejaVuSans.ttf"),
            (family + "-Bold", "DejaVuSans-Bold.ttf"),
            (family + "-Oblique", "DejaVuSans-Oblique.ttf"),
            (family + "-BoldOblique", "DejaVuSans-BoldOblique.ttf"),
        ):
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
        pdfmetrics.registerFontFamily(
            family,
            normal=family,
            bold=family + "-Bold",
            italic=family + "-Oblique",
            boldItalic=family + "-BoldOblique",
        )
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in {"text", "tspan"}:
            font = (
                "STSong-Light"
                if re.search(r"[\u3400-\u9fff]", "".join(element.itertext()))
                else family
            )
            element.set("font-family", font)
            style = re.sub(r"font-family\s*:[^;]+;?", "", element.get("style", ""))
            element.set("style", style + f";font-family:{font}")
    from svglib.fonts import FontMap

    font_map = FontMap()
    font_map.register_font(family, str(Path(get_data_path()) / "fonts/ttf/DejaVuSans.ttf"))
    font_map._map["STSong-Light"] = {
        "svg_family": "STSong-Light",
        "svg_weight": "normal",
        "svg_style": "normal",
        "rlgFont": "STSong-Light",
        "exact": True,
    }
    from xml.etree.ElementTree import register_namespace

    register_namespace("", "http://www.w3.org/2000/svg")
    drawing = svg2rlg(io.BytesIO(ElementTree.tostring(root)), font_map=font_map)
    if drawing is None or not drawing.width or not drawing.height:
        raise ValueError("SVG has no drawable dimensions")
    width, height = width_mm * 72 / 25.4, height_mm * 72 / 25.4
    drawing.scale(width / drawing.width, height / drawing.height)
    drawing.width, drawing.height = width, height
    return renderPDF.drawToString(drawing)
