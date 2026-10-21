"""Locked publication and recovery for legacy processed directories."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

logger = logging.getLogger(__name__)


def _paths(target):
    target = Path(target).expanduser()
    target = target.parent.resolve() / target.name
    key = hashlib.sha256(target.name.encode()).hexdigest()
    prefix = target.parent / f".scmm-dataset-{key}"
    return target, prefix.with_suffix(".lock"), prefix.with_suffix(".backup")


@contextmanager
def dataset_directory(target, *, read_only=False):
    """Serialize cooperating readers/writers and recover an interrupted rename."""
    target, lock, backup = _paths(target)
    try:
        handle = lock.open("rb" if read_only and lock.exists() else "a+b")
    except PermissionError:
        if not read_only:
            raise
        # Old datasets on read-only media have no sidecar lock. A directory
        # replacement during the read must produce an error, never a mixed result.
        before = target.stat()
        yield target
        after = target.stat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
        ):
            raise OSError(
                "Dataset directory changed during read; retry from a stable version"
            ) from None
        return
    with handle:
        if os.name == "nt":
            import msvcrt

            if not read_only or handle.writable():
                handle.seek(0)
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if target.is_symlink() or backup.is_symlink():
                raise ValueError("Dataset publication paths must not be symbolic links")
            if backup.exists() and not target.exists():
                backup.rename(target)
            yield target
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _remove_backup(backup):
    if backup.exists():
        shutil.rmtree(backup)


def save_directory(root, name, metadata, frames, *, overwrite):
    """Write/verify a complete sibling candidate, then publish with rollback."""
    root = Path(root).expanduser()
    safe_name = Path(name).name
    if safe_name in {"", ".", ".."}:
        raise ValueError(f"Invalid dataset name: {safe_name!r}")
    root.mkdir(parents=True, exist_ok=True)
    with dataset_directory(root / safe_name) as target:
        _, _, backup = _paths(target)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        if target.exists() and not target.is_dir():
            raise NotADirectoryError(target)
        # A leftover backup with a complete target means publication succeeded.
        # Refuse another overwrite if that backup cannot be safely removed.
        _remove_backup(backup)
        with TemporaryDirectory(prefix=".scmm-dataset-stage-", dir=target.parent) as staging:
            candidate = Path(staging) / "dataset"
            managed_files = {
                ".meta",
                *(
                    f"{stem}.{suffix}"
                    for stem in ("data", "peak_meta", "feature_meta", "feature_snr")
                    for suffix in ("pkl", "csv")
                ),
            }
            if target.exists():
                # Retain caller-owned reports and auxiliary files, never old frames.
                shutil.copytree(
                    target,
                    candidate,
                    symlinks=True,
                    ignore=lambda directory, names: (
                        managed_files.intersection(names) if Path(directory) == target else set()
                    ),
                )
            else:
                candidate.mkdir()
            with (candidate / ".meta").open("w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
            for stem, frame in frames:
                frame.to_pickle(candidate / f"{stem}.pkl")
                frame.to_csv(candidate / f"{stem}.csv")
                pd.testing.assert_frame_equal(pd.read_pickle(candidate / f"{stem}.pkl"), frame)
            with (candidate / ".meta").open(encoding="utf-8") as handle:
                json.load(handle)
            if target.exists():
                target.rename(backup)
            try:
                candidate.rename(target)
            except BaseException:
                if backup.exists():
                    backup.rename(target)
                raise
            # Publication has committed; cleanup failure must not masquerade as save failure.
            try:
                _remove_backup(backup)
            except OSError:
                logger.warning(
                    "Dataset saved; previous version remains at %s", backup, exc_info=True
                )
        return root / safe_name
