import numpy as np
import pandas as pd
import pytest
from anndata import AnnData

pytest.importorskip("plotly")

from scMM.application.workbench import AnalysisWorkspace
from scMM.ui.analysis_plots import violin_figure, volcano_figure


def test_feature_selection_and_hiding_zero_never_recompute_fdr(monkeypatch):
    data = AnnData(
        np.array([[0, 1], [2, 1], [4, 1], [1, 2], [3, 2], [5, 2.0]]),
        obs=pd.DataFrame({"group": ["a"] * 3 + ["b"] * 3}, index=list("abcdef")),
    )
    state = AnalysisWorkspace()
    state.replace(data)
    result = state.differential("group", "a", "b")
    expected = result["table"].copy()

    def no_retest(*args, **kwargs):
        raise AssertionError("plots must use the already corrected full feature table")

    monkeypatch.setattr("scMM.analysis.statistics.differential_features", no_retest)
    volcano = volcano_figure(expected)
    violin = violin_figure(state.data, result, ["0"], hide_zero=True)
    assert len(volcano.data[0].x) == 2
    assert len(violin.data[0].y) == 2
    assert "全局 FDR" in violin.layout.annotations[0].text
    pd.testing.assert_frame_equal(expected, result["table"])
