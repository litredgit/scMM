"""Bundled correlation network analysis."""

import pandas as pd

from scMM.analysis.statistics import feature_correlation_network


def network(state, **options):
    state.results.pop("network", None)
    token = state.token
    graph, corr = feature_correlation_network(state.require_data(), **options)
    table = pd.DataFrame(
        [(a, b, attrs["correlation"]) for a, b, attrs in graph.edges(data=True)],
        columns=["source", "target", "correlation"],
    )
    result = {"graph": graph, "correlation": corr, "table": table, "parameters": options}
    state.put_result("network", result, token)
    return result
