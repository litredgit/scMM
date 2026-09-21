"""Additional analysis methods without replacing trajectory capabilities."""

from ..analysis.statistics import differential_features, marker_features


class StatisticsMixin:
    def differential_features(self, group_key, group_a, group_b, **kwargs):
        return differential_features(self.adata, group_key, group_a, group_b, **kwargs)

    def marker_features(self, cluster_key="cluster", **kwargs):
        return marker_features(self.adata, cluster_key, **kwargs)
