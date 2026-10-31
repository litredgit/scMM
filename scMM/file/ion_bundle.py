"""Self-contained project evidence bundles; no raw spectra or executable models."""

import io
import json
import stat
import zipfile
from copy import copy, deepcopy
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from scMM.application.data_view_storage import read_catalog_snapshot, write_catalog_snapshot
from scMM.application.data_views import freeze_active_branch
from scMM.application.projects import write_json


def export_project_bundle(project):
    """Export unsaved catalogue state without publishing or writing into its project."""
    state = freeze_active_branch(project)
    with TemporaryDirectory(prefix="scmm-ion-export-") as temporary:
        folder = Path(temporary)
        proxy = copy(project)
        proxy.folder = folder
        snapshot = folder / "snapshots" / "export"
        snapshot.mkdir(parents=True)
        relative, _ = write_catalog_snapshot(proxy, snapshot, state)
        catalog = json.loads((folder / relative).read_text(encoding="utf-8"))
        manifest = deepcopy(project.manifest)
        artifacts = {"data_catalog": relative}
        active = state["active_branch_id"]
        if active is not None:
            artifacts.update(
                {key: catalog["branches"][active][key] for key in ("current", "baseline", "views")}
            )
        manifest.update(schema_version=2, artifacts=artifacts)
        write_json(folder / "project.json", manifest)
        write_json(
            folder / "bundle.json",
            {
                "schema_version": 1,
                "kind": "scmm_ion_project",
                "raw_spectra": "external_references",
                "models": "excluded",
            },
        )
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(folder).as_posix())
        return stream.getvalue()


def import_project_bundle(content, *, max_bytes=2_000_000_000, max_files=10000):
    """Validate a whole archive in isolation; the caller chooses whether to install it."""
    if len(content) > max_bytes:
        raise ValueError("bundle exceeds configured import size budget")
    with TemporaryDirectory(prefix="scmm-ion-import-") as temporary:
        folder = Path(temporary)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > max_files or sum(item.file_size for item in entries) > max_bytes:
                raise ValueError("bundle exceeds expanded resource budget")
            seen, written = set(), 0
            for item in entries:
                name = PurePosixPath(item.filename)
                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or "\\" in item.filename
                    or ":" in item.filename
                    or not name.parts
                    or item.filename.casefold() in seen
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1
                ):
                    raise ValueError("unsafe, duplicate or encrypted bundle member")
                seen.add(item.filename.casefold())
                target = folder.joinpath(*name.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("expanded bundle exceeds resource budget")
                        output.write(chunk)
        description = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
        manifest = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        if (
            description.get("schema_version") != 1
            or description.get("kind") != "scmm_ion_project"
            or description.get("models") != "excluded"
            or manifest.get("schema_version") != 2
        ):
            raise ValueError("unsupported project bundle")
        import h5py

        logical_bytes = 0
        for path in folder.rglob("*"):
            if path.is_file() and h5py.is_hdf5(path):
                logical_bytes += validate_hdf5_container(path, max_bytes=max_bytes)
                if logical_bytes > max_bytes:
                    raise ValueError("bundle expanded scientific arrays exceed resource budget")
        state = read_catalog_snapshot(folder, manifest["artifacts"]["data_catalog"])
        for entry in state["branches"].values():
            entry["workspace"]["source"] = "imported_project_bundle"
        return {"manifest": manifest, "state": state, "description": description}


def validate_hdf5_container(path, *, max_bytes):
    """Reject external links/storage and oversized logical arrays before reading data."""
    import math

    import h5py

    total, seen = 0, set()
    with h5py.File(path, "r") as handle:

        def inspect(group):
            nonlocal total
            address = h5py.h5o.get_info(group.id).addr
            if address in seen:
                raise ValueError("cyclic or aliased HDF5 group")
            seen.add(address)
            encoding = group.attrs.get("encoding-type")
            if isinstance(encoding, bytes):
                encoding = encoding.decode("utf-8")
            if encoding in {"csr_matrix", "csc_matrix"}:
                shape = group.attrs.get("shape")
                if shape is None or math.prod(int(v) for v in shape) * 8 > max_bytes:
                    raise ValueError("sparse logical shape exceeds import budget")
            for name in group:
                link = group.get(name, getlink=True)
                if not isinstance(link, h5py.HardLink):
                    raise ValueError("external or symbolic HDF5 links are forbidden")
                node = group[name]
                if isinstance(node, h5py.Group):
                    inspect(node)
                else:
                    if node.is_virtual or node.external:
                        raise ValueError("external HDF5 dataset storage is forbidden")
                    total += node.size * max(node.dtype.itemsize, 1)
                    if total > max_bytes:
                        raise ValueError("logical HDF5 data exceeds import budget")

        inspect(handle)
    return total
