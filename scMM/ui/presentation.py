"""Shared display formatting; exported numerical values are never rounded."""

import math

import numpy as np
import pandas as pd
import panel as pn


def ordinary_number(value):
    number = float(value)
    if 0 < abs(number) < 0.001:
        # Keep small nonzero values visible without scientific notation.
        return np.format_float_positional(
            number, precision=3, unique=False, fractional=False, trim="-"
        )
    return np.format_float_positional(number, precision=3, unique=False, trim="-")


def count_number(value):
    return np.format_float_positional(float(value), precision=1, unique=False, trim="-")


def probability_number(value):
    return np.format_float_positional(
        float(value), precision=3, unique=False, fractional=False, trim="-"
    )


class QCDataFrame(pn.pane.DataFrame):
    """Format mixed QC metrics on a display copy, retaining the numerical object."""

    def _transform_object(self, obj):
        if isinstance(obj, pd.DataFrame) and "metric" in obj:
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
            obj = displayed
        return super()._transform_object(obj)


def mass_label(value):
    try:
        return f"{float(value):.4f}"
    except (ValueError, TypeError):
        return str(value)


def feature_label(identity, mz=None):
    try:
        return (
            mass_label(mz) if mz is not None and math.isfinite(float(mz)) else mass_label(identity)
        )
    except (ValueError, TypeError):
        return mass_label(identity)


def qc_file_table(frame):
    """Display QC metrics as rows without merging distinct reference ions."""
    rows = []
    for source, values in frame.iterrows():
        for metric in frame.columns.get_level_values(0).unique():
            stats = values[metric]
            reference = str(metric).startswith("reference_intensity_")
            if reference and stats["count"] == 0:
                continue
            rows.append(
                {
                    "source_file": source,
                    "metric": "reference_intensity" if reference else metric,
                    "reference_mz": float(metric.removeprefix("reference_intensity_"))
                    if reference
                    else float("nan"),
                    **stats.to_dict(),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "source_file",
            "metric",
            "reference_mz",
            "count",
            "mean",
            "median",
            "std",
            "min",
            "max",
        ],
    )


def style_figure(figure):
    if figure is None or not hasattr(figure, "update_layout"):
        return figure
    figure.update_layout(
        template="plotly_white", paper_bgcolor="white", plot_bgcolor="white", hovermode="closest"
    )
    figure.update_xaxes(showspikes=False, showgrid=False, zeroline=False, showline=True)
    figure.update_yaxes(showspikes=False, showgrid=False, zeroline=False, showline=True)
    for axis_name in figure.layout:
        if axis_name.startswith(("xaxis", "yaxis")):
            axis = figure.layout[axis_name]
            title = (axis.title.text or "").lower()
            if any(word in title for word in ("intensity", "强度", "abundance")):
                axis.tickformat = axis.hoverformat = ".3e"
            elif "m/z" in title or title == "mz":
                axis.tickformat = axis.hoverformat = ".4f"
            elif any(word in title for word in ("features", "cells", "特征数", "细胞数")):
                axis.tickformat = axis.hoverformat = "d"
            else:
                axis.tickformat = axis.hoverformat = ".3~f"
    return figure


def apply_presentation(root):
    for pane in root.select(pn.pane.Plotly):
        if "scmm-formatted" in pane.tags:
            continue
        pane.tags = [*pane.tags, "scmm-formatted"]
        # Rebuild Plotly after config changes so modebar export options refresh.
        pane.jscallback(config="source.properties.frames.change.emit()")
        style_figure(pane.object)
        pane.param.watch(lambda e: style_figure(e.new), "object")
        pane.config = {
            **(pane.config or {}),
            "displaylogo": False,
            "toImageButtonOptions": {"format": "svg"},
        }
    for table in root.select(pn.pane.DataFrame):
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
            table.formatters = formatters

        format_table()
        table.param.watch(format_table, "object")
    for table in root.select(pn.widgets.Tabulator):
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
        }:
            widget.label = name
            if name in {"ref_mz", "target_mz", "mz_min", "mz_max"}:
                widget.format = "0.0000"
