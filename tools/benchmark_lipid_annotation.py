"""Reproducible synthetic matrices against the installed LMSD, without saving cells."""

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from anndata import AnnData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scMM.application.lipid_database import load_database
from scMM.application.workbench import AnalysisWorkspace
from scMM.util.lipid_annotation import annotate_lipids
from scMM.util.lipid_isotopes import adduct_shift


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=int, default=10000)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--features", type=int, default=500)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.cells, args.samples, args.features) < 1 or args.samples > args.cells:
        parser.error("positive sizes required, with samples <= cells")
    start = time.perf_counter()
    database, identity = load_database()
    database_seconds = time.perf_counter() - start
    masses = (
        database.loc[database.EXACT_MASS.between(250, 900), "EXACT_MASS"]
        .drop_duplicates()
        .to_numpy()
    )
    count = (args.features + 1) // 2
    parents = masses[np.linspace(0, len(masses) - 1, count, dtype=int)] + adduct_shift("[M+H]+")
    mz = np.column_stack([parents, parents + 1.003355]).ravel()[: args.features]
    rng = np.random.default_rng(42)
    X = rng.uniform(1e4, 1e6, (args.cells, args.features))
    X[:, 1::2] = X[:, : (args.features // 2) * 2 : 2] * 0.25
    data = AnnData(
        X,
        obs=pd.DataFrame(
            {"sample": np.arange(args.cells) % args.samples},
            index=[f"synthetic-cell-{i}" for i in range(args.cells)],
        ),
        var=pd.DataFrame(
            {"mz": mz}, index=[f"synthetic-feature-{i}" for i in range(args.features)]
        ),
    )
    state = AnalysisWorkspace()
    state.replace(data)
    parameters = {
        "database": identity["filename"],
        "polarity": "pos",
        "adducts": ["[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+"],
        "annotation_ppm": 10.0,
        "isotope_ppm": 10.0,
        "max_isotope_order": 3,
        "isotope_tolerance": 0.2,
        "min_valid_cells": 20,
        "intensity_layer": "",
        "resolution": 35000.0,
    }
    start = time.perf_counter()
    result = annotate_lipids(state.require_data(), database, identity, parameters, {})
    elapsed = time.perf_counter() - start
    report = {
        "scope": "synthetic matrix with downloaded LMSD; not experimental accuracy or user acceptance",
        "created_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed": 42,
        "cells": args.cells,
        "samples": args.samples,
        "features": args.features,
        "dtype": "float64",
        "parameters": parameters,
        "pyopenms_version": result["pyopenms_version"],
        "rules": result["rules"],
        "source_sha256": {
            str(p.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in [
                Path(__file__).resolve(),
                *sorted((Path(__file__).resolve().parents[1] / "scMM/util").glob("lipid*.py")),
                Path(__file__).resolve().parents[1] / "scMM/application/lipid_database.py",
            ]
        },
        "database": identity,
        "database_load_seconds": database_seconds,
        "annotation_seconds": elapsed,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "candidate_count": len(result["candidates"]),
        "isotope_evidence_count": len(result["relations"]),
        "matched_evidence_count": sum(r["matched"] for r in result["relations"]),
        "diagnostics_count": len(result["diagnostics"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "cells",
                    "features",
                    "candidate_count",
                    "isotope_evidence_count",
                    "annotation_seconds",
                    "peak_rss_mib",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
