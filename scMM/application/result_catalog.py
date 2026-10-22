"""Explicit contracts for current analysis results; no models in saved reports."""

from copy import deepcopy
from dataclasses import dataclass

import pandas as pd

from scMM.util.lifecycle import stale_stored_reports


@dataclass(frozen=True)
class ResultSpec:
    operation: str
    plots: tuple[str, ...]
    download: str
    metadata_fields: tuple[str, ...] = ()
    invalidates: tuple[str, ...] = ()


RESULTS = {
    "differential": ResultSpec(
        "differential", ("volcano", "violin"), "differential.csv", ("group_key",)
    ),
    "markers": ResultSpec("markers", (), "markers.csv", ("group_key",)),
    "network": ResultSpec("network", ("network_plot",), "network.csv"),
    "supervised": ResultSpec(
        "train",
        ("roc", "pr", "calibration", "confusion"),
        "supervised.json",
        ("label_key", "group_key"),
        ("shap",),
    ),
    "shap": ResultSpec(
        "explain_shap",
        ("shap_plot", "shap_beeswarm", "shap_waterfall", "shap_dependence"),
        "shap.csv",
    ),
}
RESULT_NAMES = {spec.operation: name for name, spec in RESULTS.items()}
RESULT_PLOTS = {name: spec.plots for name, spec in RESULTS.items()}
# Independent plots use only their explicit observation dependencies and X/layer.
INDEPENDENT_PLOTS = ("feature_scatter", "feature_embedding", "stability")


def related_results(names):
    selected = set(names)
    for name in tuple(selected):
        if name in RESULTS:
            selected.update(RESULTS[name].invalidates)
    return selected


def metadata_dependencies(name, value, all_values):
    if name == "shap":
        if "supervised" in all_values:
            return metadata_dependencies("supervised", all_values["supervised"], all_values)
        return set(value.get("_observation_dependencies", ())) if isinstance(value, dict) else set()
    spec = RESULTS.get(name)
    if spec is None:
        return set()
    return {
        value.get(key) if isinstance(value, dict) else getattr(value, key, None)
        for key in spec.metadata_fields
    } - {None, ""}


def stale_metadata_results(values, changed, *, readonly=False):
    if readonly:
        return related_results(stale_stored_reports(values, changed))
    stale = set()
    for name, value in values.items():
        dependencies = metadata_dependencies(name, value, values)
        if (name == "shap" and "supervised" not in values) or dependencies & changed:
            stale.add(name)
    return related_results(stale)


def live_report(name, value):
    if name not in RESULTS:
        raise ValueError("Unknown analysis result")
    if name == "supervised":
        return {
            "diagnostics": value.result_,
            "label_key": getattr(value, "label_key", None),
            "group_key": getattr(value, "group_key", None),
            "train_obs": value.train_obs_names_.tolist(),
            "test_obs": value.test_obs_names_.tolist(),
            "classes": value.classes_.tolist(),
        }
    return value


def serialize_reports(values, *, identities=None):
    reports = {}
    for name in RESULTS:
        if name not in values:
            continue
        result = live_report(name, values[name])
        payload = {
            key: deepcopy(value)
            for key, value in result.items()
            if key not in {"table", "graph", "correlation"}
        }
        if "table" in result:
            payload["table"] = result["table"].to_dict(orient="records")
            payload["table_columns"] = list(result["table"].columns)
        if name == "network":
            payload["nodes"] = list(result["graph"].nodes)
            if "correlation" in result:
                payload["correlation_split"] = result["correlation"].to_dict(orient="split")
                payload["correlation_axis_names"] = [
                    result["correlation"].index.name,
                    result["correlation"].columns.name,
                ]
        if identities and identities.get(name):
            payload["_result_identity"] = identities[name]
        payload["_observation_dependencies"] = sorted(metadata_dependencies(name, result, values))
        reports[name] = payload
    return reports


def restore_report(name, value):
    if name not in RESULTS:
        raise ValueError("Unknown analysis result")
    result = deepcopy(value)
    result.pop("_observation_dependencies", None)
    result.pop("_result_identity", None)
    columns = result.pop("table_columns", None)
    if "table" in result:
        result["table"] = pd.DataFrame(result["table"], columns=columns)
    correlation = result.pop("correlation_split", None)
    axis_names = result.pop("correlation_axis_names", [None, None])
    if correlation is not None:
        result["correlation"] = pd.DataFrame(**correlation)
        result["correlation"].index.name, result["correlation"].columns.name = axis_names
    if name == "network":
        import networkx as nx

        graph = nx.Graph()
        graph.add_nodes_from(result.get("nodes", ()))
        for row in result["table"].to_dict(orient="records"):
            graph.add_edge(row["source"], row["target"], correlation=row["correlation"])
        result["graph"] = graph
    return result


def frontend_contract():
    operations = {
        "reduce": {"plots": ["embedding"]},
        "cluster": {"plots": ["embedding"]},
        "save_latent": {"plots": []},
    }
    for name, spec in RESULTS.items():
        operations[spec.operation] = {
            "result": name,
            "plots": list(spec.plots[:1] if name == "differential" else spec.plots),
        }
    return {
        "operations": operations,
        "resultPlots": {name: list(spec.plots) for name, spec in RESULTS.items()},
        "resultDownloads": {name: spec.download for name, spec in RESULTS.items()},
    }


PLOT_RESULTS = {plot: name for name, spec in RESULTS.items() for plot in spec.plots}
REPORT_PLOTS = set(PLOT_RESULTS) - {"violin"}
DATA_PLOTS = (*INDEPENDENT_PLOTS, "embedding", "qc_plot", "heatmap")


def project_result_identities(project):
    return {
        name: project.workspace._result_identities.get(name)
        if name in project.workspace.results
        else project.saved_reports.get(name, {}).get("_result_identity")
        for name in RESULTS
    }


def rebind_figure_identity(figure, state, *, previous_token=None, kind=None, identities=None):
    """Rebind proven unchanged inputs; persisted identity is trusted only on reopen."""
    from numbers import Integral

    if not isinstance(figure, dict) or not isinstance(figure.get("layout"), dict):
        return False
    metadata = figure["layout"].get("meta")
    if not isinstance(metadata, dict):
        return False
    if kind not in PLOT_RESULTS and kind not in DATA_PLOTS:
        return False
    parent = PLOT_RESULTS.get(kind)
    if parent:
        identity = (identities or {}).get(parent)
        valid = bool(
            identity
            and metadata.get("result_name") == parent
            and metadata.get("result_identity") == identity
        )
        metadata["result_identity_valid"] = valid
        if not valid:
            return False
    if state.data is None or metadata.get("dataset_token") is None:
        return False
    previous = state.token if previous_token is None else previous_token
    accepted = [list(previous)]
    if previous[1] == 0:
        saved = state.require_data().uns.get("scmm_workbench", {})
        if (
            isinstance(saved, dict)
            and isinstance(saved.get("dataset_id"), str)
            and isinstance(saved.get("revision"), Integral)
            and not isinstance(saved.get("revision"), bool)
        ):
            accepted.append([saved["dataset_id"], int(saved["revision"])])
    if metadata.get("dataset_token") not in accepted:
        return False
    metadata["dataset_token"] = list(state.token)
    return True
