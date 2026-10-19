"""Invalidate matrix-dependent artifacts without discarding measured layers or metadata."""


def invalidate_derived(data):
    metadata = data.uns.setdefault("scmm_workbench", {})
    for column in metadata.get("derived_obs", []):
        if column in data.obs:
            del data.obs[column]
    metadata["derived_obs"] = []
    for mapping in (data.obsm, data.obsp, data.varm, data.varp):
        mapping.clear()
    for key in list(data.uns):
        if key.endswith(("_params", "_qc")) or key in {
            "neighbors",
            "pca",
            "umap",
            "tsne",
            "scmm_saved_reports",
        }:
            del data.uns[key]
