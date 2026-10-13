"""Shared display formatting; exported numerical values are never rounded."""

from copy import deepcopy
from html import escape

import pandas as pd
import panel as pn
import plotly.graph_objects as go

from scMM.plot.presentation import (
    count_number as count_number,
)
from scMM.plot.presentation import (
    feature_label as feature_label,
)
from scMM.plot.presentation import (
    mass_label as mass_label,
)
from scMM.plot.presentation import (
    ordinary_number as ordinary_number,
)
from scMM.plot.presentation import (
    probability_number as probability_number,
)
from scMM.plot.presentation import (
    qc_file_table as qc_file_table,
)
from scMM.plot.presentation import (
    style_figure as style_figure,
)

from .help import configure_help
from .layout import CONTROL_BUTTON_STYLE, FIELD_STYLE, style_button


class QCDataFrame(pn.pane.DataFrame):
    """Format mixed QC metrics on a display copy, retaining the numerical object."""

    def _transform_object(self, obj):
        if not isinstance(obj, pd.DataFrame) or "metric" not in obj:
            return super()._transform_object(obj)
        displayed = obj.copy()
        intensity = obj["metric"].str.contains("intensity|abundance|强度", case=False, na=False)
        for column in ("mean", "median", "std", "min", "max"):
            if column not in obj:
                continue
            displayed[column] = [
                self.na_rep
                if pd.isna(value)
                else f"{value:.3e}"
                if scientific
                else count_number(value)
                for value, scientific in zip(obj[column], intensity, strict=True)
            ]
        grouped = {"source_file", "reference_mz", "cell_count"} <= set(obj.columns)
        if not grouped:
            return super()._transform_object(displayed)
        # Merge by the original full path, never by the visible basename.
        sources = obj.attrs.get("source_paths", obj.source_file.tolist())
        html = '<table class="dataframe panel-df scmm-qc"><thead><tr>'
        html += "".join(f"<th>{escape(str(c))}</th>" for c in obj.columns) + "</tr></thead><tbody>"
        start = 0
        while start < len(obj):
            end = start + 1
            while end < len(obj) and sources[end] == sources[start]:
                end += 1
            for index in range(start, end):
                html += "<tr>"
                for column in obj.columns:
                    if column in ("source_file", "reference_mz", "cell_count") and index != start:
                        continue
                    value = displayed.iloc[index][column]
                    text = self.na_rep if pd.isna(value) else str(value)
                    if column == "cell_count" and not pd.isna(value):
                        text = str(int(value))
                    attrs = (
                        f' rowspan="{end - start}"'
                        if column in ("source_file", "reference_mz", "cell_count")
                        else ""
                    )
                    if column == "source_file":
                        attrs += f' title="{escape(str(sources[index]), quote=True)}"'
                    html += f"<td{attrs}>{escape(text)}</td>"
                html += "</tr>"
            start = end
        html += "</tbody></table>"
        return {"object": escape(html)}


LEGEND_POSITIONS = {
    "图右侧": "right",
    "图内左上": "top_left",
    "图内右上": "top_right",
    "图内左下": "bottom_left",
    "图内右下": "bottom_right",
    "隐藏": "hidden",
}


def position_legend(pane, position):
    if pane.object is None:
        return
    # Panel keeps nested layout dictionaries in its Bokeh model. Mutating them
    # in place makes subsequent updates compare equal and disappear on the wire.
    figure = go.Figure(data=pane.object.data, layout=deepcopy(pane.object.layout))
    if not hasattr(pane, "_scmm_legend_base"):
        pane._scmm_legend_base = figure.layout.showlegend
    coordinates = {
        "right": (1.02, 1, "left", "top"),
        "top_left": (0.01, 0.99, "left", "top"),
        "top_right": (0.99, 0.99, "right", "top"),
        "bottom_left": (0.01, 0.01, "left", "bottom"),
        "bottom_right": (0.99, 0.01, "right", "bottom"),
    }
    x, y, xanchor, yanchor = coordinates.get(position, coordinates["right"])
    figure.update_layout(
        uirevision=figure.layout.uirevision or f"scmm-{getattr(pane, '_scmm_legend_revision', 0)}",
        showlegend=False if position == "hidden" else pane._scmm_legend_base,
        legend={
            "x": x,
            "y": y,
            "xanchor": xanchor,
            "yanchor": yanchor,
            "bgcolor": "rgba(255,255,255,0.75)",
            "orientation": "v",
        },
    )
    if not hasattr(pane, "_scmm_coloraxis_base"):
        pane._scmm_coloraxis_base = {
            key: figure.layout[key].showscale
            for key in figure.layout
            if key.startswith("coloraxis")
        }
    for key, original in pane._scmm_coloraxis_base.items():
        figure.layout[key].update(
            showscale=False if position == "hidden" else original,
            colorbar={
                "x": x,
                "y": y,
                "xanchor": xanchor,
                "yanchor": yanchor,
                "len": 1 if position == "right" else 0.35,
                "thickness": 14,
            },
        )
    if figure.to_json() != pane.object.to_json():
        pane.object = figure


def presentation_views(root):
    """Include closed accordions, which Panel deliberately skips in select()."""
    views, pending, seen = [], [root], set()
    while pending:
        view = pending.pop()
        if not isinstance(view, pn.viewable.Viewable) or id(view) in seen:
            continue
        seen.add(id(view))
        views.append(view)
        pending.extend(v for v in view.select() if v is not view)
        pending.extend(getattr(view, "objects", []))
    return views


def apply_presentation(root):
    views = presentation_views(root)

    def select(kind):
        return [view for view in views if isinstance(view, kind)]

    if configure_help not in pn.viewable.Viewable._preprocessing_hooks:
        pn.viewable.Viewable._preprocessing_hooks.append(configure_help)
    for widget in select(pn.widgets.Button) + select(pn.widgets.FileDownload):
        style_button(widget)
    for control in select((pn.widgets.RadioButtonGroup, pn.widgets.Toggle)):
        if CONTROL_BUTTON_STYLE not in control.stylesheets:
            control.stylesheets = [*control.stylesheets, CONTROL_BUTTON_STYLE]
        control.height = None
    for accordion in select(pn.Accordion):
        accordion.header_background = "#f5f3ff"
        accordion.active_header_background = "#ede9fe"
        accordion.header_color = "#6d28d9"
        accordion.sizing_mode = "stretch_width"
    for widget in select(pn.widgets.Widget):
        if isinstance(
            widget,
            (
                pn.widgets.TextInput,
                pn.widgets.Select,
                pn.widgets.IntInput,
                pn.widgets.FloatInput,
                pn.widgets.Checkbox,
            ),
        ):
            widget.sizing_mode = None
            widget.min_width = 0
            if isinstance(widget, (pn.widgets.IntInput, pn.widgets.FloatInput)):
                widget.width = None
                widget.styles = {**widget.styles, "width": "220px"}
            elif widget.width is None or widget.width == 300:
                widget.width = None
                widget.styles = {**widget.styles, "width": "240px"}
            widget.styles = {**widget.styles, "max-width": "100%", "min-width": "0"}
            if FIELD_STYLE not in widget.stylesheets:
                widget.stylesheets = [*widget.stylesheets, FIELD_STYLE]
        elif isinstance(widget, (pn.widgets.MultiChoice, pn.widgets.AutocompleteInput)):
            widget.sizing_mode = "stretch_width"
            widget.max_width = 520
            widget.min_width = 0
    for layout in select(pn.Column):
        layout.min_width = 0
    for pane in select(pn.pane.Plotly):
        if "scmm-formatted" in pane.tags:
            continue
        pane.tags = [*pane.tags, "scmm-formatted"]
        # Rebuild Plotly after config changes so modebar export options refresh.
        pane.jscallback(config="source._render_count += 1")
        style_figure(pane.object)
        pane.param.watch(lambda e: style_figure(e.new), "object")
        pane.config = {
            **(pane.config or {}),
            "displaylogo": False,
            "toImageButtonOptions": {"format": "svg"},
        }
    for table in select(pn.pane.DataFrame):
        if "scmm-formatted" in table.tags:
            continue
        table.tags = [*table.tags, "scmm-formatted"]
        table.text_align = table.justify = "center"
        table.sparsify = False
        table.col_space = 100
        table.max_rows = 100
        table.float_format = ordinary_number
        table.styles = {**table.styles, "overflow": "auto"}
        table.stylesheets = [
            *table.stylesheets,
            ".panel-df th, .panel-df td { text-align: center !important; vertical-align: middle; white-space: nowrap; }",
        ]

        def format_table(event=None, table=table):
            frame = table.object
            if not isinstance(frame, pd.DataFrame):
                return
            formatters = {}
            for col in frame.columns:
                name = str(col).lower()
                if name in {"mz", "m/z", "reference_mz", "feature_id"}:
                    formatters[col] = mass_label
                elif name == "count":
                    formatters[col] = lambda x: f"{x:.0f}"
                elif name in {"mean_a", "mean_b"} or any(
                    key in name for key in ("intensity", "强度", "abundance")
                ):
                    formatters[col] = lambda x: f"{x:.3e}"
                elif any(key in name for key in ("features", "cells", "特征数", "细胞数")):
                    formatters[col] = count_number
                elif name in {"p_value", "p", "pval", "pvalue", "fdr", "q_value", "qvalue"}:
                    formatters[col] = probability_number
                    table.na_rep = "—"
            table.formatters = formatters

        format_table()
        table.param.watch(format_table, "object")
    for table in select(pn.widgets.Tabulator):
        if "scmm-formatted" in table.tags:
            continue
        table.tags = [*table.tags, "scmm-formatted"]
        table.text_align = "center"
        table.header_align = "center"
        table.layout = "fit_data_stretch"
        if "Reference m/z" in table.value.columns:
            table.formatters = {"Reference m/z": {"type": "money", "precision": 4, "symbol": ""}}
        table.stylesheets = [
            *table.stylesheets,
            ".tabulator-cell { text-overflow: ellipsis; text-align: center !important; } .tabulator-col-title { text-align: center !important; }",
            ".tabulator-col.tabulator-sortable .tabulator-col-title { padding-left: 25px !important; padding-right: 25px !important; }",
        ]


def english_parameters(owner):
    """Use stable English parameter identifiers, retaining action button labels."""
    for name, widget in vars(owner).items():
        if isinstance(
            widget,
            (
                pn.widgets.Select,
                pn.widgets.MultiChoice,
                pn.widgets.TextInput,
                pn.widgets.FloatInput,
                pn.widgets.IntInput,
                pn.widgets.RangeSlider,
                pn.widgets.FloatSlider,
                pn.widgets.Checkbox,
            ),
        ) and name not in {
            "trust",
            "replace_confirm",
            "batch_confirm",
            "apply_confirm",
            "reset_confirm",
            "leave",
            "confirm_save",
            "exploratory_split",
            "project_name",
            "description",
            "h5ad_download_name",
            "follow_log",
            "raw_sample",
            "name",
            "project_select",
            "file_root",
            "mapping_source",
            "export_root",
            "export_directory",
            "export_name",
            "root",
            "path",
            "included",
            "legend_chart",
            "legend_position",
            "validation_mode",
        }:
            widget.label = name
            if name in {"ref_mz", "target_mz", "mz_min", "mz_max"}:
                widget.format = "0.0000"
