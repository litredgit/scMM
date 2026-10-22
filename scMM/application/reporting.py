"""Build a read-only report bound to the explicitly requested current dataset."""

import json
from copy import deepcopy
from datetime import UTC, datetime

from scMM import __version__
from scMM.analysis.quality_pdf import quality_report_bytes, report_bundle

from .result_catalog import RESULTS, project_result_identities, rebind_figure_identity


def report_artifact(project, result_value, kind, key):
    if kind not in {"quality_pdf", "report_zip"}:
        raise ValueError("unsupported report type")
    state = project.workspace
    try:
        requested = json.loads(key) if len(key) < 200 else None
    except (ValueError, TypeError) as exc:
        raise ValueError("Refresh the current dataset before exporting a report") from exc
    if (
        not isinstance(requested, list)
        or len(requested) != 2
        or type(requested[0]) is not str
        or type(requested[1]) is not int
        or requested != list(state.token)
    ):
        raise ValueError("Report input is stale; refresh the current dataset")
    data = state.require_data()
    from .time_analysis import info as time_info
    from .time_analysis import result_metadata, result_tables

    time_results = [row for row in time_info(data) if row["valid"]]
    available = sorted((set(state.results) | set(project.saved_reports)) & RESULTS.keys())
    metadata = {
        "report_schema": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "scmm_version": __version__,
        "project": project.manifest["name"],
        "dataset_id": state.dataset_id,
        "dataset_revision": state.revision,
        "matrix": "current X",
        "source": state.source or "unknown",
        "unsaved": project.unsaved,
        "loaded_project_revision": project.manifest.get("revision"),
        "last_saved_snapshot": project.manifest.get("artifacts", {}).get("current"),
        "available_results": [*available, *(f"time_{row['key']}" for row in time_results)],
        "figures": sorted(project.views.get("figures", {})),
        "history": state.history(),
        "scope": "当前矩阵 QC 和现有有效数值结果；不自动分析，不代替科学验收",  # noqa: RUF001
    }
    if kind == "quality_pdf":
        return quality_report_bytes(data, metadata), "application/pdf"
    reports = {}
    for row in time_results:
        for name, table in result_tables(data, row["key"]).items():
            reports[f"time_{row['key']}_{name}"] = {
                "summary": result_metadata(data, row["key"]),
                "table": table,
            }
    for name in available:
        value = result_value(project, name)
        reports[name] = {
            "summary": {
                k: v for k, v in value.items() if k not in {"table", "graph", "correlation"}
            }
        }
        if "table" in value:
            reports[name]["table"] = value["table"]
        if name == "network":
            if "graph" in value:
                reports[name]["summary"]["nodes"] = list(value["graph"].nodes)
            if "correlation" in value:
                reports[name]["correlation"] = value["correlation"]
    figures = {}
    omitted = {}
    for name, source in project.views.get("figures", {}).items():
        figure = json.loads(source) if isinstance(source, str) else deepcopy(source)
        meta = figure.get("layout", {}).get("meta", {})
        rebind_figure_identity(
            figure, state, kind=name, identities=project_result_identities(project)
        )
        if (
            meta.get("time_result_valid") is False
            or meta.get("result_identity_valid") is False
            or meta.get("dataset_token") != list(state.token)
        ):
            omitted[name] = (
                "figure workspace identity is not current; use the figure's own read-only export"
            )
            continue
        figures[name] = figure
    metadata["omitted_figures"] = omitted
    return report_bundle(data, metadata, reports, figures=figures), "application/zip"
