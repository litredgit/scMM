import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scMM.file._dataset_loading import combine_aligned_files, discover_ms_files
from scMM.file.data import CyESIData


def make_dataset(
    name: str,
    values: list[list[float]],
    columns: list[float],
    *,
    labels: list[str] | None = None,
) -> CyESIData:
    obj = object.__new__(CyESIData)
    index = pd.Index([f"{name}-{idx}" for idx in range(len(values))])
    obj.data = pd.DataFrame(values, index=index, columns=columns)
    obj.peak_meta = pd.DataFrame(
        {"label": labels or [name] * len(values), "rt": np.arange(len(values))},
        index=index,
    )
    obj.feature_meta = pd.DataFrame(
        {"mz": columns, "source": name}, index=pd.Index(columns, name="feature_id")
    )
    obj.file_meta = {"name": name, "ref_mz": columns[0]}
    obj.ref_mz = columns[0]
    return obj


def test_alignwith_union_retains_values_and_metadata() -> None:
    left = make_dataset("left", [[1.0, 2.0]], [100.0, 200.0])
    right = make_dataset("right", [[10.0, 30.0]], [100.0004, 300.0])

    result = left.alignwith(right, ppm_tol=5.0, mz_merge_options="union")

    assert result is left
    assert list(result.data.columns) == [100.0, 200.0, 300.0]
    np.testing.assert_allclose(result.data.to_numpy(), [[1.0, 2.0, 0.0], [10.0, 0.0, 30.0]])
    assert list(result.feature_meta.index) == [100.0, 200.0, 300.0]
    assert result.feature_meta.loc[300.0, "source"] == "right"
    assert result.get_name() == "left+right"
    assert len(result.file_meta["per_file_meta"]) == 2


def test_alignwith_ref_retains_reference_axis() -> None:
    left = make_dataset("left", [[1.0, 2.0]], [100.0, 200.0])
    right = make_dataset("right", [[10.0, 30.0]], [100.0004, 300.0])

    left.alignwith(right, ppm_tol=5.0, mz_merge_options="ref")

    assert list(left.data.columns) == [100.0, 200.0]
    np.testing.assert_allclose(left.data.to_numpy(), [[1.0, 2.0], [10.0, 0.0]])


def test_normalize_and_impute_preserve_index() -> None:
    dataset = make_dataset("sample", [[1.0, 3.0], [0.0, 0.0]], [100.0, 200.0])
    original_index = dataset.data.index.copy()

    dataset.normalize().impute(method="mean", missing_values=0)

    pd.testing.assert_index_equal(dataset.data.index, original_index)


def test_save_load_round_trip(tmp_path: Path) -> None:
    dataset = make_dataset("sample", [[1.0, 2.0]], [100.0, 200.0])

    result_path = dataset.save(tmp_path)
    loaded = CyESIData.load_from_processed(result_path)

    pd.testing.assert_frame_equal(loaded.data, dataset.data)
    pd.testing.assert_frame_equal(loaded.peak_meta, dataset.peak_meta)
    pd.testing.assert_frame_equal(loaded.feature_meta, dataset.feature_meta)
    assert loaded.ref_mz == dataset.ref_mz
    with pytest.raises(FileExistsError):
        dataset.save(tmp_path)
    assert dataset.save(tmp_path, overwrite=True) == result_path


@pytest.mark.parametrize("method", ["knn", "mean", "median", "most_frequent"])
def test_impute_preserves_empty_features_and_metadata(method):
    dataset = make_dataset("sample", [[0.0, 0.0], [0.0, 4.0], [0.0, 8.0]], [100.0, 200.0])
    before = dataset.data.copy()
    cells, features = dataset.peak_meta.copy(), dataset.feature_meta.copy()
    dataset.feature_snr = before + 1
    snr = dataset.feature_snr.copy()
    assert dataset.impute(method=method) is dataset
    pd.testing.assert_index_equal(dataset.data.index, before.index)
    pd.testing.assert_index_equal(dataset.data.columns, before.columns)
    np.testing.assert_array_equal(dataset.data.iloc[:, 0], 0)
    np.testing.assert_array_equal(dataset.data.iloc[1:, 1], [4, 8])
    assert dataset.data.iloc[0, 1] == (4 if method == "most_frequent" else 6)
    pd.testing.assert_frame_equal(dataset.peak_meta, cells)
    pd.testing.assert_frame_equal(dataset.feature_meta, features)
    pd.testing.assert_frame_equal(dataset.feature_snr, snr)


@pytest.mark.parametrize("failure", ["shape", "nonfinite", "exception"])
def test_impute_bad_candidate_preserves_state(monkeypatch, failure):
    from sklearn.impute import KNNImputer

    dataset = make_dataset("sample", [[0.0, 2.0], [0.0, 4.0]], [100.0, 200.0])
    before = dataset.data.copy()

    def bad_result(self, values):
        # An estimator must not be able to mutate the live frame on failure.
        values.iloc[0, 1] = 99
        if failure == "exception":
            raise ValueError("estimator failed")
        if failure == "shape":
            return np.ones((2, 1))
        return np.full((2, 2), np.inf)

    monkeypatch.setattr(KNNImputer, "fit_transform", bad_result)
    with pytest.raises(ValueError):
        dataset.impute()
    pd.testing.assert_frame_equal(dataset.data, before)


def test_impute_rejects_axis_dropping_override_without_mutation():
    dataset = make_dataset("sample", [[0.0, 2.0], [0.0, 4.0]], [100.0, 200.0])
    before = dataset.data.copy()
    with pytest.raises(ValueError, match="keep_empty_features"):
        dataset.impute(keep_empty_features=False)
    pd.testing.assert_frame_equal(dataset.data, before)


@pytest.mark.parametrize("method", ["knn", "mean", "median", "most_frequent"])
@pytest.mark.parametrize("missing", [0.0, np.nan])
def test_impute_all_missing_matrix_keeps_axes(method, missing):
    dataset = make_dataset("sample", [[missing, missing]] * 3, [100.0, 200.0])
    dataset.impute(method=method, missing_values=missing)
    np.testing.assert_array_equal(dataset.data.to_numpy(), np.zeros((3, 2)))


def test_to_anndata_uses_stable_unique_identifiers() -> None:
    dataset = make_dataset("sample", [[1.0, 2.0], [3.0, 4.0]], [100.0, 200.0])

    adata = dataset.to_anndata()

    assert adata.shape == (2, 2)
    assert list(adata.obs_names) == ["cell_0", "cell_1"]
    assert list(adata.var_names) == ["100.0", "200.0"]
    assert "source_index" in adata.obs


def test_deisotope_removes_correlated_isotope() -> None:
    parent = np.array([100.0, 200.0, 300.0, 400.0])
    dataset = make_dataset(
        "sample",
        np.column_stack([parent, parent * 0.05, [5.0, 2.0, 8.0, 1.0]]).tolist(),
        [100.0, 101.003355, 150.0],
    )

    result = dataset.deisotope(ppm_tol=1.0, r_square_threshold=0.99)

    assert result is dataset
    assert list(dataset.data.columns) == [100.0, 150.0]
    assert dataset.file_meta["deisotope"]["n_removed_features"] == 1
    assert dataset.feature_meta.loc[100.0, "n_isotope_children"] == 1


def test_deisotope_audit_does_not_mutate_dataset() -> None:
    parent = np.array([100.0, 200.0, 300.0, 400.0])
    dataset = make_dataset(
        "sample",
        np.column_stack([parent, parent * 0.05, parent * 0.002]).tolist(),
        [100.0, 101.003355, 102.00671],
    )
    original_data = dataset.data.copy()
    original_feature_meta = dataset.feature_meta.copy()
    original_file_meta = dataset.file_meta.copy()

    audit = dataset.deisotope(
        ppm_tol=1.0,
        r_square_threshold=0.99,
        merge_mode="sum",
        remove=False,
        inplace=False,
    )

    pd.testing.assert_frame_equal(dataset.data, original_data)
    pd.testing.assert_frame_equal(dataset.feature_meta, original_feature_meta)
    assert dataset.file_meta == original_file_meta
    assert not hasattr(dataset, "deisotope_result")

    assert audit["isotope_features"] == [101.003355, 102.00671]
    assert audit["final_table"]["isotope_order"].tolist() == [1, 2]
    np.testing.assert_allclose(
        audit["processed_data"][100.0],
        original_data[100.0] + original_data[101.003355] + original_data[102.00671],
    )
    assert audit["feature_meta"].loc[100.0, "n_isotope_children"] == 2
    assert audit["feature_meta"].loc[101.003355, "deisotope_role"] == "isotope"


def test_deisotope_builds_missing_feature_metadata_without_side_effects() -> None:
    dataset = make_dataset("sample", [[1.0, 0.05], [2.0, 0.1]], [100.0, 101.003355])
    del dataset.feature_meta

    audit = dataset.deisotope(ppm_tol=1.0, inplace=False)

    assert not hasattr(dataset, "feature_meta")
    assert audit["feature_meta"]["mz"].tolist() == [100.0]


def test_deisotope_rejects_invalid_missing_mask_shape() -> None:
    dataset = make_dataset("sample", [[1.0, 0.05], [2.0, 0.1]], [100.0, 101.003355])

    with pytest.raises(ValueError, match="same shape"):
        dataset.deisotope(missing_func=lambda values: values[:, 0], inplace=False)


def test_load_processed_uses_csv_fallback_and_builds_metadata(tmp_path: Path) -> None:
    result_dir = tmp_path / "csv-only"
    result_dir.mkdir()
    (result_dir / ".meta").write_text(
        json.dumps({"name": "csv-only", "ref_mz": 100.0}),
        encoding="utf-8",
    )
    pd.DataFrame([[1.0, 2.0]], columns=[100.0, 200.0]).to_csv(result_dir / "data.csv")

    dataset = CyESIData.load_from_processed(result_dir)

    assert dataset.get_name() == "csv-only"
    assert dataset.peak_meta.empty
    assert dataset.feature_meta["mz"].tolist() == [100.0, 200.0]
    assert dataset.feature_meta.index.tolist() == dataset.data.columns.tolist()
    assert dataset.feature_meta.index.name == "feature_id"


def test_load_processed_rejects_feature_metadata_dimension_mismatch(tmp_path: Path) -> None:
    result_dir = tmp_path / "invalid"
    result_dir.mkdir()
    (result_dir / ".meta").write_text(
        json.dumps({"name": "invalid", "ref_mz": 100.0}),
        encoding="utf-8",
    )
    pd.DataFrame([[1.0, 2.0]], columns=[100.0, 200.0]).to_pickle(result_dir / "data.pkl")
    pd.DataFrame({"mz": [100.0]}).to_pickle(result_dir / "feature_meta.pkl")

    with pytest.raises(ValueError, match="feature_meta row count"):
        CyESIData.load_from_processed(result_dir)


def test_discover_ms_files_filters_and_sorts_direct_children(tmp_path: Path) -> None:
    (tmp_path / "b.mzXML").touch()
    (tmp_path / "a.mzML").touch()
    (tmp_path / "notes.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "ignored.mzML").touch()

    files = discover_ms_files(tmp_path)

    assert [Path(path).name for path in files] == ["a.mzML", "b.mzXML"]


def test_combine_aligned_files_orders_acquisitions_and_normalizes_time() -> None:
    def alignment(name: str, timestamp: float, retention_times: list[float], value: float):
        index = pd.Index(range(len(retention_times)), name="frame")
        return {
            "file_meta": {"name": name, "timestamp": timestamp},
            "data": pd.DataFrame(value, index=index, columns=[100.0]),
            "peak_meta": pd.DataFrame({"rt": retention_times}, index=index),
        }

    state = combine_aligned_files(
        "experiment",
        100.0,
        [
            alignment("late.mzML", 20.0, [0.0, 2.0], 2.0),
            alignment("early.mzML", 10.0, [0.0, 1.0], 1.0),
        ],
    )

    assert state.data[100.0].tolist() == [1.0, 1.0, 2.0, 2.0]
    assert state.peak_meta["label"].tolist() == ["early", "early", "late", "late"]
    np.testing.assert_allclose(state.peak_meta["time"], [0.0, 1 / 12, 10 / 12, 1.0])
    assert [item["name"] for item in state.file_meta["per_file_meta"]] == [
        "early.mzML",
        "late.mzML",
    ]


def test_alignwith_matches_each_right_feature_at_most_once() -> None:
    left = make_dataset("left", [[1.0, 2.0]], [100.0, 100.0002])
    right = make_dataset("right", [[10.0]], [100.0001])

    left.alignwith(right, ppm_tol=5.0)

    right_row = left.data.iloc[1].to_numpy()
    assert np.count_nonzero(right_row) == 1
    assert right_row.sum() == pytest.approx(10.0)


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize(
    "artifact",
    [
        ".meta",
        "data.pkl",
        "data.csv",
        "peak_meta.pkl",
        "peak_meta.csv",
        "feature_meta.pkl",
        "feature_meta.csv",
        "feature_snr.pkl",
        "feature_snr.csv",
    ],
)
def test_legacy_save_write_failure_preserves_complete_version(
    tmp_path, monkeypatch, artifact, overwrite
):
    from scMM.file import _dataset_persistence as persistence

    old = make_dataset("sample", [[1.0, 2.0]], [100.0, 200.0])
    old.feature_snr = old.data + 10
    target = tmp_path / "sample"
    if overwrite:
        old.save(tmp_path)
    updated = make_dataset("sample", [[3.0, 4.0]], [100.0, 200.0], labels=["new"])
    updated.feature_snr = updated.data + 20
    original_open = Path.open

    def fail_open(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.name == artifact and ("w" in mode or "a" in mode):
            raise OSError("injected write failure")
        return original_open(path, *args, **kwargs)

    # pandas opens pickle/CSV via builtin open, while JSON uses Path.open.
    import builtins

    original_builtin = builtins.open

    def fail_builtin(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if isinstance(path, (str, Path)) and Path(path).name == artifact and "w" in mode:
            raise OSError("injected write failure")
        return original_builtin(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", fail_open)
        patch.setattr(builtins, "open", fail_builtin)
        with pytest.raises(OSError, match="injected write failure"):
            updated.save(tmp_path, overwrite=overwrite)
    if overwrite:
        restored = CyESIData.load_from_processed(target)
        pd.testing.assert_frame_equal(restored.data, old.data)
        pd.testing.assert_frame_equal(restored.peak_meta, old.peak_meta)
        pd.testing.assert_frame_equal(restored.feature_snr, old.feature_snr)
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".scmm-dataset-stage-*"))
    assert not persistence._paths(target)[2].exists()


@pytest.mark.parametrize("phase", ["backup", "publish", "rollback", "cleanup"])
def test_legacy_save_publish_recovery(tmp_path, monkeypatch, phase):
    from scMM.file import _dataset_persistence as persistence

    old = make_dataset("sample", [[1.0]], [100.0])
    target = old.save(tmp_path)
    old.feature_snr = old.data + 10
    old.save(tmp_path, overwrite=True)
    (target / "report.txt").write_text("caller report", encoding="utf-8")
    updated = make_dataset("sample", [[3.0]], [100.0], labels=["new"])
    original_rename = Path.rename
    original_remove = persistence._remove_backup
    backup = persistence._paths(target)[2]

    def rename(path, destination):
        if (
            (phase == "backup" and path == target)
            or (phase in {"publish", "rollback"} and path.name == "dataset")
            or (phase == "rollback" and path == backup)
        ):
            raise OSError("injected rename failure")
        return original_rename(path, destination)

    def remove(path):
        if phase == "cleanup" and path.exists():
            raise OSError("injected cleanup failure")
        original_remove(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", rename)
        patch.setattr(persistence, "_remove_backup", remove)
        if phase == "cleanup":
            assert updated.save(tmp_path, overwrite=True) == target
        else:
            with pytest.raises(OSError, match="injected rename failure"):
                updated.save(tmp_path, overwrite=True)
    # Even failed rollback is recoverable on the next normal read.
    restored = CyESIData.load_from_processed(target)
    expected = updated if phase == "cleanup" else old
    pd.testing.assert_frame_equal(restored.data, expected.data)
    pd.testing.assert_frame_equal(restored.peak_meta, expected.peak_meta)
    assert hasattr(restored, "feature_snr") == (phase != "cleanup")
    assert (target / "report.txt").read_text(encoding="utf-8") == "caller report"
    updated.save(tmp_path, overwrite=True)
    assert not backup.exists()
    assert not (target / "feature_snr.pkl").exists()
    assert not (target / "feature_snr.csv").exists()


@pytest.mark.parametrize("committed", [False, True])
def test_legacy_save_process_crash_recovers_whole_version(tmp_path, committed):
    import subprocess
    import sys

    old = make_dataset("sample", [[1.0]], [100.0])
    target = old.save(tmp_path)
    script = """
import os
import sys
from pathlib import Path
from scMM.file.data import CyESIData
folder = Path(sys.argv[1])
dataset = CyESIData.load_from_processed(folder)
dataset.data.iloc[:, :] = 9.0
dataset.peak_meta["label"] = "new"
rename = Path.rename
def crash(path, destination):
    result = rename(path, destination)
    if (sys.argv[2] == "True" and path.name == "dataset") or (sys.argv[2] == "False" and path == folder):
        os._exit(91)
    return result
Path.rename = crash
dataset.save(folder.parent, overwrite=True)
"""
    result = subprocess.run([sys.executable, "-c", script, str(target), str(committed)], timeout=30)
    assert result.returncode == 91
    restored = CyESIData.load_from_processed(target)
    assert restored.data.iloc[0, 0] == (9.0 if committed else 1.0)
    assert restored.peak_meta["label"].iloc[0] == ("new" if committed else "sample")
    # An interrupted staging directory is never used as a dataset or silently removed.
    assert list(tmp_path.glob(".scmm-dataset-stage-*"))


@pytest.mark.parametrize("second_overwrite", [False, True])
def test_legacy_concurrent_save_and_read_never_mix_versions(
    tmp_path, monkeypatch, second_overwrite
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    old = make_dataset("sample", [[1.0]], [100.0])
    target = old.save(tmp_path)
    updated = make_dataset("sample", [[9.0]], [100.0], labels=["new"])
    interrupted, release, reader_started, writer_started = (Event() for _ in range(4))
    rename = Path.rename

    def pause(path, destination):
        result = rename(path, destination)
        if path == target:
            interrupted.set()
            assert release.wait(10)
        return result

    def read():
        reader_started.set()
        return CyESIData.load_from_processed(target)

    def write():
        writer_started.set()
        return old.save(tmp_path, overwrite=second_overwrite)

    monkeypatch.setattr(Path, "rename", pause)
    with ThreadPoolExecutor(max_workers=3) as pool:
        saving = pool.submit(updated.save, tmp_path, overwrite=True)
        try:
            assert interrupted.wait(10)
            reading = pool.submit(read)
            writing = pool.submit(write)
            assert reader_started.wait(10) and writer_started.wait(10)
            assert not reading.done() and not writing.done()
        finally:
            release.set()
        assert saving.result(timeout=10) == target
        restored = reading.result(timeout=10)
        if second_overwrite:
            assert writing.result(timeout=10) == target
        else:
            with pytest.raises(FileExistsError):
                writing.result(timeout=10)
    assert (restored.data.iloc[0, 0], restored.peak_meta["label"].iloc[0]) in (
        {(1.0, "sample"), (9.0, "new")} if second_overwrite else {(9.0, "new")}
    )


@pytest.mark.parametrize("replaced", [False, True])
def test_legacy_readonly_directory_checks_replacement(tmp_path, monkeypatch, replaced):
    from scMM.file import _dataset_loading as loading

    old = make_dataset("sample", [[1.0]], [100.0])
    target = old.save(tmp_path)
    path_open, load = Path.open, loading._load_processed_dataset

    def no_lock_write(path, mode="r", *args, **kwargs):
        if path.suffix == ".lock":
            raise PermissionError("read-only medium")
        return path_open(path, mode, *args, **kwargs)

    def load_and_replace(path):
        state = load(path)
        if replaced:
            path.rename(path.with_name("previous"))
            path.mkdir()
        return state

    monkeypatch.setattr(Path, "open", no_lock_write)
    monkeypatch.setattr(loading, "_load_processed_dataset", load_and_replace)
    if replaced:
        with pytest.raises(OSError, match="changed during read"):
            CyESIData.load_from_processed(target)
    else:
        pd.testing.assert_frame_equal(CyESIData.load_from_processed(target).data, old.data)


def test_legacy_load_directory_symlink_and_relative_save(tmp_path, monkeypatch):
    dataset = make_dataset("sample", [[1.0]], [100.0])
    monkeypatch.chdir(tmp_path)
    target = dataset.save("results")
    assert target == Path("results/sample")
    link = tmp_path / "alias"
    link.symlink_to(target.resolve(), target_is_directory=True)
    pd.testing.assert_frame_equal(CyESIData.load_from_processed(link).data, dataset.data)
    with pytest.raises(ValueError, match="symbolic links"):
        dataset.file_meta["name"] = "alias"
        dataset.save(tmp_path, overwrite=True)


def test_legacy_candidate_verification_failure_keeps_old_version(tmp_path, monkeypatch):
    old = make_dataset("sample", [[1.0]], [100.0])
    target = old.save(tmp_path)
    updated = make_dataset("sample", [[9.0]], [100.0], labels=["new"])
    read = pd.read_pickle

    def corrupt(path, *args, **kwargs):
        frame = read(path, *args, **kwargs)
        if Path(path).name == "data.pkl":
            frame.iloc[0, 0] = 99.0
        return frame

    with monkeypatch.context() as patch:
        patch.setattr(pd, "read_pickle", corrupt)
        with pytest.raises(AssertionError):
            updated.save(tmp_path, overwrite=True)
    pd.testing.assert_frame_equal(CyESIData.load_from_processed(target).data, old.data)


@pytest.mark.parametrize("failure", ["exception", "shape", "nonfinite"])
def test_normalization_plugin_failure_preserves_complete_state(monkeypatch, failure):
    from scMM.util.normalize import NORM_REGISTRY

    dataset = make_dataset("sample", [[1.0, 2.0], [3.0, 4.0]], [100.0, 200.0])
    dataset.feature_snr = dataset.data + 10
    dataset.deisotope_result = {"original": True}
    original = dataset.__dict__
    before = dataset.data.copy()
    metadata = json.loads(json.dumps(dataset.file_meta))

    def plugin(values, parameters):
        values[0, 0] = 999
        if failure == "exception":
            raise ValueError("plugin failed")
        return np.ones((1, 1)) if failure == "shape" else np.full(values.shape, np.inf)

    monkeypatch.setitem(NORM_REGISTRY, "plugin_failure", plugin)
    with pytest.raises(ValueError):
        dataset.normalize("plugin_failure")
    assert dataset.__dict__ is original
    pd.testing.assert_frame_equal(dataset.data, before)
    assert dataset.file_meta == metadata
    assert dataset.deisotope_result == {"original": True}


@pytest.mark.parametrize("stage", ["debug", "metadata"])
def test_preprocess_failed_callback_or_metadata_keeps_all_state(monkeypatch, stage):
    from scMM.file import _dataset_processing

    dataset = make_dataset("sample", [[1.0, 2.0], [3.0, 4.0], [1.0, 2.0]], [100.0, 200.0])
    dataset.feature_snr = dataset.data + 10
    dataset.peak_meta["tags"] = [["original"] for _ in range(3)]
    original = dataset.__dict__
    before = dataset.data.copy()
    observations = dataset.peak_meta.copy()

    def extract(frame, *args, **kwargs):
        frame.iloc[0, 0] = 999
        return {
            "cell_df": pd.DataFrame([[3.0, 4.0]], columns=frame.columns),
            "peak_frames": np.array([1 if stage == "debug" else 999]),
            "window_ranges": [(0, 2)],
            "baseline": np.zeros(frame.shape),
            "cell_mask": np.array([False, True, False]),
            "ref_mz_matched": 100.0,
        }

    def debug(name, payload):
        payload["signal"].iloc[0, 0] = 888
        payload["frame_obs"].iloc[0, 0] = "changed"
        payload["frame_obs"]["tags"].iloc[0].append("changed")
        raise ValueError("debug failed")

    monkeypatch.setattr(_dataset_processing, "find_cell_peaks", extract)
    with pytest.raises((ValueError, IndexError)):
        dataset.preprocess(debug_hook=debug if stage == "debug" else None)
    assert dataset.__dict__ is original
    pd.testing.assert_frame_equal(dataset.data, before)
    pd.testing.assert_frame_equal(dataset.peak_meta, observations)
    assert dataset.peak_meta["tags"].iloc[0] == ["original"]
    assert dataset.feature_snr is original["feature_snr"]


def test_deisotope_failing_missing_detector_cannot_change_input():
    dataset = make_dataset("sample", [[2.0, 3.0], [4.0, 6.0]], [100.0, 101.003355])
    original = dataset.__dict__
    before = dataset.data.copy()

    def missing(values):
        values[:] = 999
        raise ValueError("missing detector failed")

    with pytest.raises(ValueError):
        dataset.deisotope(missing_func=missing)
    assert dataset.__dict__ is original
    pd.testing.assert_frame_equal(dataset.data, before)


def test_outlier_rng_record_and_current_length_survive_legacy_json():
    values = [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0], [100.0, 150.0]]
    left = make_dataset("sample", values, [100.0, 200.0])
    right = make_dataset("sample", values, [100.0, 200.0])
    left.file_meta["length"] = len(values)
    left.remove_outlier(random_state=np.random.RandomState(17), n_estimators=5)
    record = json.loads(json.dumps(left.file_meta))["outlier"]["random_state"]
    recovered = np.random.RandomState()
    recovered.set_state(
        (
            record["algorithm"],
            np.array(record["keys"], dtype=np.uint32),
            record["position"],
            record["has_gauss"],
            record["cached_gaussian"],
        )
    )
    right.remove_outlier(random_state=recovered, n_estimators=5)
    pd.testing.assert_frame_equal(left.data, right.data)
    assert left.file_meta["length"] == len(left.data)
    assert left.file_meta["outlier"]["input_cells"] == 4
