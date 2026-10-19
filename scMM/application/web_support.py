"""JSON presentation helpers shared by HTTP features; matrices stay server-side."""

import json

import pandas as pd
from plotly.utils import PlotlyJSONEncoder


def table_view(frame, *, limit=200):
    view = frame.head(limit).copy()
    view.columns = list(map(str, view.columns))
    return {
        "columns": list(view.columns),
        "rows": json.loads(view.to_json(orient="records", double_precision=15)),
        "total": len(frame),
    }


def figure_view(figure):
    # Plotly's encoder retains float64 values and handles typed numerical arrays.
    return json.loads(json.dumps(figure.to_dict(), cls=PlotlyJSONEncoder))


def json_view(value):
    if isinstance(value, pd.DataFrame):
        return table_view(value)
    return json.loads(json.dumps(value, default=lambda item: item.tolist()))
