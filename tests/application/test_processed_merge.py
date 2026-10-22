"""Processed matrix matching, precise annotations/layers and complete reset axes."""

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.application.merge_metadata import mapping_rows
from scMM.application.processed_merge import assemble, prepare
from scMM.file.data import CyESIData
from scMM.util.intensity import write_intensity_states


def example(values, mz, name):
    data = AnnData(
        np.asarray(values, dtype=float),
        obs=pd.DataFrame(
            {"sample": name, "group": name, "time": np.arange(len(values), dtype=float)},
            index=[f"c{i}" for i in range(len(values))],
        ),
        var=pd.DataFrame(
            {"mz": mz, "annotation": [f"{name}:{i}" for i in range(len(mz))]},
            index=[f"f{i}" for i in range(len(mz))],
        ),
    )
    write_intensity_states(data, {"X": "raw"})
    return data


def inputs_for(left, right):
    return [
        {
            "id": f"m{i}",
            "spec": {"mass_key": "mz", "sample_key": "sample"},
            "data": data,
            "baseline": data,
            "identity": {},
            "scope": "test",
            "label": str(i),
        }
        for i, data in enumerate((left, right))
    ]


def options_for(inputs, **changes):
    return dict(
        reference=0,
        mode="union",
        ppm_tol=5.0,
        ambiguity="legacy",
        common_observations=["time"],
        mapping=[
            {
                **{key: row[key] for key in ("input_id", "source_sample")},
                "name": row["source_sample"],
                "group": None,
                "subject": None,
                "batch": None,
            }
            for row in mapping_rows(inputs)
        ],
        **changes,
    )


@pytest.mark.parametrize("mode", ["union", "ref"])
@pytest.mark.parametrize("reference", [0, 1])
def test_merge_matches_existing_alignwith_without_changing_inputs(mode, reference):
    left = example([[1.123456789012345, 2.0], [3.0, 4.0]], [200.0, 100.0], "a")
    right = example([[5.0, 6.0]], [100.0001, 300.0], "b")
    inputs = inputs_for(left, right)
    opts = options_for(inputs)
    opts.update(mode=mode, reference=reference)
    plan = prepare(inputs, opts)
    result = assemble(inputs, opts, plan["data"], "data", "fixed")
    originals = [item["data"].copy() for item in inputs]
    legacy = CyESIData.from_anndata(originals[reference], name="reference")
    legacy.alignwith(
        CyESIData.from_anndata(originals[1 - reference], name="other"),
        ppm_tol=5,
        mz_merge_options=mode,
    )
    np.testing.assert_array_equal(result.X, legacy.data.to_numpy())
    np.testing.assert_array_equal(result.var.mz, legacy.data.columns.to_numpy(dtype=float))
    np.testing.assert_array_equal(left.X, [[1.123456789012345, 2], [3, 4]])
    assert result.obs_names[0].startswith(f"m{reference}:")
    assert len(plan["baseline"]["features"]) == 3


def test_source_layers_raw_int64_metadata_and_h5ad_are_preserved(tmp_path):
    left = example([[1.0, 2.0], [3.0, 4.0]], [100.0, 200.0], "a")
    left.obs["big"] = pd.array([2**60 + 1, 2**60 + 2], dtype="Int64")
    left.layers["signal"] = left.X * 7
    left.raw = left.copy()
    right = example([[5.0, 6.0]], [100.0001, 300.0], "b")
    inputs = inputs_for(left, right)
    opts = options_for(inputs)
    result = assemble(inputs, opts, prepare(inputs, opts)["data"], "data", "fixed")
    assert result.obs["m0__big"].iloc[0] == 2**60 + 1
    assert pd.isna(result.obs["m0__big"].iloc[-1])
    np.testing.assert_equal(result.layers["merge_m0_layer_0"][:2, :2], left.layers["signal"])
    assert np.isnan(result.layers["merge_m0_layer_0"][-1]).all()
    np.testing.assert_equal(result.raw.X[:2], left.raw.X)
    assert np.isnan(result.raw.X[-1]).all()
    path = tmp_path / "merged.h5ad"
    result.write_h5ad(path)
    loaded = read_h5ad(path)
    np.testing.assert_equal(loaded.X, result.X)
    assert loaded.obs["m0__big"].iloc[0] == 2**60 + 1
    pd.testing.assert_frame_equal(loaded.uns["scmm_merge_sources"]["m0"]["obs"], left.obs)
    assert "m1__annotation" in loaded.var


def test_greedy_conflicts_are_visible_and_duplicate_mz_rejected():
    left = example([[1, 2]], [100, 100.0001], "a")
    right = example([[3]], [100.00008], "b")
    inputs = inputs_for(left, right)
    opts = options_for(inputs)
    plan = prepare(inputs, opts)["data"]
    row = plan["rows"][-1]
    assert row["ambiguous"] and row["candidate_count"] == 2
    assert row["target_id"] == "m0:f0"
    right.var["mz"] = 100
    left.var["mz"] = 100
    with pytest.raises(ValueError, match="唯一"):
        prepare(inputs, opts)


def test_current_filtered_axes_do_not_shrink_union_reset_point():
    left = example([[1, 2], [3, 4]], [100, 200], "a")
    right = example([[5, 6]], [100, 300], "b")
    inputs = inputs_for(left, right)
    inputs[0]["data"] = left[:1, :1].copy()
    opts = options_for(inputs)
    opts["mode"] = "ref"
    plans = prepare(inputs, opts)
    assert plans["data"]["cells"] == 2 and len(plans["data"]["features"]) == 1
    assert plans["baseline"]["cells"] == 3 and len(plans["baseline"]["features"]) == 3


def test_lossy_intensity_or_common_metadata_is_rejected():
    left = example([[1, 2]], [100, 200], "a")
    right = example([[3, 4]], [100, 300], "b")
    inputs = inputs_for(left, right)
    opts = options_for(inputs)
    left.X = np.array([[2**60 + 1, 2]], dtype=np.int64)
    with pytest.raises(ValueError, match="精度"):
        prepare(inputs, opts)


def test_baseline_only_samples_and_heterogeneous_groups_are_explicitly_preserved():
    left = example([[1.0, 2.0], [3.0, 4.0]], [100.0, 200.0], "a")
    left.obs["sample"] = ["a", "removed"]
    left.obs["group"] = ["A", "B"]
    right = example([[5.0, 6.0]], [100.0001, 300.0], "b")
    right.obs["group"] = ["C"]
    inputs = inputs_for(left, right)
    inputs[0]["data"] = left[:1].copy()
    opts = options_for(inputs)
    assert next(row for row in mapping_rows(inputs) if row["source_sample"] == "removed") == {
        "input_id": "m0",
        "source_sample": "removed",
        "cells": 0,
        "baseline_cells": 1,
    }
    incomplete = {
        **opts,
        "mapping": [row for row in opts["mapping"] if row["source_sample"] != "removed"],
    }
    with pytest.raises(ValueError, match="完整覆盖"):
        prepare(inputs, incomplete)
    for row in opts["mapping"]:
        row["name"] = "intentional-common-sample"
    plans = prepare(inputs, opts)
    current = assemble(inputs, opts, plans["data"], "data", "same")
    baseline = assemble(inputs, opts, plans["baseline"], "baseline", "same")
    assert current.obs["group"].tolist() == ["A", "C"]
    assert baseline.obs["group"].tolist() == ["A", "B", "C"]
    assert current.obs.sample_id.nunique() == baseline.obs.sample_id.nunique() == 1
    assert current.obs.sample_id.iloc[0] == baseline.obs.sample_id.iloc[1]
