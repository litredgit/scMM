"""Complete metadata-only dependency enumeration for old and catalogue projects."""

import json

from anndata import read_h5ad

from .projects import child_path


def iter_project_artifacts(manifest, folder):
    version = manifest.get("schema_version")
    if version not in {1, 2}:
        raise ValueError("unsupported project reference schema")
    artifacts = manifest["artifacts"]
    paths = {child_path(folder, path) for path in artifacts.values() if isinstance(path, str)}
    if version == 2:
        catalog_path = child_path(folder, artifacts["data_catalog"])
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog.get("schema_version") != 1 or not isinstance(catalog.get("files"), dict):
            raise ValueError("invalid referenced data catalogue")
        paths.update(child_path(folder, path) for path in catalog["files"])
        required = [catalog["registry_artifact"], *catalog["source_matrices"].values()]
        required += [row["artifact"] for row in catalog["roots"].values()]
        required += [
            row[key]
            for row in catalog["branches"].values()
            for key in ("current", "baseline", "views")
        ]
        if not set(required).issubset(catalog["files"]):
            raise ValueError("catalogue reference closure is incomplete")
    if any(not path.is_file() for path in paths):
        raise ValueError("referenced project artifact is missing")
    yield from sorted(paths)


def project_references(manifest, folder):
    from .trash import _references

    paths = list(iter_project_artifacts(manifest, folder))
    refs = set(paths) | set(_references(manifest, folder))
    for path in paths:
        if path.suffix.lower() == ".h5ad":
            data = read_h5ad(path, backed="r")
            try:
                refs.update(_references(dict(data.uns), folder))
                for key, value in data.uns.items():
                    if (
                        isinstance(value, str)
                        and str(key).startswith("scmm_")
                        and str(key).endswith("_json")
                    ):
                        refs.update(_references(json.loads(value), folder))
            finally:
                data.file.close()
        elif path.suffix.lower() == ".json":
            refs.update(_references(json.loads(path.read_text(encoding="utf-8")), folder))
    return sorted(refs)


def memory_project_references(project):
    """Enumerate all live branches without copying matrices or reading external files."""
    from .trash import _references

    refs = set(_references([project.manifest, project.views], project.folder))
    workspaces = [vars(project.workspace)]
    matrices = []
    if project.ion_state is not None:
        state = project.ion_state
        refs.update(
            _references([state.get("registry", {}), state.get("views", {})], project.folder)
        )
        for root in state["roots"].values():
            refs.update(_references(root["metadata"], project.folder))
            matrices.append(root["data"])
        for branch in state["branches"].values():
            workspaces.append(branch["workspace"])
            refs.update(_references(branch.get("presentation", {}), project.folder))
        matrices.extend(state.get("source_matrices", {}).values())
    for workspace in workspaces:
        refs.update(_references({"source": workspace["source"]}, project.folder))
        matrices.extend(
            data for data in (workspace["data"], workspace["_original"]) if data is not None
        )
    for data in matrices:
        refs.update(_references(dict(data.uns), project.folder))
        for key, value in data.uns.items():
            if (
                str(key).startswith("scmm_")
                and str(key).endswith("_json")
                and isinstance(value, str)
            ):
                refs.update(_references(json.loads(value), project.folder))
    return sorted(refs)
