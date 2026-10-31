"""View selection, quantitative spaces and descriptive sensitivity contracts."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.analysis.statistics import differential_features
from scMM.application.analysis_inputs import (
    compare_views,
    replicate_summary,
    resolve_analysis_input,
)
from scMM.application.data_views import DataViewCatalog, activate_view, initialize_catalog
from scMM.application.projects import Project
from scMM.ion.semantics import unknown_state, write_value_states


def example(tmp_path):
    project = Project(tmp_path, {"name": "test", "samples": []})
    data = AnnData(
        np.arange(1.0, 19.0).reshape(6, 3),
        obs=pd.DataFrame(
            {"group": ["a"] * 3 + ["b"] * 3, "sample_id": ["s1"] * 3 + ["s2"] * 3},
            index=[f"c{i}" for i in range(6)],
        ),
        var=pd.DataFrame({"mz": [100.0, 101.0, 102.0]}, index=["f1", "f2", "f3"]),
    )
    write_value_states(data, {"X": {**unknown_state(), "space": "linear_abundance"}})
    return project, data


def test_preserve_existing_model_reports_and_log_effect_guard(tmp_path):
    project, data = example(tmp_path)
    project.workspace.replace(data)
    baseline = project.workspace._original.copy()
    project.workspace.differential("group", "a", "b")
    project.workspace.normalize("log")
    project.workspace.reduce(method="pca", store_key="X_preexisting", n_components=2)
    before = deepcopy(project.workspace.results)
    token = project.workspace.token
    project.views = {"user": "preserve"}
    view, branch = initialize_catalog(
        project,
        baseline,
        source={"kind": "test"},
        origin_kind="imported_feature",
        linearity="linear_abundance",
        preserve_active=True,
    )
    assert project.workspace.token == token
    assert project.views == {"user": "preserve"}
    assert set(project.workspace.results) == set(before)
    context = resolve_analysis_input(project)
    assert context["branch_id"] == branch and context["view_id"] == view["id"]
    with pytest.raises(ValueError, match="linear_abundance"):
        project.workspace.differential("group", "a", "b")
    layer = project.workspace.data.uns["scmm_workbench"]["original_layer"]
    result = project.workspace.differential("group", "a", "b", effect_layer=layer)
    assert result["numerical_inputs"]["test_layer"] == "X"
    expected = differential_features(data, "group", "a", "b")
    np.testing.assert_allclose(result["table"].log2_fold_change, expected.log2_fold_change)
    with pytest.raises(ValueError, match="combined"):
        differential_features(data, "group", "a", "b", layer=layer, test_layer="X")


def test_unknown_space_not_certified_and_legacy_is_explicit(tmp_path):
    project, data = example(tmp_path)
    data.uns.clear()
    table = differential_features(data, "group", "a", "b")
    assert table.attrs["input"]["legacy_unverified_abundance"]
    initialize_catalog(
        project, data, source={"kind": "test"}, origin_kind="imported_feature", linearity="unknown"
    )
    with pytest.raises(ValueError, match="linear_abundance"):
        project.workspace.differential("group", "a", "b")


def test_metadata_sync_all_branches_and_comparison_diagnostics(tmp_path):
    from scMM.application.web_projects import sync_metadata

    project, data = example(tmp_path)
    view, branch = initialize_catalog(
        project,
        data,
        source={"kind": "test"},
        origin_kind="imported_feature",
        linearity="linear_abundance",
    )
    catalog = DataViewCatalog.from_state(project.ion_state)
    _, second = catalog.create_feature_view(
        root_id=view["root_id"],
        cell_ids=list(data.obs_names),
        feature_ids=["f1", "f2"],
        expected_revision=1,
    )
    project.ion_state = catalog.export_state()
    project.manifest["samples"] = [
        dict(id=key, name=key, group="updated", subject="subject", batch="batch")
        for key in ("s1", "s2")
    ]
    sync_metadata(project)
    for entry in project.ion_state["branches"].values():
        assert set(entry["workspace"]["data"].obs.group) == {"updated"}
    root = next(iter(project.ion_state["roots"].values()))["data"]
    assert set(root.obs.group) == {"a", "b"}
    report = compare_views(project, branch_ids=[branch, second], normalization_mode="independent")
    assert [entry["input"]["shape"][1] for entry in report["branches"]] == [3, 2]
    with pytest.raises(ValueError, match="record"):
        compare_views(
            project,
            branch_ids=[branch, second],
            normalization_mode="shared",
            shared_factors=dict.fromkeys(data.obs_names, 1.0),
        )
    activate_view(
        project,
        view_id=project.ion_state["branches"][second]["view_id"],
        branch_id=second,
        expected_catalog_revision=2,
    )
    with pytest.raises(ValueError, match="activate"):
        resolve_analysis_input(project, branch_id=branch)


def test_replicate_export_and_ec_not_mz(tmp_path):
    from scMM.util.lipid_annotation import dataset_inputs

    _project, data = example(tmp_path)
    summary = replicate_summary(data, replicate_key="sample_id", group_key="group")
    assert list(summary.cell_count) == [3, 3]
    np.testing.assert_allclose(summary.f1, [4, 13])
    data.uns["scmm_analysis_input_json"] = '{"variable_kind":"empirical_compound"}'
    with pytest.raises(ValueError, match="m/z"):
        dataset_inputs(data)


def test_saved_comparison_is_json_safe_and_normalization_claims_are_checked(tmp_path):
    import json

    from scMM.application.analysis_inputs import apply_shared_normalization
    from scMM.application.projects import ProjectStore

    store = ProjectStore(tmp_path)
    project = store.create("sensitivity")
    _, data = example(tmp_path)
    view, first = initialize_catalog(
        project,
        data,
        source={"kind": "synthetic"},
        origin_kind="extraction",
        linearity="linear_abundance",
    )
    catalog = DataViewCatalog.from_state(project.ion_state)
    _, second = catalog.create_feature_view(
        root_id=view["root_id"],
        cell_ids=list(data.obs_names),
        feature_ids=["f1", "f2"],
        expected_revision=1,
    )
    for entry in catalog._branches.values():
        entry["workspace"].reduce(method="pca", store_key="X_compare", n_components=2)
    project.workspace = catalog.workspace
    project.ion_state = catalog.export_state()
    store.save(project)
    project = store.open(project.folder)
    report = compare_views(project, branch_ids=[first, second], normalization_mode="independent")
    json.dumps(report, allow_nan=False)
    assert report["branches"][0]["pca_loadings"]
    from scMM.application.data_views import freeze_active_branch

    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    factors = dict.fromkeys(data.obs_names, 2.0)
    for entry in catalog._branches.values():
        apply_shared_normalization(entry["workspace"], factors)
    project.workspace = catalog.workspace
    project.ion_state = catalog.export_state()
    assert (
        compare_views(
            project, branch_ids=[first, second], normalization_mode="shared", shared_factors=factors
        )["normalization_mode"]
        == "shared"
    )
    project.workspace.normalize("total")
    with pytest.raises(ValueError, match="superseded"):
        compare_views(
            project, branch_ids=[first, second], normalization_mode="shared", shared_factors=factors
        )
    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    _, other = catalog.add_measurement(
        data,
        source={"kind": "different acquisition"},
        origin_kind="extraction",
        value_semantics="linear_abundance",
    )
    project.workspace = catalog.workspace
    project.ion_state = catalog.export_state()
    with pytest.raises(ValueError, match="same measurement root"):
        compare_views(project, branch_ids=[first, other], normalization_mode="independent")
