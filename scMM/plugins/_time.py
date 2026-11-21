"""Bundled named pseudotime, trajectory and trend computations."""

import json

from scMM.application import time_analysis
from scMM.application.result_catalog import project_result_identities, rebind_figure_identity


def run_time(self, identity, revision, operation, options):
    from scMM.application.web_projects import project_candidate

    if operation not in {"palantir", "trajectory", "velocity", "trends", "trend_clusters"}:
        raise ValueError("不支持的时间分析操作")
    with self.access(identity, operation=operation) as workspace:
        workspace.check(revision)
        project = workspace.require_project()
        time_analysis.check_size(project.workspace.require_data())
        candidate = project_candidate(project)
        if candidate.ion_state is not None:
            from scMM.application.analysis_inputs import resolve_analysis_input

            resolve_analysis_input(candidate, purpose=operation)
        state = candidate.workspace
        result = getattr(time_analysis, operation)(state.data, **options)
        state._commit(
            state.data,
            operation,
            {"key": options["key"], **result["parameters"]},
            clear_derived=False,
            save_layer=False,
        )
        for key, source in list(candidate.views.get("figures", {}).items()):
            try:
                figure = json.loads(source) if isinstance(source, str) else source
            except (TypeError, ValueError):
                continue
            rebind_figure_identity(
                figure,
                state,
                previous_token=project.workspace.token,
                kind=key,
                identities=project_result_identities(candidate),
            )
            candidate.views["figures"][key] = figure
        candidate.report_token = state.token
        candidate.dirty = True
        workspace.project = candidate
        workspace.revision += 1
        workspace.ai_completed = operation
        return {
            "workspace": self.view(workspace),
            "value": {"key": options["key"], "parameters": result["parameters"]},
        }
