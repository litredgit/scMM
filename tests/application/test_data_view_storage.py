"""Complete multi-branch publication and failure isolation, using synthetic inputs."""

import json

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.data_views import DataViewCatalog, initialize_catalog
from scMM.application.projects import ProjectStore


def project_with_branches(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("ions")
    data = AnnData(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        obs=pd.DataFrame({"sample_id": ["s", "s"]}, index=["a", "b"]),
        var=pd.DataFrame({"mz": [100.0, 101.0]}, index=["x", "y"]),
    )
    view, branch_id = initialize_catalog(
        project,
        data,
        source={"kind": "synthetic"},
        origin_kind="extraction",
        linearity="linear_abundance",
    )
    catalog = DataViewCatalog.from_state(project.ion_state)
    catalog.create_feature_view(
        root_id=view["root_id"], cell_ids=["b"], feature_ids=["y"], expected_revision=1
    )
    project.ion_state = catalog.export_state()
    return store, project, branch_id


def test_all_branches_roundtrip_and_old_format_stays_one(tmp_path):
    store, project, active = project_with_branches(tmp_path)
    project.workspace.normalize("log")
    store.save(project)
    assert project.manifest["schema_version"] == 2
    reopened = store.open(project.folder)
    assert len(reopened.ion_state["branches"]) == 2
    assert reopened.ion_state["active_branch_id"] == active
    np.testing.assert_array_equal(reopened.workspace.data.X, project.workspace.data.X)
    np.testing.assert_array_equal(reopened.workspace._original.X, [[1.0, 2.0], [3.0, 4.0]])
    assert reopened.workspace.dataset_id != project.workspace.dataset_id
    assert not reopened.unsaved
    root = next(iter(reopened.ion_state["roots"].values()))["data"]
    np.testing.assert_array_equal(root.X, [[1.0, 2.0], [3.0, 4.0]])
    old = store.create("old")
    old.workspace.replace(AnnData(np.ones((2, 2))))
    store.save(old)
    assert store.open(old.folder).manifest["schema_version"] == 1


def test_catalogue_save_updates_live_reports_and_views(tmp_path, monkeypatch):
    from scMM.application import data_view_storage

    store, project, active = project_with_branches(tmp_path)
    ws = project.workspace
    ws.put_result(
        "differential",
        {"table": pd.DataFrame({"fdr": [0.01]}), "parameters": {"method": "mannwhitney"}},
        ws.token,
    )
    project.views = {"figures": {"volcano": {"layout": {"meta": {}}}}}

    def rebind(figure, _state, **_kwargs):
        figure["layout"]["meta"]["verified"] = True
        return True

    monkeypatch.setattr(data_view_storage, "rebind_figure_identity", rebind)
    store.save(project)
    reopened = store.open(project.folder)
    assert project.saved_reports == reopened.saved_reports
    assert project.saved_reports["differential"]["table"] == [{"fdr": 0.01}]
    assert project.views == reopened.views
    assert project.views["figures"]["volcano"]["layout"]["meta"]["verified"] is True
    assert project.ion_state["branches"][active]["presentation"]["views"] == project.views


@pytest.mark.parametrize("malformed", ["missing", "wrong-kind"])
def test_h5ad_structural_errors_raise_value_error(tmp_path, malformed):
    import h5py

    from scMM.application.data_view_storage import verify_h5ad_snapshot

    data = AnnData(np.ones((2, 2)))
    path = tmp_path / "snapshot.h5ad"
    data.write_h5ad(path)
    with h5py.File(path, "a") as snapshot:
        if malformed == "missing":
            del snapshot["uns"]
        else:
            del snapshot["obs"]
            snapshot.create_dataset("obs", data=[1, 2])
    with pytest.raises(ValueError, match=r"Snapshot.*invalid"):
        verify_h5ad_snapshot(path, data)


def test_candidate_failure_and_inactive_corruption_are_not_partial_success(tmp_path, monkeypatch):
    from scMM.application import data_view_storage

    store, project, _ = project_with_branches(tmp_path)
    store.save(project)
    old_manifest = (project.folder / "project.json").read_bytes()
    before = project.manifest.copy()
    original = data_view_storage.AnalysisWorkspace.save_h5ad
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second branch write failed")
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(data_view_storage.AnalysisWorkspace, "save_h5ad", fail_second)
        with pytest.raises(OSError, match="second branch"):
            store.save(project)
    assert project.manifest == before
    assert (project.folder / "project.json").read_bytes() == old_manifest
    catalog = json.loads(
        (project.folder / project.manifest["artifacts"]["data_catalog"]).read_text()
    )
    inactive = next(key for key in catalog["branches"] if key != catalog["active_branch_id"])
    (project.folder / catalog["branches"][inactive]["baseline"]).unlink()
    with pytest.raises((ValueError, OSError)):
        store.open(project.folder)


def test_reference_closure_protects_inactive_branch_and_registry(tmp_path):
    from scMM.application.project_references import project_references
    from scMM.application.storage import StorageRoot
    from scMM.application.trash import SavedItems

    store, project, active = project_with_branches(tmp_path)
    store.save(project)
    catalog_path = project.folder / project.manifest["artifacts"]["data_catalog"]
    catalog = json.loads(catalog_path.read_text())
    inactive = next(key for key in catalog["branches"] if key != active)
    target = project.folder / catalog["branches"][inactive]["baseline"]
    references = project_references(project.manifest, project.folder)
    assert target in references
    assert project.folder / catalog["registry_artifact"] in references
    manager = SavedItems(store, [StorageRoot("results", tmp_path)], trash_root=tmp_path / "trash")
    with pytest.raises(RuntimeError, match="引用"):
        manager.plan("项目结果", target)


def test_full_l2_missingness_and_materialized_branch_roundtrip(tmp_path):
    from scMM.application.data_views import add_source_view, materialize_analysis_branch
    from scMM.ion.representation import preview_complete_availability

    store, project, _ = project_with_branches(tmp_path)
    root_id = next(iter(project.ion_state["roots"]))
    source = AnnData(
        np.array([[2.0, np.nan], [0.0, 7.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame({"quantifier_feature_id": ["x", "y"]}, index=["ec1", "ec2"]),
    )
    source.layers["scmm_quantifiable"] = np.array([[True, False], [True, True]])
    view, branch = add_source_view(
        project, source, root_id=root_id, level="L2", source_features=["x", "y"]
    )
    assert branch is None
    preview = preview_complete_availability(source, cell_ids=["a", "b"])
    materialized = materialize_analysis_branch(project, view_id=view["id"], preview=preview)
    store.save(project)
    reopened = store.open(project.folder)
    restored = reopened.ion_state["source_matrices"][view["id"]]
    np.testing.assert_array_equal(restored.X, source.X)
    finite = reopened.ion_state["branches"][materialized]["workspace"]["data"]
    assert finite.var_names.tolist() == ["ec1"]
    assert finite.X[1, 0] == 0


def test_complete_bundle_does_not_save_source_and_rejects_traversal(tmp_path):
    import io
    import zipfile

    from scMM.file.ion_bundle import export_project_bundle, import_project_bundle

    _store, project, _ = project_with_branches(tmp_path)
    before = (project.folder / "project.json").read_bytes()
    archive = export_project_bundle(project)
    imported = import_project_bundle(archive)
    assert len(imported["state"]["branches"]) == 2
    assert (project.folder / "project.json").read_bytes() == before
    assert project.manifest["schema_version"] == 1
    assert not list((project.folder / "snapshots").iterdir())
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bad:
        bad.writestr("../escape.json", "{}")
    with pytest.raises(ValueError, match="unsafe"):
        import_project_bundle(stream.getvalue())


def test_single_source_projection_keeps_nan_and_does_not_invent_l0(tmp_path):
    from scMM.application.data_views import add_source_view
    from scMM.file.ion_view import export_compound_source, import_compound_source

    store, project, _ = project_with_branches(tmp_path)
    root_id = next(iter(project.ion_state["roots"]))
    data = AnnData(
        np.array([[1.0, np.nan], [0.0, 3.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame(index=["ec1", "ec2"]),
    )
    data.layers["scmm_quantifiable"] = np.array([[True, False], [True, True]])
    view, _ = add_source_view(
        project, data, root_id=root_id, level="L2", source_features=["x", "y"]
    )
    payload = export_compound_source(project, view["id"])
    receiver = store.create("projection")
    imported = import_compound_source(receiver, payload)
    assert not imported["root_available"]
    assert not receiver.ion_state["roots"]
    assert receiver.workspace.data is None
    store.save(receiver)
    reopened = store.open(receiver.folder)
    np.testing.assert_array_equal(reopened.ion_state["source_matrices"][imported["id"]].X, data.X)
    assert not reopened.ion_state["roots"]


def test_hdf5_external_links_and_oversized_logical_data_are_rejected(tmp_path):
    import h5py

    from scMM.file.ion_bundle import validate_hdf5_container

    target = tmp_path / "external.h5ad"
    with h5py.File(target, "w") as handle:
        handle["outside"] = h5py.ExternalLink("/outside/secret.h5", "/X")
    with pytest.raises(ValueError, match="links"):
        validate_hdf5_container(target, max_bytes=10000)
    with h5py.File(target, "w") as handle:
        handle.create_dataset("huge", shape=(1000000,), dtype="f8", chunks=(100,))
    with pytest.raises(ValueError, match="budget"):
        validate_hdf5_container(target, max_bytes=10000)


def test_unsaved_inactive_source_reference_is_protected(tmp_path):
    from scMM.application.project_references import memory_project_references
    from scMM.application.storage import StorageRoot
    from scMM.application.trash import SavedItems

    store, project, active = project_with_branches(tmp_path)
    external = tmp_path / "external.h5ad"
    AnnData(np.ones((2, 2))).write_h5ad(external)
    inactive = next(key for key in project.ion_state["branches"] if key != active)
    project.ion_state["branches"][inactive]["workspace"]["source"] = str(external)
    assert external in memory_project_references(project)
    manager = SavedItems(
        store,
        [StorageRoot("results", tmp_path)],
        active_paths=lambda: memory_project_references(project),
        trash_root=tmp_path / "trash",
    )
    with pytest.raises(RuntimeError, match="会话"):
        manager.plan("results", external)


def test_reversible_selection_pool_roundtrip_preserves_measurement_root(tmp_path):
    from scMM.application.selection_labels import update

    store, project, _ = project_with_branches(tmp_path)
    root_before = next(iter(project.ion_state["roots"].values()))["data"].X.copy()
    update(project.workspace, name="review", ids=["a"])
    store.save(project)
    reopened = store.open(project.folder)
    assert list(reopened.workspace.data.obs_names) == ["a"]
    assert reopened.workspace._selection_source.n_obs == 2
    update(reopened.workspace, name="review", mode="toggle", enabled=False)
    np.testing.assert_array_equal(reopened.workspace.data.X, root_before)
    np.testing.assert_array_equal(
        next(iter(reopened.ion_state["roots"].values()))["data"].X, root_before
    )


@pytest.mark.parametrize("sparse", [False, True])
def test_catalogue_candidate_shares_only_readonly_buffers(tmp_path, sparse):
    from scipy.sparse import csr_matrix

    from scMM.application.data_views import copy_catalogue_state

    _store, project, _branch = project_with_branches(tmp_path)
    root = next(iter(project.ion_state["roots"].values()))["data"]
    if sparse:
        root.X = csr_matrix(root.X)
    copy_state = copy_catalogue_state(project.ion_state)
    candidate = next(iter(copy_state["roots"].values()))["data"]
    assert candidate is not root and candidate.X is not root.X
    original, shared = (root.X.data, candidate.X.data) if sparse else (root.X, candidate.X)
    assert np.shares_memory(original, shared) and not shared.flags.writeable
    candidate.obs["sample_id"] = ["edited", "third"]
    candidate.uns["scmm_measurement_root_id"] = "edited"
    assert root.obs["sample_id"].tolist() == ["s", "s"]
    assert root.uns["scmm_measurement_root_id"] != "edited"


@pytest.mark.parametrize("field", ["reports", "root", "embedding", "labels", "sparse_metadata"])
def test_snapshot_validates_metadata_and_embeddings(tmp_path, field):
    from scipy.sparse import csr_matrix

    from scMM.application.data_view_storage import verify_h5ad_snapshot

    data = AnnData(np.ones((2, 1)))
    data.uns["scmm_measurement_root_id"] = "original"
    data.uns["scmm_workbench"] = {"reports_json": '{"original":{}}'}
    data.obsm["X_pca"] = np.array([[1.0, 2.0], [3.0, 4.0]])
    data.obsm["labels"] = np.array([["中文"], [b"b"]], dtype=object)
    data.uns["sparse_metadata"] = csr_matrix([[0.0, 2.0], [np.nan, 3.0]])
    path = tmp_path / "snapshot.h5ad"
    data.copy().write_h5ad(path)
    verify_h5ad_snapshot(path, data)
    changed = data.copy()
    if field == "reports":
        changed.uns["scmm_workbench"]["reports_json"] = "{}"
    elif field == "root":
        changed.uns["scmm_measurement_root_id"] = "other"
    elif field == "embedding":
        changed.obsm["X_pca"][0, 0] += 1
    elif field == "labels":
        changed.obsm["labels"][0, 0] = "c"
    else:
        changed.uns["sparse_metadata"].data[0] += 1
    changed.write_h5ad(path)
    with pytest.raises(ValueError, match="Snapshot"):
        verify_h5ad_snapshot(path, data)


def test_h5ad_writes_preserve_live_metadata_and_reopened_pqn_history(tmp_path):
    from scMM.application.state_codec import StateCodec

    store, project, _ = project_with_branches(tmp_path)
    original = project.workspace._original
    original.obs["sample_name"] = ["raw", "raw"]
    codec = StateCodec(tmp_path)
    codec.encode(original)
    assert original.obs["sample_name"].dtype == object
    project.workspace.normalize("pqn")
    first = project.workspace.history()[-1]["parameters"]["pqn_diagnostic"]
    store.save(project)
    reopened = store.open(project.folder).workspace
    reopened.normalize("pqn")
    second = reopened.history()[-1]["parameters"]["pqn_diagnostic"]
    assert first != second
    assert {first, second} <= reopened.data.uns["scmm_workbench"]["pqn_diagnostics"].keys()
