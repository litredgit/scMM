import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

from scMM.analysis import SupervisedAnalyzer, differential_features, marker_features
from scMM.analysis.statistics import _bh_fdr


def example():
    rng = np.random.default_rng(12)
    return AnnData(
        X=rng.uniform(1, 4, (80, 5)),
        obs=pd.DataFrame(
            {"label": ["a", "b"] * 40, "sample": np.repeat(np.arange(20).astype(str), 4)},
            index=[f"cell{i}" for i in range(80)],
        ),
    )


def test_fdr_and_markers_preserve_metadata():
    np.testing.assert_allclose(_bh_fdr([0.01, 0.04, 0.03]), [0.03, 0.04, 0.04])
    data = example()
    before = data.obs.copy()
    data.X[:, 0] = 1
    for method in ["mannwhitney", "welch"]:
        result = differential_features(data, "label", "a", "b", method=method)
        assert result.set_index("feature_id").loc["0", "p_value"] == 1
        assert result["fdr"].between(0, 1).all()
    assert len(marker_features(data, "label")) == 10
    pd.testing.assert_frame_equal(before, data.obs)
    data.X[0, 0] = -1
    with pytest.raises(ValueError, match="nonnegative"):
        differential_features(data, "label", "a", "b")


@pytest.mark.parametrize("model", ["logistic", "lda", "plsda", "random_forest"])
def test_models_with_group_holdout(model):
    analyzer = SupervisedAnalyzer(example(), "label", group_key="sample")
    params = {"n_estimators": 5, "n_jobs": 1} if model == "random_forest" else {}
    result = analyzer.evaluate(model, cv=3, model_params=params)
    assert set(analyzer.train_groups_).isdisjoint(analyzer.test_groups_)
    assert np.isfinite(result["cv_metrics"]["roc_auc"]["mean"])
    assert set(analyzer.roc_curves()) == {"a", "b"}


def test_quality_pdf_and_new_clustering(tmp_path):
    pytest.importorskip("matplotlib")
    from scMM.analysis import render_quality_report
    from scMM.plot.engine import PlotEngine

    data = example()
    data.obs["reference_intensity_100"] = data.X[:, 0]
    assert render_quality_report(data, tmp_path / "qc.pdf").read_bytes().startswith(b"%PDF")
    engine = PlotEngine.from_adata(data, tmp_path)
    assert engine.cluster_cells("kmeans", n_clusters=2) is engine
    assert engine.adata.uns["clusters_qc"]["n_clusters"] == 2
    assert hasattr(engine, "compute_trajectory")
    assert len(engine.differential_features("label", "a", "b")) == 5
    assert engine.plot_feature_scatter("1", "2", color_key="label").is_file()
    engine.adata.X[:, 2] = engine.adata.X[:, 1] * 2
    graph, _ = engine.feature_correlation_network(min_abs_correlation=0.99)
    assert graph.has_edge("1", "2")


@pytest.mark.parametrize("model", ["logistic", "random_forest"])
@pytest.mark.filterwarnings(
    "ignore:The set_(bad|under|over) function will be deprecated:PendingDeprecationWarning:shap.plots.colors._colors"
)
def test_optional_smote_and_shap(model):
    pytest.importorskip("shap")
    pytest.importorskip("imblearn")
    analyzer = SupervisedAnalyzer(example(), "label", group_key="sample")
    params = {"n_estimators": 5, "n_jobs": 1} if model == "random_forest" else {}
    analyzer.evaluate(model, cv=3, smote=True, model_params=params)
    explanation = analyzer.explain_shap(max_background=8, max_samples=4)
    assert explanation.values.shape[:2] == (4, 5)
    assert np.isfinite(explanation.values).all()


def test_group_support_gate_uses_sources_instead_of_cell_count():
    data = example()
    data.obs["sample"] = [f"{label}-{i // 40}" for i, label in enumerate(data.obs.label)]
    # Four groups globally, but only two groups per class despite forty cells each.
    before = data.copy()
    analyzer = SupervisedAnalyzer(data, "label", group_key="sample")
    with pytest.raises(ValueError, match="每类至少有 3 个来源组"):
        analyzer.evaluate(cv=2, test_size=0.5)
    assert not hasattr(analyzer, "model_")
    np.testing.assert_array_equal(data.X, before.X)
    pd.testing.assert_frame_equal(data.obs, before.obs)
    exploratory = SupervisedAnalyzer(data, "label")
    report = exploratory.evaluate(cv=2)
    audit = report["validation_audit"]
    assert audit["validation_mode"] == "cell_exploration"
    assert audit["all_source_support"]["a"] == {"cells": 40, "source_groups": None}
    assert any("细胞级探索" in message for message in audit["warnings"])


def test_group_support_is_recorded_for_holdout_and_each_cv_fold():
    analyzer = SupervisedAnalyzer(example(), "label", group_key="sample")
    audit = analyzer.evaluate(cv=3)["validation_audit"]
    assert audit["validation_mode"] == "grouped"
    for label in ("a", "b"):
        assert audit["all_source_support"][label] == {"cells": 40, "source_groups": 20}
        assert audit["train_source_support"][label] == {"cells": 32, "source_groups": 16}
        assert audit["test_source_support"][label] == {"cells": 8, "source_groups": 4}
        assert len(audit["cv_source_support"]) == 3
        for fold in audit["cv_source_support"]:
            assert fold["fit"][label]["source_groups"] >= 2
            assert fold["validation"][label]["source_groups"] >= 1
            assert fold["fit"][label]["cells"] + fold["validation"][label]["cells"] == 32
    assert any("不再是独立测试" in message for message in audit["warnings"])
    assert any("不能证明生物学独立" in message for message in audit["warnings"])


def test_history_caveats_do_not_change_training_or_claim_layer_lineage():
    import json

    plain = example()
    annotated = plain.copy()
    annotated.layers["before_imputation"] = annotated.X.copy()
    history = [
        {"operation": "impute", "layer": "imputed", "parameters": {"method": "knn"}},
        {"operation": "filter", "layer": "filtered", "parameters": {"min_feature_fraction": 0.2}},
        {"operation": "restore", "layer": "restored", "parameters": {"layer": "before_imputation"}},
    ]
    annotated.uns["scmm_workbench"] = {"history_json": json.dumps(history)}
    original = SupervisedAnalyzer(plain, "label", group_key="sample")
    restored = SupervisedAnalyzer(annotated, "label", group_key="sample", layer="before_imputation")
    original.evaluate(cv=3)
    audit = restored.evaluate(cv=3)["validation_audit"]
    np.testing.assert_array_equal(original.probabilities_, restored.probabilities_)
    assert audit["recorded_risk_operations"] == ["filter", "impute"]
    assert audit["input_layer"] == "before_imputation"
    assert any("其他层或已恢复步骤" in message for message in audit["warnings"])
    assert "不执行折内重预处理" in audit["history_scope"]
    assert annotated.uns["scmm_workbench"]["history_json"] == json.dumps(history)


@pytest.mark.parametrize("history", [None, "broken", "{}", '["bad step"]'])
def test_unknown_preprocessing_history_is_reported_without_inventing_safety(history):
    data = example()
    data.uns["scmm_workbench"] = {"history_json": history}
    analyzer = SupervisedAnalyzer(data, "label", group_key="sample")
    audit = analyzer.evaluate(cv=2)["validation_audit"]
    assert not audit["recorded_steps"]
    assert audit["input_intensity_state"] == "unknown"
    assert any("无法解析" in message for message in audit["warnings"])


def test_unlabelled_cells_are_excluded_and_blank_groups_are_rejected():
    data = example()
    data.obs.loc[data.obs_names[0], "label"] = None
    analyzer = SupervisedAnalyzer(data, "label", group_key="sample")
    audit = analyzer.evaluate(cv=2)["validation_audit"]
    assert audit["excluded_unlabelled_cells"] == 1
    assert sum(value["cells"] for value in audit["all_source_support"].values()) == 79
    data.obs.loc[data.obs_names[1], "sample"] = "  "
    with pytest.raises(ValueError, match="不能为空白"):
        SupervisedAnalyzer(data, "label", group_key="sample")


def test_three_source_groups_per_class_can_support_holdout_and_two_cv_folds():
    data = example()[:72].copy()
    data.obs["sample"] = np.repeat(["source-a", "source-b", "source-c"], 24)
    analyzer = SupervisedAnalyzer(data, "label", group_key="sample")
    audit = analyzer.evaluate(cv=2, test_size=1 / 3)["validation_audit"]
    assert set(analyzer.train_groups_).isdisjoint(analyzer.test_groups_)
    for label in ("a", "b"):
        assert audit["all_source_support"][label]["source_groups"] == 3
        assert audit["train_source_support"][label]["source_groups"] == 2
        assert audit["test_source_support"][label]["source_groups"] == 1
