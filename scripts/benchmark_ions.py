"""Reproducible synthetic ion engineering evidence; not chemical validation.

Run with the project environment: python scripts/benchmark_ions.py --output report.json
Each size executes in a fresh process so peak RSS is reported independently.
"""

import argparse
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def case(samples):
    import numpy as np
    import pandas as pd
    from anndata import AnnData

    from scMM.application.data_views import add_source_view, initialize_catalog
    from scMM.application.ion_jobs import IonJobs
    from scMM.application.projects import ProjectStore
    from scMM.application.web_ions import measurement
    from scMM.ion.identity import dataset_identity
    from scMM.ion.representation import build_representations
    from scMM.util.intensity import write_intensity_states

    rng = np.random.default_rng(1024)
    cells, features = samples * 1000, 500
    data = AnnData(
        rng.lognormal(2.0, 1.0, (cells, features)),
        obs=pd.DataFrame(
            {"sample_id": np.repeat([f"s{i}" for i in range(samples)], 1000)},
            index=[f"c{i}" for i in range(cells)],
        ),
        var=pd.DataFrame(
            {"mz": np.linspace(100.0, 995.0, features)}, index=[f"f{i}" for i in range(features)]
        ),
    )
    for i in range(0, 40, 2):
        data.var.iloc[i + 1, 0] = data.var.iloc[i, 0] + 1.00335483507
        data.X[:, i + 1] = data.X[:, i] * 0.1
    write_intensity_states(data, {"X": "raw"})
    timers = {}
    with TemporaryDirectory(prefix="scmm-ion-benchmark-") as temp:
        store = ProjectStore(temp)
        project = store.create("synthetic benchmark")
        start = time.perf_counter()
        view, _ = initialize_catalog(
            project,
            data,
            source={"kind": "synthetic benchmark", "seed": 1024},
            origin_kind="extraction",
            linearity="linear_abundance",
        )
        timers["freeze_seconds"] = time.perf_counter() - start
        source = measurement(project, view["root_id"])
        jobs = IonJobs(Path(temp) / ".ion-jobs")
        options = {
            "species": ["[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+"],
            "polarity": "pos",
            "ppm": 5.0,
            "max_isotope_order": 3,
            "min_valid_cells": 20,
            "formula_hypotheses": [],
            "resolution_200": None,
            "max_states": 100000,
            "component_seconds": 30.0,
            "max_hypotheses": 10000,
            "memory_mb": 16384,
            "task_seconds": 300,
        }
        start = time.perf_counter()
        job = jobs.submit(
            source,
            owner="synthetic",
            workspace="benchmark",
            binding={"root_id": view["root_id"]},
            options=options,
            request_id="benchmark",
        )
        timers["submit_freeze_seconds"] = time.perf_counter() - start
        response_times = []
        while True:
            stamp = time.perf_counter()
            row = jobs.get(job["id"], owner="synthetic", workspace="benchmark")
            response_times.append(time.perf_counter() - stamp)
            if row["status"] not in {"queued", "running"}:
                break
            if time.perf_counter() - start > 310:
                raise RuntimeError("benchmark worker exceeded task deadline")
            time.sleep(0.02)
        timers["worker_wall_seconds"] = time.perf_counter() - start
        if row["status"] != "succeeded":
            raise RuntimeError(
                (Path(temp) / ".ion-jobs" / job["id"] / "worker.log").read_text()[-10000:]
            )
        result = jobs.result(job["id"], owner="synthetic", workspace="benchmark")
        grouping = result["grouping"]
        start = time.perf_counter()
        l1, l2, audit = build_representations(
            source, grouping, [], relation_reviews={}, include_singletons=True
        )
        for level, matrix in [("L1", l1), ("L2", l2)]:
            add_source_view(
                project,
                matrix,
                root_id=view["root_id"],
                level=level,
                source_features=list(source.var_names),
                quantification_id=audit["representation_id"],
            )
        project.ion_state["registry"]["grouping"]["synthetic"] = {
            "root_id": view["root_id"],
            **result,
        }
        timers["represent_and_register_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        store.save(project)
        timers["save_and_validate_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        reopened = store.open(project.folder)
        timers["reopen_seconds"] = time.perf_counter() - start
        assert len(reopened.ion_state["branches"]) == 3
        for key, matrix in project.ion_state["source_matrices"].items():
            assert dataset_identity(matrix, allow_missing=True) == dataset_identity(
                reopened.ion_state["source_matrices"][key], allow_missing=True
            )
        job_bytes = sum(
            p.stat().st_size for p in (Path(temp) / ".ion-jobs").rglob("*") if p.is_file()
        )
        snapshot_bytes = sum(p.stat().st_size for p in project.folder.rglob("*") if p.is_file())
        jobs.shutdown()
        return {
            "samples": samples,
            "shape": [cells, features],
            "seed": 1024,
            "timings": timers,
            "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_worker_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            "raw_matrix_bytes": data.X.nbytes,
            "job_bytes": job_bytes,
            "snapshot_bytes": snapshot_bytes,
            "status_query_max_seconds": max(response_times),
            "relations": len(grouping["relations"]),
            "groups": len(grouping["groups"]),
            "search_complete": all(d["search_complete"] for d in grouping["diagnostics"]),
            "search_states": sum(d["states"] for d in grouping["diagnostics"]),
            "l1_variables": l1.n_vars,
            "l2_variables": l2.n_vars,
            "selection_mode": "reviewed_v1 with no accepted relations; unknowns retained",
            "roundtrip_exact": True,
        }


def dense():
    import numpy as np
    import pandas as pd
    from anndata import AnnData

    from scMM.ion import ION_SPECS, find_relations, infer_groups

    data = AnnData(
        np.ones((20, 30)),
        obs=pd.DataFrame(index=[f"c{i}" for i in range(20)]),
        var=pd.DataFrame(
            {"mz": [500.0] * 15 + [501.00335483507] * 15}, index=[f"f{i}" for i in range(30)]
        ),
    )
    specs = [ION_SPECS["[M+H]+"], ION_SPECS["[M+Na]+"]]
    rows = find_relations(data, specs, polarity="pos")["relations"]
    start = time.perf_counter()
    grouping = infer_groups(
        data, rows, specs, max_states=1000, timeout_seconds=1.0, max_hypotheses=100
    )
    return {
        "shape": list(data.shape),
        "relations": len(rows),
        "elapsed_seconds": time.perf_counter() - start,
        "budgets": {"max_states": 1000, "timeout_seconds": 1.0, "max_hypotheses": 100},
        "search_complete": all(r["search_complete"] for r in grouping["diagnostics"]),
        "diagnostics": grouping["diagnostics"],
        "interpretation": "budget exhaustion must stay incomplete; not a chemistry failure",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", type=int, choices=[1, 10])
    args = parser.parse_args()
    if args.case:
        print(json.dumps(case(args.case), allow_nan=False))
        return
    results = []
    for size in (1, 10):
        completed = subprocess.run(
            [sys.executable, __file__, "--case", str(size)],
            capture_output=True,
            text=True,
            check=True,
        )
        results.append(json.loads(completed.stdout.splitlines()[-1]))
    report = {
        "schema_version": 1,
        "purpose": "synthetic engineering benchmark; no real chemical accuracy validation",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cases": results,
        "dense_component": dense(),
    }
    content = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(content)
    else:
        print(content)


if __name__ == "__main__":
    main()
