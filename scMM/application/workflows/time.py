"""Versioned workspace boundary for independent named time-analysis results."""

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from .. import time_analysis
from ..web_support import table_view


class TimeWorkflow:
    def __init__(self, service):
        self._service = service

    def time_info(self, identity, *, query="", offset=0, limit=200):
        with self._service.access(identity) as workspace:
            data = workspace.require_project().workspace.require_data()
            rows = time_analysis.info(data)
            saved = workspace.require_project().views.get("figures", {}).get("time_plot", {})
            if isinstance(saved, str):
                try:
                    saved = json.loads(saved)
                except (TypeError, ValueError):
                    saved = {}
            if not isinstance(saved, dict):
                saved = {}
            probabilities = {
                f"{row['key']}_branch_probs" for row in rows if row["kind"] == "palantir"
            }
            cells = [
                str(cell) for cell in data.obs_names if query.casefold() in str(cell).casefold()
            ]
            return {
                "results": rows,
                "observations": list(data.obs.columns),
                "embeddings": [
                    key
                    for key in data.obsm
                    if key not in probabilities and data.obsm[key].shape[1] >= 2
                ],
                "probability_keys": list(data.obsm),
                "layers": list(data.layers),
                "feature_columns": list(data.var.columns),
                "cells": cells[offset : offset + limit],
                "total_cells": len(cells),
                "saved_plot_key": saved.get("layout", {}).get("meta", {}).get("time_result_key"),
            }

    def time_result(self, identity, key):
        from scMM.util.time_results import require_run

        with self._service.access(identity) as workspace:
            data = workspace.require_project().workspace.require_data()
            run = require_run(data, key)
            return {
                "key": key,
                "kind": run["kind"],
                "parameters": run["parameters"],
                "tables": {
                    name: table_view(table)
                    for name, table in time_analysis.result_tables(data, key).items()
                },
            }

    def run_time(self, identity, revision, operation, options):
        self._service.require_plugin("time")
        from scMM.plugins._time import run_time

        return run_time(self._service, identity, revision, operation, options)

    def time_download(self, identity, key):
        with self._service.access(identity) as workspace:
            data = workspace.require_project().workspace.require_data()
            tables = time_analysis.result_tables(data, key)
            metadata = time_analysis.result_metadata(data, key)
            result = BytesIO()
            with ZipFile(result, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "metadata.json", json.dumps(metadata, ensure_ascii=False, allow_nan=False)
                )
                for name, table in tables.items():
                    archive.writestr(f"{name}.csv", table.to_csv(index=False))
            return result.getvalue()
