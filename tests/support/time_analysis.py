"""Small deterministic AnnData and window input constructors; no shared mutable state."""

import numpy as np
import pandas as pd
from anndata import AnnData

from scMM.application.time_analysis import trajectory
from scMM.util.intensity import write_intensity_states


def example(count=40):
    data = AnnData(
        np.random.default_rng(12).normal(size=(count, 6)),
        obs=pd.DataFrame(
            {
                "time": np.linspace(0, 1, count),
                "group": ["a"] * (count // 2) + ["b"] * (count - count // 2),
                "batch": "original",
            },
            index=[f"c{i}" for i in range(count)],
        ),
        var=pd.DataFrame(index=[f"f{i}" for i in range(6)]),
    )
    data.obsm["X_test"] = np.column_stack(
        [np.arange(count, dtype=float), np.arange(count, dtype=float) ** 2]
    )
    write_intensity_states(data, {"X": "raw"})
    return data


def path(data, key="path_a", **options):
    return trajectory(
        data,
        **{
            "key": key,
            "coordinate_key": "X_test",
            "time_key": "time",
            "time_kind": "normalized_time",
            "unit": "unitless",
            "window_size": 4,
            "step_size": 3,
            "min_cells_per_window": 2,
            **options,
        },
    )
