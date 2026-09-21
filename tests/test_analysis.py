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
def test_optional_smote_and_shap(model):
    pytest.importorskip("shap")
    pytest.importorskip("imblearn")
    analyzer = SupervisedAnalyzer(example(), "label", group_key="sample")
    params = {"n_estimators": 5, "n_jobs": 1} if model == "random_forest" else {}
    analyzer.evaluate(model, cv=3, smote=True, model_params=params)
    explanation = analyzer.explain_shap(max_background=8, max_samples=4)
    assert explanation.values.shape[:2] == (4, 5)
    assert np.isfinite(explanation.values).all()
