"""Run one fit with private RNG, warnings and native thread limits."""

import argparse
import json
import random
import sys
import warnings
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("options", type=Path)
    args = parser.parse_args()
    try:
        from ._trend_clustering import trend_cluster

        options = json.loads(args.options.read_text(encoding="utf-8"))
        if options["cluster_method"] in {"leiden", "louvain"}:
            import igraph

            igraph.set_random_number_generator(random.Random(options["random_state"]))
        values = np.load(args.input, allow_pickle=False)
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
            warnings.simplefilter("always")
            labels = trend_cluster(values, **options)
        diagnostics = list(
            dict.fromkeys(f"{item.category.__name__}: {item.message}" for item in caught)
        )
        np.save(args.output, labels, allow_pickle=False)
        args.output.with_suffix(".json").write_text(
            json.dumps(diagnostics, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
