"""Safe access to server-mounted data directories."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

SUPPORTED_RAW_SUFFIXES = frozenset({".raw", ".mzml", ".mzxml"})
UNAVAILABLE_PATH = "所选路径不可用。请在授权目录中重新选择。"


def _selected_path(root, selected_path):
    windows = PureWindowsPath(str(selected_path))
    if os.name != "nt" and (windows.drive or str(selected_path).startswith("\\")):
        raise PermissionError(UNAVAILABLE_PATH)
    return root.path / Path(selected_path)


@dataclass(frozen=True)
class StorageRoot:
    """A named directory that the UI is allowed to browse."""

    label: str
    path: Path

    def __post_init__(self) -> None:
        label = self.label.strip()
        if not label:
            raise ValueError("Storage root label cannot be empty")
        path = Path(self.path).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise NotADirectoryError(path)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class StorageEntry:
    """One directory or supported raw-data file below a storage root."""

    name: str
    relative_path: Path
    is_directory: bool
    size_bytes: int | None


class StorageCatalog:
    """Resolve and enumerate paths without allowing escape from configured roots."""

    def __init__(self, roots: Iterable[StorageRoot]) -> None:
        roots_by_label: dict[str, StorageRoot] = {}
        for root in roots:
            if root.label in roots_by_label:
                raise ValueError(f"Duplicate storage root label: {root.label}")
            roots_by_label[root.label] = root
        if not roots_by_label:
            raise ValueError("At least one storage root is required")
        self._roots = roots_by_label

    @property
    def roots(self) -> tuple[StorageRoot, ...]:
        """Return configured roots in display order."""
        return tuple(self._roots.values())

    def root(self, label: str) -> StorageRoot:
        """Look up a configured root by its display label."""
        try:
            return self._roots[label]
        except KeyError:
            raise PermissionError(UNAVAILABLE_PATH) from None

    def resolve(self, root_label: str, selected_path: str | Path) -> Path:
        """Resolve a selected path and reject traversal or symlink escapes."""
        root = self.root(root_label)
        candidate = _selected_path(root, selected_path)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise PermissionError(UNAVAILABLE_PATH) from None
        if not resolved.is_relative_to(root.path):
            raise PermissionError(UNAVAILABLE_PATH)
        return resolved

    def resolve_raw_file(self, root_label: str, selected_path: str | Path) -> Path:
        """Resolve a Thermo RAW or mzML/mzXML file below a configured root."""
        resolved = self.resolve(root_label, selected_path)
        try:
            is_file = resolved.is_file()
        except (OSError, RuntimeError, ValueError):
            raise PermissionError(UNAVAILABLE_PATH) from None
        if not is_file:
            raise PermissionError(UNAVAILABLE_PATH)
        if resolved.suffix.lower() not in SUPPORTED_RAW_SUFFIXES:
            raise ValueError("Only Thermo RAW, mzML and mzXML raw-data files are supported")
        return resolved

    def resolve_output_directory(self, root_label: str, selected_path: str | Path) -> Path:
        """Resolve an existing directory or one missing direct child for output."""
        root = self.root(root_label)
        candidate = _selected_path(root, selected_path)
        try:
            if candidate.is_symlink():
                raise PermissionError(UNAVAILABLE_PATH)
            parent = candidate.parent.resolve(strict=True)
            if not parent.is_dir():
                raise PermissionError(UNAVAILABLE_PATH)
            resolved = candidate.resolve()
            if resolved.exists() and not resolved.is_dir():
                raise PermissionError(UNAVAILABLE_PATH)
        except (OSError, RuntimeError, ValueError):
            raise PermissionError(UNAVAILABLE_PATH) from None
        if not resolved.is_relative_to(root.path):
            raise PermissionError(UNAVAILABLE_PATH)
        return resolved

    def list_entries(
        self,
        root_label: str,
        directory: str | Path = ".",
    ) -> tuple[StorageEntry, ...]:
        """List child directories and supported raw-data files."""
        root = self.root(root_label)
        resolved = self.resolve(root_label, directory)
        try:
            if not resolved.is_dir():
                raise PermissionError(UNAVAILABLE_PATH)
            children = list(resolved.iterdir())
        except (OSError, RuntimeError, ValueError):
            raise PermissionError(UNAVAILABLE_PATH) from None
        entries: list[StorageEntry] = []
        for child in children:
            try:
                if child.is_symlink():
                    child.resolve(strict=True).relative_to(root.path)
                is_directory = child.is_dir()
                if not is_directory and (
                    not child.is_file() or child.suffix.lower() not in SUPPORTED_RAW_SUFFIXES
                ):
                    continue
                stat = child.stat()
            except (OSError, RuntimeError, ValueError):
                continue
            entries.append(
                StorageEntry(
                    name=child.name,
                    relative_path=child.relative_to(root.path),
                    is_directory=is_directory,
                    size_bytes=None if is_directory else stat.st_size,
                )
            )
        return tuple(sorted(entries, key=lambda item: (not item.is_directory, item.name.lower())))
