import numpy as np
import pandas as pd
import pytest
from anndata import AnnData, read_h5ad

from scMM.file.data import CyESIData
from scMM.util.intensity import PROVENANCE_KEY, intensity_states, write_intensity_states


@pytest.mark.parametrize("operation", ["normalize", "impute", "remove_outlier"])
def test_python_transforms_invalidate_imported_results_and_preserve_measurements(operation):
    original = source()
    original.raw = original.copy()
    original.layers["measured"] = original.X.copy()
    original.uns["X_pca_params"] = {"method": "pca"}
    original.uns["scmm_workbench"] = {"derived_obs": ["cluster"]}
    original.obs["cluster"] = ["a", "a", "b"]
    dataset = CyESIData.from_anndata(original)
    np.testing.assert_array_equal(dataset.to_anndata().obsm["X_pca"], original.obsm["X_pca"])
    if operation == "normalize":
        dataset.normalize("total")
    elif operation == "impute":
        dataset.impute("mean")
    else:
        dataset.remove_outlier(random_state=42, contamination=0.2)
    result = dataset.to_anndata()
    assert "X_pca" not in result.obsm and "X_pca_params" not in result.uns
    assert "cluster" not in result.obs
    assert result.uns["experiment"] == original.uns["experiment"]
    retained = original.obs_names.get_indexer(result.obs_names)
    np.testing.assert_array_equal(result.layers["measured"], original.X[retained])
    np.testing.assert_array_equal(result.raw.X, original.raw.X[retained])


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


def test_unrecorded_origin_is_not_inferred_from_names_values_or_reset(tmp_path):
    from scMM.application.workbench import AnalysisWorkspace
    from scMM.util.lipid_annotation import dataset_inputs
    from scMM.util.lipid_network import intensity_layers

    data = source()
    data.layers["raw"] = data.X.copy()
    data.uns["scmm_workbench"] = {"original_layer": "raw", "history_json": "[]"}
    state = AnalysisWorkspace()
    state.replace(data)
    state.normalize("total")
    state.reset()
    assert intensity_layers(state.data) == {"raw": [], "molecule": []}
    for layer in ["X", "raw", state.history()[-1]["layer"]]:
        with pytest.raises(ValueError, match="来源未知"):
            dataset_inputs(state.data, layer)
    # Unknown origin does not prevent normal analysis or independent persistence.
    state.reduce("pca", store_key="X_pca_new")
    exported = CyESIData.from_anndata(state.data).save_h5ad(tmp_path / "unknown.h5ad")
    restored = CyESIData.read_h5ad(exported).to_anndata()
    assert intensity_states(restored)["X"] == "unknown"
    np.testing.assert_array_equal(restored.X, data.X)


@pytest.mark.parametrize(
    "operation,expected", [("normalize", "normalized"), ("impute", "transformed")]
)
def test_python_transform_lineage_survives_h5ad_and_legacy_save(tmp_path, operation, expected):
    data = source()
    write_intensity_states(data, {"X": "raw"})
    dataset = CyESIData.from_anndata(data)
    getattr(dataset, operation)("total" if operation == "normalize" else "median")
    adata = dataset.to_anndata()
    assert intensity_states(adata)["X"] == expected
    folder = dataset.save(tmp_path)
    assert intensity_states(CyESIData.load_from_processed(folder).to_anndata())["X"] == expected
    path = dataset.save_h5ad(tmp_path / "processed.h5ad")
    assert intensity_states(CyESIData.read_h5ad(path).to_anndata())["X"] == expected


def test_legacy_imputation_history_cannot_become_raw_by_reset():
    import json

    from scMM.application.workbench import AnalysisWorkspace

    data = source()
    data.uns["scmm_workbench"] = {
        "history_json": json.dumps([{"operation": "impute", "layer": "imputed"}])
    }
    data.layers["imputed"] = data.X.copy()
    state = AnalysisWorkspace()
    state.replace(data)
    state.reset()
    assert intensity_states(state.data)["X"] == "transformed"
    state.restore("imputed")
    assert intensity_states(state.data)["X"] == "transformed"


@pytest.mark.parametrize("payload", ["[]", "null", '{"schema_version":1,"states":{"X":"invalid"}}'])
def test_malformed_lineage_is_rejected(payload):
    data = source()
    data.uns[PROVENANCE_KEY] = payload
    with pytest.raises(ValueError, match="intensity provenance"):
        CyESIData.from_anndata(data)


@pytest.mark.parametrize("method,expected", [("total", "normalized"), ("log", "transformed")])
def test_lineage_never_recovers_from_imputation_by_normalizing(method, expected):
    from scMM.application.workbench import AnalysisWorkspace

    state = AnalysisWorkspace()
    data = source()
    write_intensity_states(data, {"X": "raw"})
    state.replace(data)
    state.normalize(method)
    assert intensity_states(state.data)["X"] == expected
    state.impute()
    state.normalize(method)
    assert intensity_states(state.data)["X"] == "transformed"


@pytest.mark.parametrize("method", ["alignwith", "merge_objects"])
def test_merging_unknown_or_transformed_intensity_does_not_invent_raw(method):
    from scMM.file._sequential import merge_objects

    left = source()
    write_intensity_states(left, {"X": "raw"})
    for provenance in ("unknown", "transformed", "raw"):
        right = source()
        write_intensity_states(right, {"X": provenance})
        a, b = CyESIData.from_anndata(left), CyESIData.from_anndata(right)
        result = a.alignwith(b) if method == "alignwith" else merge_objects(CyESIData, [a, b], 0)
        assert intensity_states(result.to_anndata())["X"] == provenance


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


@pytest.mark.parametrize("operation", ["normalize", "impute", "remove_outlier"])
def test_invalid_snr_candidate_keeps_template_results_and_source(operation):
    dataset = CyESIData.from_anndata(source())
    dataset.feature_snr = dataset.feature_snr.iloc[:, ::-1]
    original = dataset.__dict__
    data = dataset.data.copy()
    template = dataset._anndata_template
    embedding = template.obsm["X_pca"].copy()
    with pytest.raises(ValueError, match="feature_snr axes"):
        getattr(dataset, operation)()
    assert dataset.__dict__ is original
    assert dataset._anndata_template is template
    np.testing.assert_array_equal(template.obsm["X_pca"], embedding)
    pd.testing.assert_frame_equal(dataset.data, data)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"file_meta_json": "null"},
        {"file_meta_json": "{}invalid"},
        {"file_meta_json": {}},
        {"schema_version": 2},
    ],
)
def test_anndata_import_rejects_malformed_metadata_without_editing_source(payload):
    from copy import deepcopy

    data = source()
    data.uns["scmm"] = deepcopy(payload)
    original = data.X.copy()
    with pytest.raises(ValueError):
        CyESIData.from_anndata(data)
    np.testing.assert_array_equal(data.X, original)
    assert data.uns["scmm"] == payload
    assert "mz" in data.var


def test_anndata_import_rejects_duplicate_feature_ids_before_copy_warning():
    data = source()
    data.var_names = ["duplicate", "duplicate"]
    with pytest.raises(ValueError, match="feature names must be unique"):
        CyESIData.from_anndata(data)


def test_legacy_scan_labels_remain_positional_and_export_source_index():
    dataset = CyESIData.from_anndata(source())
    del dataset._anndata_template
    dataset.peak_meta.index = [10, 20, 30]
    exported = dataset.to_anndata()
    np.testing.assert_array_equal(exported.X, dataset.data)
    assert exported.obs["source_index"].tolist() == ["10", "20", "30"]
    assert exported.obs["source_file"].tolist() == ["a", "a", "b"]


@pytest.mark.parametrize("operation", ["normalize", "impute", "remove_outlier"])
def test_transform_clears_imported_serialized_reports(operation):
    original = source()
    original.uns["scmm_workbench"] = {
        "reports_json": '{"differential":{"group_key":"source_file","table":[]}}'
    }
    dataset = CyESIData.from_anndata(original)
    getattr(dataset, operation)()
    exported = dataset.to_anndata()
    assert exported.uns["scmm_workbench"]["reports_json"] == "{}"
    assert original.uns["scmm_workbench"]["reports_json"] != "{}"


def test_imported_observation_identity_mismatch_is_rejected_on_export():
    dataset = CyESIData.from_anndata(source())
    dataset.peak_meta = dataset.peak_meta.iloc[::-1]
    original = dataset.__dict__
    with pytest.raises(ValueError, match="peak_meta index"):
        dataset.to_anndata()
    assert dataset.__dict__ is original
