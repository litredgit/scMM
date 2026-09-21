"""Additional analysis methods without replacing trajectory capabilities."""

from ..analysis.statistics import differential_features, marker_features


class StatisticsMixin:
    def differential_features(self, group_key, group_a, group_b, **kwargs):
        return differential_features(self.adata, group_key, group_a, group_b, **kwargs)

    def marker_features(self, cluster_key="cluster", **kwargs):
        return marker_features(self.adata, cluster_key, **kwargs)

    def feature_correlation_network(
        self, *, method="pearson", min_abs_correlation=0.7, top_features=None
    ):
        """Return an explicit correlation graph, separate from feature-distance embedding."""
        import networkx as nx
        import numpy as np
        import pandas as pd

        if method not in {"pearson", "spearman", "kendall"}:
            raise ValueError("unknown correlation method")
        if not 0 <= min_abs_correlation <= 1:
            raise ValueError("min_abs_correlation must be between zero and one")
        X = self._get_X()
        selected = np.arange(self.adata.n_vars)
        if top_features is not None:
            if int(top_features) < 1:
                raise ValueError("top_features must be positive")
            selected = np.argsort(np.nanvar(X, axis=0))[-int(top_features) :]
        corr = pd.DataFrame(X[:, selected], columns=self.adata.var_names[selected]).corr(
            method=method
        )
        graph = nx.Graph()
        graph.add_nodes_from(corr.columns)
        for i, left in enumerate(corr.columns):
            for j in range(i + 1, len(corr.columns)):
                value = float(corr.iloc[i, j])
                if np.isfinite(value) and abs(value) >= min_abs_correlation:
                    graph.add_edge(left, corr.columns[j], correlation=value, weight=abs(value))
        return graph, corr

    def plot_feature_scatter(
        self, feature_a, feature_b, *, color_key=None, regression=True, output_file=None
    ):
        """Plot two named features or nearest numeric masses; support categorical colors."""
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from matplotlib.figure import Figure
        from scipy.stats import linregress

        def index(feature):
            if str(feature) in self.adata.var_names:
                return self.adata.var_names.get_loc(str(feature))
            masses = np.asarray(self.adata.var.get("mz", self.adata.var_names), dtype=float)
            return int(np.abs(masses - float(feature)).argmin())

        values = self._get_X()
        x, y = values[:, index(feature_a)], values[:, index(feature_b)]
        fig = Figure(figsize=(5, 5))
        ax = fig.subplots()
        options = {}
        labels = None
        if color_key is not None:
            colors = self.adata.obs[color_key]
            if pd.api.types.is_numeric_dtype(colors):
                options = {"c": colors, "cmap": "viridis"}
            else:
                codes, labels = pd.factorize(colors)
                options = {"c": codes, "cmap": "tab20"}
        scatter = ax.scatter(x, y, s=8, alpha=0.7, **options)
        if color_key is not None:
            bar = fig.colorbar(scatter, ax=ax, label=color_key)
            if labels is not None:
                bar.set_ticks(range(len(labels)), labels=labels.astype(str))
        finite = np.isfinite(x) & np.isfinite(y)
        if regression and finite.sum() >= 2 and np.ptp(x[finite]) > 0:
            slope, intercept, r, p, _ = linregress(x[finite], y[finite])
            xx = np.sort(x[finite])
            ax.plot(xx, intercept + slope * xx, color="red")
            ax.set_title(f"R²={r * r:.3f}, p={p:.2g}")
        ax.set(xlabel=str(feature_a), ylabel=str(feature_b))
        target = Path(output_file) if output_file else self.path / "feature_scatter.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, bbox_inches="tight")
        return target
