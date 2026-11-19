"""Synthetic module handoffs, native catalogue closure and transactional failures."""

import base64
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.application.module_exchange import (
    METADATA_KEY,
    export_exchange,
    export_package,
    import_exchange,
    import_feature_csv,
    import_matrix_csv,
    module_status,
    read_package,
)
from scMM.application.parameters import load_defaults
from scMM.application.projects import ProjectStore
from scMM.application.storage import StorageRoot
from scMM.application.web_workspace import WebWorkspaceService
from scMM.application.workbench import AnalysisWorkspace


@pytest.fixture
def manager(tmp_path):
    raw, results, projects = [tmp_path / name for name in ("raw", "results", "projects")]
    for folder in (raw, results, projects):
        folder.mkdir()
    service = WebWorkspaceService(
        [StorageRoot("raw", raw)],
        [StorageRoot("results", results)],
        projects,
        load_defaults(),
    )
    identity = service.create()["workspace_id"]
    service.create_project(identity, 0, "Module input")
    yield service, identity
    service.shutdown()


def values(format, **options):
    return {
        "revision": 1,
        "format": format,
        "filename": "upload.csv",
        "file_base64": "",
        "matrix_csv": "",
        "observations_csv": "",
        "features_csv": "",
        "orientation": "observations_rows",
        "observation_kind": "cell",
        **options,
    }


def test_matrix_rows_columns_and_exact_metadata_alignment():
    data = import_matrix_csv(
        "Sample,Class,100.25,200.5\ns2,B,0,2.4\ns1,A,3.1,4\n",
        observations_csv="observation_id,subject\ns1,p1\ns2,p2\n",
        features_csv="feature_id,mz,name\n200.5,200.5,B\n100.25,100.25,A\n",
        observation_kind="sample",
    )
    assert data.obs_names.tolist() == ["s2", "s1"]
    assert data.obs.subject.tolist() == ["p2", "p1"]
    assert data.obs.group.tolist() == ["B", "A"]
    assert data.var["name"].tolist() == ["A", "B"]
    assert data.X[0, 0] == 0
    column_data = import_matrix_csv(
        "Feature,s2,s1\nClass,B,A\n100.25,0,3.1\n200.5,2.4,4\n",
        orientation="observations_columns",
    )
    np.testing.assert_array_equal(column_data.X, data.X)
    assert column_data.obs.group.tolist() == ["B", "A"]
    assert json.loads(data.uns[METADATA_KEY])["observation_kind"] == "sample"


def test_metaboanalyst_label_formats_and_cells_are_not_biological_replicates(manager):
    row = import_matrix_csv("Sample,Label,100.5\ncell1,处理组,2\ncell2,对照组,3\n")
    column = import_matrix_csv(
        "Feature,cell1,cell2\nLabel,处理组,对照组\n100.5,2,3\n", orientation="observations_columns"
    )
    assert row.obs.group.tolist() == ["处理组", "对照组"]
    assert column.obs.group.tolist() == row.obs.group.tolist()
    assert row.obs["sample"].nunique() == 1
    assert json.loads(row.uns[METADATA_KEY])["biological_replication"] == "unknown"
    supplied = import_matrix_csv(
        "id,100.5\nc1,2\nc2,3\n",
        observations_csv="observation_id,sample_id\nc1,donor1\nc2,donor1\n",
    )
    assert "sample" not in supplied.obs
    assert supplied.obs.sample_id.tolist() == ["donor1", "donor1"]
    sample = import_matrix_csv(
        "Sample,Label,100.5\ns1,处理组,2\ns2,对照组,3\n", observation_kind="sample"
    )
    assert sample.obs["sample"].tolist() == ["s1", "s2"]
    service, identity = manager
    import_exchange(
        service,
        identity,
        "statistics",
        values("matrix_csv", matrix_csv="Sample,Label,100.5\ncell1,处理组,2\ncell2,对照组,3\n"),
    )
    with service.access(identity) as workspace:
        assert len(workspace.project.samples) == 1
        assert workspace.project.workspace.data.obs.group.tolist() == ["处理组", "对照组"]


@pytest.mark.parametrize(
    "matrix,options",
    [
        ("id,f1\na,\n", {}),
        ("id,f1\na,NaN\n", {}),
        ("id,f1\na,inf\n", {}),
        ("id,f1\na,1\na,2\n", {}),
        ("id,f1,f1\na,1,2\n", {}),
        ("id,f1\na,1\n", {"observations_csv": "observation_id,group\nb,X\n"}),
        ("id,Group,f1\na,X,1\n", {"observations_csv": "observation_id,group\na,Y\n"}),
    ],
)
def test_invalid_matrix_is_not_coerced(matrix, options):
    with pytest.raises(ValueError):
        import_matrix_csv(matrix, **options)


def test_feature_only_is_empty_quantitation_and_survives_formal_save(tmp_path):
    data = import_feature_csv("feature_id,mz,custom\nf2,150.25,yes\nf1,200.5,no\n")
    assert data.shape == (0, 2)
    state = AnalysisWorkspace()
    state.replace(data)
    assert state.require_features().var_names.tolist() == ["f2", "f1"]
    with pytest.raises(ValueError, match="定量矩阵"):
        state.require_data()
    with pytest.raises(ValueError, match="定量矩阵"):
        state.normalize("total")
    store = ProjectStore(tmp_path)
    project = store.create("Features")
    project.workspace = state
    store.save(project)
    restored = store.open(project.folder)
    assert restored.workspace.require_features().shape == (0, 2)
    assert json.loads(restored.workspace.data.uns[METADATA_KEY])["quantitation_available"] is False
    with pytest.raises(ValueError):
        AnalysisWorkspace().replace(AnnData(np.empty((0, 2))))


def test_complete_package_keeps_baseline_reports_and_never_saves_source(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("Matrix")
    project.workspace.replace(import_matrix_csv("id,f1,f2\na,1.2345678901234567,2\nb,3,4\n"))
    project.workspace.normalize("log")
    before = (project.folder / "project.json").read_bytes()
    payload = export_package(project, "statistics")
    restored, description = read_package(payload)
    assert (project.folder / "project.json").read_bytes() == before
    assert not list((project.folder / "snapshots").iterdir())
    assert description["schema_version"] == 1
    assert restored.workspace.data.var_names.tolist() == ["f1", "f2"]
    np.testing.assert_array_equal(restored.workspace.data.X, project.workspace.data.X)
    np.testing.assert_array_equal(restored.workspace._original.X, project.workspace._original.X)
    assert restored.workspace.history() == project.workspace.history()


def test_catalogue_package_preserves_all_roots_branches_and_l3(tmp_path):
    from scMM.application.data_views import DataViewCatalog, initialize_catalog

    store = ProjectStore(tmp_path)
    project = store.create("Catalogue")
    data = AnnData(
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame({"mz": [100.0, 101.0]}, index=["x", "y"]),
    )
    view, _ = initialize_catalog(
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
    project.ion_state["registry"]["test_evidence"] = {"candidate": "unknown", "source": "synthetic"}
    restored, _ = read_package(export_package(project, "annotation"))
    assert len(restored.ion_state["roots"]) == 1
    assert len(restored.ion_state["branches"]) == 2
    assert restored.ion_state["registry"]["test_evidence"] == {
        "candidate": "unknown",
        "source": "synthetic",
    }
    root = next(iter(restored.ion_state["roots"].values()))["data"]
    np.testing.assert_array_equal(root.X, data.X)


def test_catalogue_complete_l2_availability_and_review_roundtrip(tmp_path):
    from scMM.application.data_views import (
        add_source_view,
        initialize_catalog,
        materialize_analysis_branch,
    )
    from scMM.ion.representation import preview_complete_availability

    project = ProjectStore(tmp_path).create("L2")
    measured = AnnData(
        np.array([[1.0, 2.0], [0.0, 3.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame({"mz": [100.0, 101.0]}, index=["x", "y"]),
    )
    view, _ = initialize_catalog(
        project,
        measured,
        source={"kind": "synthetic"},
        origin_kind="extraction",
        linearity="linear_abundance",
    )
    source = AnnData(
        np.array([[2.0, np.nan], [0.0, 7.0]]),
        obs=pd.DataFrame(index=["a", "b"]),
        var=pd.DataFrame({"quantifier_feature_id": ["x", "y"]}, index=["ec1", "ec2"]),
    )
    source.layers["scmm_quantifiable"] = np.array([[True, False], [True, True]])
    compound, _ = add_source_view(
        project, source, root_id=view["root_id"], level="L2", source_features=["x", "y"]
    )
    preview = preview_complete_availability(source, cell_ids=["a", "b"])
    materialize_analysis_branch(project, view_id=compound["id"], preview=preview)
    project.ion_state["registry"]["reviews"].append(
        {"decision": "unresolved", "source": "synthetic"}
    )
    restored, _ = read_package(export_package(project, "annotation"))
    np.testing.assert_array_equal(restored.ion_state["source_matrices"][compound["id"]].X, source.X)
    np.testing.assert_array_equal(
        restored.ion_state["source_matrices"][compound["id"]].layers["scmm_quantifiable"],
        source.layers["scmm_quantifiable"],
    )
    assert restored.ion_state["registry"]["reviews"][0]["decision"] == "unresolved"
    assert restored.workspace.data.X[1, 0] == 0


def test_archive_resource_limits_and_malformed_json_are_rejected(tmp_path):
    project = ProjectStore(tmp_path).create("Input")
    payload = export_package(project, "extraction")
    with pytest.raises(ValueError, match="大小限制"):
        read_package(payload, max_bytes=1)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", "[]")
    with pytest.raises(ValueError, match="协议"):
        read_package(stream.getvalue())


def test_zip_traversal_checksum_and_undeclared_content_are_rejected(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("Input")
    project.workspace.replace(import_matrix_csv("id,100\na,1\n"))
    payload = export_package(project, "extraction")
    for member, content in [
        ("../escape", b"bad"),
        ("project/project.json", b"{}"),
        ("secret.pkl", b"bad"),
    ]:
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(payload)) as source, zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                if info.filename != member:
                    target.writestr(info.filename, source.read(info.filename))
            target.writestr(member, content)
        with pytest.raises(ValueError):
            read_package(output.getvalue())


def test_import_is_transactional_and_statistics_requires_real_matrix(manager):
    service, identity = manager
    imported = import_exchange(
        service, identity, "annotation", values("feature_csv", matrix_csv="mz\n100.2\n101.2\n")
    )
    assert imported["revision"] == 2
    assert module_status(service, identity, "annotation")["feature_only"]
    before = service.current(identity)
    with pytest.raises(ValueError):
        import_exchange(
            service,
            identity,
            "statistics",
            values("matrix_csv", revision=2, matrix_csv="id,f1\na,bad\n"),
        )
    assert service.current(identity) == before
    content, _, _ = export_exchange(service, identity, "annotation", 2)
    with pytest.raises(ValueError, match="统计分析"):
        import_exchange(
            service,
            identity,
            "statistics",
            values("package", revision=2, file_base64=base64.b64encode(content).decode()),
        )
    assert service.current(identity) == before
    with pytest.raises(ValueError, match="特征注释"):
        import_exchange(
            service,
            identity,
            "extraction",
            values("feature_csv", revision=2, matrix_csv="mz\n100\n"),
        )


def test_native_import_and_csv_export_roundtrip(manager):
    service, identity = manager
    import_exchange(
        service,
        identity,
        "statistics",
        values(
            "matrix_csv",
            matrix_csv="Name,Class,100.1,200.2\na,A,0,1.2345678901234567\nb,B,3,4\n",
            observation_kind="sample",
        ),
    )
    content, _, _ = export_exchange(service, identity, "statistics", 2, "csv")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        data = import_matrix_csv(
            archive.read("matrix.csv").decode("utf-8-sig"),
            observations_csv=archive.read("observations.csv").decode("utf-8-sig"),
            features_csv=archive.read("features.csv").decode("utf-8-sig"),
        )
    np.testing.assert_array_equal(data.X, [[0.0, 1.2345678901234567], [3.0, 4.0]])
    content, _, _ = export_exchange(service, identity, "statistics", 2)
    result = import_exchange(
        service,
        identity,
        "annotation",
        values("package", revision=2, file_base64=base64.b64encode(content).decode()),
    )
    assert result["revision"] == 3
    assert module_status(service, identity, "annotation")["observation_kind"] == "sample"


def test_import_does_not_relabel_old_catalogue_branch_by_matching_sample_names(manager):
    from scMM.application.data_views import initialize_catalog

    service, identity = manager
    with service.access(identity) as workspace:
        original = import_matrix_csv("Sample,Label,100.5\nc1,Old,1\nc2,Old,2\n")
        original.obs["sample_id"] = "old-id"
        _view, branch = initialize_catalog(
            workspace.project,
            original,
            source={"kind": "synthetic"},
            origin_kind="extraction",
            linearity="linear_abundance",
        )
    import_exchange(
        service,
        identity,
        "statistics",
        values("matrix_csv", matrix_csv="Sample,Label,100.5\nc1,New,3\nc2,New,4\n"),
    )
    with service.access(identity) as workspace:
        old = workspace.project.ion_state["branches"][branch]["workspace"]["data"]
        assert old.obs.group.tolist() == ["Old", "Old"]
        assert old.obs.sample_id.tolist() == ["old-id", "old-id"]
        assert workspace.project.workspace.data.obs.group.tolist() == ["New", "New"]


def changed_manifest(content, update):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, "w") as target:
        for item in source.infolist():
            value = source.read(item.filename)
            if item.filename == "manifest.json":
                description = json.loads(value)
                update(description)
                value = json.dumps(description).encode()
            target.writestr(item.filename, value)
    return output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown_contract_field", True),
        ("schema_version", True),
        ("matrix_orientation", "features_by_observations"),
        ("missing_values", "fill_missing_with_zero"),
        ("feature_identity", "rounded_mz"),
        ("raw_spectra", "included"),
        ("models", "included"),
        ("quantitation_available", "true"),
    ],
)
def test_manifest_v1_rejects_unknown_fields_and_incompatible_fixed_contract(tmp_path, field, value):
    project = ProjectStore(tmp_path).create("Protocol")
    project.workspace.replace(import_matrix_csv("id,100\na,1\n"))
    content = export_package(project, "statistics")
    altered = changed_manifest(content, lambda manifest: manifest.update({field: value}))
    with pytest.raises(ValueError, match="协议"):
        read_package(altered)


@pytest.mark.parametrize("scope", ["artifact", "value_state", "missing_required"])
def test_manifest_v1_rejects_nested_unknown_and_missing_fields(tmp_path, scope):
    project = ProjectStore(tmp_path).create("Protocol")
    project.workspace.replace(import_matrix_csv("id,100\na,1\n"))
    content = export_package(project, "statistics")

    def update(manifest):
        if scope == "artifact":
            next(iter(manifest["files"].values()))["unknown"] = True
        elif scope == "value_state":
            manifest["value_states"]["X"]["unknown"] = True
        else:
            del manifest["created_at"]

    with pytest.raises(ValueError, match="协议"):
        read_package(changed_manifest(content, update))


@pytest.mark.parametrize(
    "field,value",
    [
        ("intensity_unit", "counts"),
        ("observation_kind", "sample"),
        ("quantitation_available", False),
        ("complete_catalogue", True),
        ("intensity_states", {"X": "raw"}),
        ("value_states", {}),
    ],
)
def test_manifest_declarations_must_match_native_matrix(tmp_path, field, value):
    project = ProjectStore(tmp_path).create("Protocol")
    project.workspace.replace(import_matrix_csv("id,100\na,1\n"))
    content = export_package(project, "statistics")
    altered = changed_manifest(content, lambda manifest: manifest.update({field: value}))
    with pytest.raises(ValueError, match="不一致"):
        read_package(altered)


def saved_files(project):
    from scMM.application.project_references import iter_project_artifacts

    return {
        path: path.read_bytes()
        for path in [
            project.folder / "project.json",
            *iter_project_artifacts(project.manifest, project.folder),
        ]
    }


@pytest.mark.parametrize("catalogue", [False, True])
def test_complete_package_replaces_nonempty_dataset_collection_without_saving(manager, catalogue):
    from scMM.application.data_views import initialize_catalog

    service, identity = manager
    original = import_matrix_csv("id,100,101\nold-a,1,2\nold-b,3,4\n")
    with service.access(identity) as workspace:
        target = workspace.project
        if catalogue:
            initialize_catalog(
                target,
                original,
                source={"kind": "old"},
                origin_kind="extraction",
                linearity="linear_abundance",
            )
        else:
            target.workspace.replace(original)
        service.store.save(target)
        previous_files = saved_files(target)
        old_id, old_folder = target.manifest["id"], target.folder

    incoming = service.store.create("Incoming collection")
    new_data = import_matrix_csv("id,200,201\nnew-a,5,6\nnew-b,7,8\n")
    view, _ = initialize_catalog(
        incoming,
        new_data,
        source={"kind": "incoming"},
        origin_kind="extraction",
        linearity="linear_abundance",
    )
    content = export_package(incoming, "annotation")
    original_content = bytes(content)
    import_exchange(
        service,
        identity,
        "annotation",
        values("package", file_base64=base64.b64encode(content).decode()),
    )
    with service.access(identity) as workspace:
        imported = workspace.project
        assert imported.manifest["id"] == old_id and imported.folder == old_folder
        assert set(imported.ion_state["roots"]) == {view["root_id"]}
        assert imported.workspace.data.obs_names.tolist() == ["new-a", "new-b"]
        assert imported.dirty
    assert content == original_content
    assert all(path.read_bytes() == value for path, value in previous_files.items())

    before = service.current(identity)
    corrupted = changed_manifest(content, lambda manifest: manifest.update(intensity_unit="wrong"))
    with pytest.raises(ValueError):
        import_exchange(
            service,
            identity,
            "annotation",
            values("package", revision=2, file_base64=base64.b64encode(corrupted).decode()),
        )
    assert service.current(identity) == before
    assert all(path.read_bytes() == value for path, value in previous_files.items())


@pytest.mark.parametrize("format", ["feature_csv", "h5ad"])
def test_feature_only_replaces_catalogue_without_fabricating_a_measurement_root(
    manager, tmp_path, format
):
    from scMM.application.data_views import initialize_catalog

    service, identity = manager
    with service.access(identity) as workspace:
        target = workspace.project
        initialize_catalog(
            target,
            import_matrix_csv("id,100\na,1\nb,2\n"),
            source={"kind": "old"},
            origin_kind="extraction",
            linearity="linear_abundance",
        )
        service.store.save(target)
        previous_files = saved_files(target)
    data = import_feature_csv("feature_id,mz\nx,150\ny,250\n")
    options = values(format, matrix_csv="feature_id,mz\nx,150\ny,250\n")
    if format == "h5ad":
        path = tmp_path / "features.h5ad"
        data.write_h5ad(path)
        options = values(format, file_base64=base64.b64encode(path.read_bytes()).decode())
    import_exchange(service, identity, "annotation", options)
    assert not module_status(service, identity, "annotation")["quantitation_available"]
    with service.access(identity) as workspace:
        project = workspace.project
        assert project.ion_state is None
        assert project.manifest["schema_version"] == 1
        assert project.workspace.require_features().shape == (0, 2)
        assert project.saved_reports == {} and project.views == {}
        with pytest.raises(ValueError, match="定量矩阵"):
            project.workspace.require_data()
        assert all(path.read_bytes() == value for path, value in previous_files.items())
        service.store.save(project)
        reopened = service.store.open(project.folder)
        assert reopened.workspace.require_features().shape == (0, 2)
        assert reopened.ion_state is None
