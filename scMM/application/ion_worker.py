"""Bounded independent worker: reads a frozen measurement, writes plain JSON only."""

import json
import os
import sys
from pathlib import Path


def compute(data, options):
    from scMM.ion.hypotheses import infer_groups
    from scMM.ion.relations import (
        assess_isotope_ratios,
        find_relations,
        formula_relations,
        measure_evidence,
    )
    from scMM.ion.species import ION_SPECS

    specs = [ION_SPECS[key] for key in options["species"]]
    relations = find_relations(
        data,
        specs,
        polarity=options["polarity"],
        ppm=options["ppm"],
        max_isotope_order=options["max_isotope_order"],
    )["relations"]
    if options.get("formula_hypotheses"):
        relations += formula_relations(
            data,
            options["formula_hypotheses"],
            polarity=options["polarity"],
            ppm=options["ppm"],
            resolution_200=options["resolution_200"],
            max_isotope_order=options["max_isotope_order"],
        )
    evidence, reason = [], None
    try:
        evidence = measure_evidence(data, relations, min_valid_cells=options["min_valid_cells"])
    except ValueError as exc:
        reason = str(exc)
    grouping = infer_groups(
        data,
        relations,
        specs,
        ppm=options["ppm"],
        max_states=options["max_states"],
        timeout_seconds=options["component_seconds"],
        max_hypotheses=options["max_hypotheses"],
    )
    ratios = assess_isotope_ratios(relations, evidence, min_valid_cells=options["min_valid_cells"])
    return {
        "schema_version": 1,
        "grouping": grouping,
        "evidence": evidence,
        "ratio_assessments": ratios,
        "evidence_unavailable_reason": reason,
        "options": options,
    }


def main(directory):
    import signal

    # Linux child exits if the API dies; the manager also verifies process termination.
    if sys.platform.startswith("linux"):
        import ctypes

        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        if os.getppid() == 1:
            raise RuntimeError("worker parent exited")
    import resource

    resource.setrlimit(resource.RLIMIT_FSIZE, (50_000_000, 50_000_000))
    from anndata import read_h5ad

    directory = Path(directory)
    options = json.loads((directory / "options.json").read_text())
    cpu = options.get("task_seconds", 300)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
    memory = options.get("memory_mb", 16384) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    result = compute(read_h5ad(directory / "input.h5ad"), options)
    encoded = json.dumps(result, allow_nan=False, ensure_ascii=False)
    if len(encoded.encode()) > 50_000_000:
        raise ValueError("worker output budget exceeded")
    (directory / "result.tmp").write_text(encoded)
    (directory / "result.tmp").replace(directory / "result.json")


if __name__ == "__main__":
    main(sys.argv[1])
