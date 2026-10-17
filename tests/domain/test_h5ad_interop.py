import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.file.data import CyESIData


def source():
    data = AnnData(
        X=np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
        obs=pd.DataFrame({"source_file": ["a", "a", "b"]}, index=["c1", "c2", "c3"]),
        var=pd.DataFrame({"mz": [100.0, 200.0]}, index=["f1", "f2"]),
    )
    data.layers["feature_snr"] = data.X * 10
    data.obsm["X_pca"] = np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]])
    data.uns["experiment"] = {"name": "example"}
    return data


def test_h5ad_and_legacy_directory_round_trip(tmp_path):
    original = source()
    dataset = CyESIData.from_anndata(original, name="example", ref_mz=100.0)
    path = dataset.save_h5ad(tmp_path / "example.h5ad")
    loaded = CyESIData.read_h5ad(path)
    np.testing.assert_array_equal(loaded.data, dataset.data)
    np.testing.assert_array_equal(loaded.feature_snr, dataset.feature_snr)
    assert loaded.ref_mz == 100.0
    exported = loaded.to_anndata()
    np.testing.assert_array_equal(exported.obsm["X_pca"], original.obsm["X_pca"])
    assert exported.obs_names.tolist() == original.obs_names.tolist()
    assert exported.var_names.tolist() == original.var_names.tolist()
    assert exported.uns["experiment"] == original.uns["experiment"]
    assert loaded.get_name() == "example"
    folder = loaded.save(tmp_path / "legacy")
    restored = CyESIData.load_from_processed(folder)
    pd.testing.assert_frame_equal(restored.feature_snr, loaded.feature_snr)
    assert restored.file_meta == loaded.file_meta
    with pytest.raises(FileExistsError):
        loaded.save_h5ad(path)
    loaded.save_h5ad(path, overwrite=True)
    assert read_h5ad(path).shape == (3, 2)


def test_h5ad_write_failure_preserves_existing_file(tmp_path, monkeypatch):
    dataset = CyESIData.from_anndata(source())
    target = dataset.save_h5ad(tmp_path / "data.h5ad")
    before = target.read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(AnnData, "write_h5ad", fail)
    with pytest.raises(RuntimeError, match="write failed"):
        dataset.save_h5ad(target, overwrite=True)
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_annotation_collision_and_subset_artifacts():
    dataset = CyESIData.from_anndata(source())
    dataset.assign_source_metadata({"a": {"group": "control"}, "b": {"group": "treated"}})
    assert dataset.peak_meta.group.tolist() == ["control", "control", "treated"]
    before = dataset.peak_meta.copy()
    with pytest.raises(ValueError, match="already exists"):
        dataset.assign_source_metadata({"a": {"group": "other"}})
    pd.testing.assert_frame_equal(dataset.peak_meta, before)
    dataset.data = dataset.data.iloc[[0, 2], :1]
    dataset.peak_meta = dataset.peak_meta.iloc[[0, 2]]
    dataset.feature_meta = dataset.feature_meta.iloc[:1]
    dataset.feature_snr = dataset.feature_snr.iloc[[0, 2], :1]
    exported = dataset.to_anndata()
    np.testing.assert_array_equal(exported.obsm["X_pca"], source().obsm["X_pca"][[0, 2]])
    assert exported.layers["feature_snr"].shape == (2, 1)
