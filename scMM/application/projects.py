"""Project persistence: one editable dataset, an immutable reset point and reports.

Publish a new manifest only after every snapshot artifact has been written.
Snapshot directories are internal recovery artifacts, not user-facing branches.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from anndata import read_h5ad

from .parameters import load_defaults
from .processing import ProcessingParameters
from .storage import StorageCatalog, StorageRoot
from .tasks import utc_now
from .workbench import AnalysisWorkspace

PROJECT_ROOT = Path("~/data/results").expanduser()


@contextmanager
def project_lock(folder):
    """Cross-process save lock; released by the OS after a crashed writer."""
    with child_path(folder, ".project.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def child_path(folder, relative):
    """Manifest references may not escape their project, including via symlinks."""
    folder = Path(folder).resolve()
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("Invalid project artifact path")
    target = (folder / value).resolve()
    if not target.is_relative_to(folder):
        raise PermissionError("Project artifact escapes project directory")
    return target


@dataclass
class Project:
    folder: Path
    manifest: dict
    workspace: AnalysisWorkspace = field(default_factory=AnalysisWorkspace)
    saved_reports: dict = field(default_factory=dict)
    views: dict = field(default_factory=dict)
    dirty: bool = False
    saved_token: tuple | None = None
    report_token: tuple | None = None

    @property
    def samples(self):
        return self.manifest["samples"]

    @property
    def unsaved(self):
        return self.dirty or self.saved_token != self.workspace.token

    def add_files(self, storage, label, paths):
        existing = {s["path"] for s in self.samples}
        additions = []
        for path in paths:
            resolved = storage.resolve_raw_file(label, path)
            if str(resolved) in existing:
                raise ValueError(f"File already belongs to project: {resolved.name}")
            existing.add(str(resolved))
            additions.append(
                {
                    "id": uuid4().hex,
                    "name": resolved.stem,
                    "path": str(resolved),
                    "storage": label,
                    "group": "",
                    "subject": "",
                    "batch": "",
                    "parameters": None,
                }
            )
        self.manifest["samples"].extend(additions)
        self.dirty = True

    def validate_samples(self):
        if not str(self.manifest["name"]).strip():
            raise ValueError("Project name is required")
        names = [s["name"].strip() for s in self.samples]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Sample names must be nonempty and unique")
        if len({s["id"] for s in self.samples}) != len(self.samples):
            raise ValueError("Duplicate sample IDs")
        for sample in self.samples:
            if not re.fullmatch(r"[a-f0-9]{32}", sample["id"]):
                raise ValueError("Invalid sample ID")
            if sample["parameters"] is not None:
                ProcessingParameters(**sample["parameters"])


def sample_parameters(project, sample):
    """Resolve explicit overrides separately from automatic file-derived limits."""
    if sample and sample["parameters"] is not None:
        return dict(sample["parameters"])
    values = dict(project.manifest["parameters"])
    if not project.manifest.get("manual_parameters"):
        if project.manifest["feature_strategy"] == "shared":
            ranges = [s["auto_mz_range"] for s in project.samples if s.get("auto_mz_range")]
            if ranges:
                values.update(mz_min=min(r[0] for r in ranges), mz_max=max(r[1] for r in ranges))
        elif sample and sample.get("auto_mz_range"):
            values.update(zip(("mz_min", "mz_max"), sample["auto_mz_range"], strict=True))
    return values


class ProjectStore:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)

    def _folder(self, value):
        folder = Path(value).resolve(strict=True)
        if folder.parent != self.root or folder.is_symlink():
            raise PermissionError("Select a project directly inside the project root")
        return folder

    def list(self):
        entries = []
        for path in self.root.iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            try:
                manifest = self._manifest(path)
            except (ValueError, OSError, KeyError):
                continue
            entries.append(
                {
                    "path": str(path),
                    "name": manifest["name"],
                    "saved_at": manifest["saved_at"],
                    "samples": len(manifest["samples"]),
                }
            )
        return sorted(entries, key=lambda row: row["saved_at"], reverse=True)

    def _manifest(self, folder):
        path = child_path(folder, "project.json")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("schema_version") != 1 or not isinstance(result.get("samples"), list):
            raise ValueError("Unsupported or invalid project manifest")
        if (
            not isinstance(result.get("name"), str)
            or not isinstance(result.get("saved_at"), str)
            or not isinstance(result.get("revision"), int)
            or not isinstance(result.get("artifacts"), dict)
        ):
            raise ValueError("Incomplete project manifest")
        return result

    def create(self, name, defaults=None):
        name = name.strip()
        if not name:
            raise ValueError("Project name is required")
        identity = uuid4().hex
        slug = re.sub(r"[^\w-]+", "_", name)[:60] or "project"
        folder = self.root / f"{slug}_{identity[:12]}"
        folder.mkdir()
        for directory in ("processing", "analyses", "exports", "snapshots"):
            (folder / directory).mkdir()
        project = Project(
            folder,
            {
                "schema_version": 1,
                "id": identity,
                "name": name,
                "description": "",
                "revision": 0,
                "saved_at": utc_now(),
                "samples": [],
                "artifacts": {},
                "parameters": asdict((defaults or load_defaults()).processing),
                "feature_strategy": "shared",
                "feature_merge_ppm": 10.0,
            },
        )
        write_json(folder / "project.json", project.manifest)
        project.saved_token = project.workspace.token
        return project

    def open(self, folder):
        folder = self._folder(folder)
        manifest = self._manifest(folder)
        project = Project(folder, manifest)
        project.validate_samples()
        ProcessingParameters(**manifest["parameters"])
        artifacts = manifest["artifacts"]
        if artifacts:
            data = read_h5ad(child_path(folder, artifacts["current"]))
            baseline = read_h5ad(child_path(folder, artifacts["baseline"]))
            project.workspace.replace(data, source=str(folder))
            project.workspace._validate(baseline)
            project.workspace._original = baseline
            project.saved_reports = json.loads(
                data.uns.get("scmm_workbench", {}).get("reports_json", "{}")
            )
            if "views" in artifacts:
                project.views = json.loads(
                    child_path(folder, artifacts["views"]).read_text(encoding="utf-8")
                )
        project.saved_token = project.workspace.token
        return project

    def save(self, project):
        folder = self._folder(project.folder)
        project.validate_samples()
        ProcessingParameters(**project.manifest["parameters"])
        with project_lock(folder):
            disk = self._manifest(folder)
            if disk["revision"] != project.manifest["revision"]:
                raise RuntimeError("Project was saved by another session; reopen before saving")
            candidate = deepcopy(project.manifest)
            saved_reports = dict(project.saved_reports)
            if project.workspace.data is not None:
                snapshot = child_path(folder, f"snapshots/{uuid4().hex}")
                snapshot.mkdir()
                catalog = StorageCatalog((StorageRoot("snapshot", snapshot),))
                current = project.workspace.save_h5ad(catalog, "snapshot", ".", "current.h5ad")
                project.workspace._original.write_h5ad(snapshot / "baseline.h5ad")
                # Loaded reports are read-only artifacts. Preserve only while data is unchanged.
                if (
                    project.saved_reports
                    and (project.report_token or project.saved_token) == project.workspace.token
                ):
                    data = read_h5ad(current)
                    fresh = json.loads(data.uns["scmm_workbench"]["reports_json"])
                    data.uns["scmm_workbench"]["reports_json"] = json.dumps(
                        {**project.saved_reports, **fresh}
                    )
                    data.write_h5ad(current)
                candidate["artifacts"] = {
                    "current": str(current.relative_to(folder)),
                    "baseline": str((snapshot / "baseline.h5ad").relative_to(folder)),
                    "views": str((snapshot / "views.json").relative_to(folder)),
                }
                write_json(snapshot / "views.json", project.views)
                saved = read_h5ad(current)
                saved_reports = json.loads(saved.uns["scmm_workbench"]["reports_json"])
            candidate.update(revision=disk["revision"] + 1, saved_at=utc_now())
            write_json(folder / "project.json", candidate)
            project.manifest = candidate
            project.saved_reports = saved_reports
            project.saved_token = project.workspace.token
            project.report_token = project.workspace.token
            project.dirty = False
