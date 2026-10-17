"""Per-scan net reference gate, parameter provenance and saved-project compatibility."""

import json
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from scMM.application.parameters import load_defaults
from scMM.application.processing import ProcessingParameters
from scMM.application.projects import ProjectStore, write_json
from scMM.file._dataset_loading import DatasetState
from scMM.file.data import CyESIData
from scMM.util._cell_snr import find_cell_peaks_snr
from scMM.util.peak import find_cell_peaks


def extract(data, method, **kwargs):
    if method == "snr_v1":
        return find_cell_peaks_snr(data, 100.0, baseline_window=11, show_progress=False, **kwargs)
    return find_cell_peaks(
        data,
        100.0,
        baseline_filter_size=11,
        n_jobs=1,
        feature_block_size=1 if method == "legacy_block" else None,
        **kwargs,
    )


@pytest.mark.parametrize("method", ["snr_v1", "legacy", "legacy_block"])
def test_gate_removes_sparse_noise_and_cuts_window_per_scan(method):
    values = np.zeros(61)
    values[:25] = 20_000
    values[8] = 200_000
    values[15] = 100_001  # Raw signal passes both nominal thresholds; net signal does not.
    values[31:36] = [50_000, 100_000, 100_001, 100_000, 150_000]
    data = pd.DataFrame({100.0: values})
    result = extract(data, method)
    assert np.flatnonzero(result["cell_mask"]).tolist() == [8, 33, 35]
    assert result["window_ranges"] == [(8, 8), (33, 33), (35, 35)]
    assert result["peak_frames"].tolist() == [8, 33, 35]
    assert len(result["cell_df"]) == 3
    original = extract(data, method, cell_min_signal=0)
    assert np.flatnonzero(original["cell_mask"]).tolist() == [8, 15, 31, 32, 33, 34, 35]
    assert original["window_ranges"] == [(8, 8), (15, 15), (31, 35)]
    assert not extract(data, method, cell_min_signal=1e6)["cell_mask"].any()


@pytest.mark.parametrize("method", ["snr_v1", "legacy", "legacy_block"])
def test_original_ratio_condition_remains_required(method):
    data = pd.DataFrame({100.0: [130_001.0, 150_000.0, 150_001.0]})
    result = extract(
        data, method, baseline_filter=lambda values, **kw: np.full_like(values, 30_000)
    )
    assert result["cell_mask"].tolist() == [False, False, True]


@pytest.mark.parametrize("mode,frames", [("union", [12, 18]), ("intersection", [18])])
def test_multi_reference_requires_both_conditions_on_same_channel(mode, frames):
    values = np.tile([100_000.0, 1.0], (31, 1))
    values[8] = [300_000, 50_000]  # Each channel passes a different condition only.
    values[12] = [600_000, 50_000]
    values[18] = [600_000, 200_000]
    result = find_cell_peaks_snr(
        pd.DataFrame(values, columns=[100.0, 200.0]),
        [100.0, 200.0],
        reference_mode=mode,
        baseline_filter=lambda values, **kw: np.broadcast_to([100_000.0, 1.0], values.shape),
        show_progress=False,
    )
    assert np.flatnonzero(result["cell_mask"]).tolist() == frames


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "100000"])
def test_invalid_gate_rejected_at_application_and_both_algorithms(value):
    with pytest.raises(ValueError, match="cell_min_signal"):
        ProcessingParameters(ref_mz=100.0, cell_min_signal=value)
    for method in ("snr_v1", "legacy", "legacy_block"):
        with pytest.raises(ValueError, match="cell_min_signal"):
            extract(pd.DataFrame({100.0: [200_000.0]}), method, cell_min_signal=value)


@pytest.mark.parametrize("method", ["legacy", "snr_v1"])
def test_preprocess_records_gate_and_invalid_value_leaves_state_unchanged(method):
    state = DatasetState(
        pd.DataFrame({100.0: [0.0, 200_000.0, 0.0, 0.0, 0.0]}),
        pd.DataFrame({"rt": np.arange(5.0)}),
        {"name": "test"},
        100.0,
    )
    obj = CyESIData._from_raw_state(state, dict(extraction_method=method, baseline_filter_size=5))
    assert len(obj.data) == 1
    assert obj.file_meta["processing"]["cell_min_signal"] == 1e5
    before = obj.data.copy(deep=True), obj.peak_meta.copy(deep=True), deepcopy(obj.file_meta)
    with pytest.raises(ValueError, match="cell_min_signal"):
        obj.preprocess(extraction_method=method, cell_min_signal=-1)
    pd.testing.assert_frame_equal(obj.data, before[0])
    pd.testing.assert_frame_equal(obj.peak_meta, before[1])
    assert obj.file_meta == before[2]


def test_defaults_and_saved_projects_preserve_explicit_or_historical_gate(tmp_path):
    assert load_defaults().processing.cell_min_signal == 1e5
    config = tmp_path / "defaults.json"
    config.write_text(json.dumps({"processing": {"cell_min_signal": 12345}}))
    assert load_defaults(config).processing.cell_min_signal == 12345
    store = ProjectStore(tmp_path)
    project = store.create("test")
    assert project.manifest["parameters"]["cell_min_signal"] == 1e5
    # Simulate a saved project before this field existed, including a sample override.
    project.manifest["parameters"].pop("cell_min_signal")
    project.manifest["samples"] = [
        {
            "id": "a" * 32,
            "name": "sample",
            "path": "unused.mzML",
            "parameters": dict(project.manifest["parameters"]),
        }
    ]
    path = project.folder / "project.json"
    write_json(path, project.manifest)
    before = path.read_bytes()
    restored = store.open(project.folder)
    assert restored.manifest["parameters"]["cell_min_signal"] == 0
    assert restored.samples[0]["parameters"]["cell_min_signal"] == 0
    assert path.read_bytes() == before  # Opening never writes the project.
    restored.manifest["parameters"]["cell_min_signal"] = 23456
    restored.samples[0]["parameters"]["cell_min_signal"] = 34567
    store.save(restored)
    again = store.open(project.folder)
    assert again.manifest["parameters"]["cell_min_signal"] == 23456
    assert again.samples[0]["parameters"]["cell_min_signal"] == 34567
    assert asdict(ProcessingParameters(**again.manifest["parameters"]))["cell_min_signal"] == 23456
