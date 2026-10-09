"""Project-local reusable extraction artifacts with file and parameter identity."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import numpy as np

from .projects import child_path, write_json


def file_identity(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "inode": stat.st_ino,
    }


def digest_file(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def signature(path, parameters):
    params = asdict(parameters) if not isinstance(parameters, dict) else dict(parameters)
    return {"version": 1, "file": file_identity(path), "parameters": json.loads(json.dumps(params))}


def save_preview(project, sample, preview, parameters, before):
    identity = signature(sample["path"], parameters)
    if identity != before:
        raise ValueError("Input changed during preview; reopen the file")
    folder = child_path(project.folder, f"processing/preview-{uuid4().hex}")
    folder.mkdir()
    preview.last_dataset.save_h5ad(folder / "data.h5ad")
    np.save(folder / "targets.npy", preview.last_targets, allow_pickle=False)
    digest = digest_file(folder / "data.h5ad")
    preview.last_detection.traces.to_csv(folder / "traces.csv", index=False)
    write_json(
        folder / "detection.json",
        {
            "reference_mz": preview.last_detection.reference_mz,
            "window_ranges": preview.last_detection.window_ranges,
            "cell_count": preview.last_detection.cell_count,
        },
    )
    write_json(folder / "identity.json", {**identity, "sha256": digest})
    return str(folder.relative_to(project.folder))


def reusable_preview(project_folder, sample, targets=None):
    record = sample.get("preview", {})
    if not record.get("artifact"):
        return None
    try:
        folder = child_path(project_folder, record["artifact"])
        identity = json.loads((folder / "identity.json").read_text())
        expected = signature(sample["path"], sample["parameters"])
        if any(identity.get(key) != value for key, value in expected.items()):
            return None
        if targets is not None and not np.array_equal(
            np.load(folder / "targets.npy", allow_pickle=False), targets
        ):
            return None
        output = child_path(folder, "data.h5ad")
        if digest_file(output) != identity["sha256"]:
            return None
        return output
    except (OSError, ValueError, KeyError):
        return None


def load_detection(output):
    import pandas as pd

    from .raw_preview import CellDetectionPreview

    folder = Path(output).parent
    metadata = json.loads((folder / "detection.json").read_text())
    return CellDetectionPreview(
        pd.read_csv(folder / "traces.csv"),
        tuple(metadata["reference_mz"]),
        tuple(tuple(pair) for pair in metadata["window_ranges"]),
        metadata["cell_count"],
    )


def shared_cache_key(request):
    from .project_batch import SHARED_FIELDS

    payload = {
        "version": 1,
        "files": [file_identity(s["path"]) for s in request["samples"]],
        "parameters": {k: request["parameters"][k] for k in SHARED_FIELDS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def cached_shared_targets(project_folder, request):
    try:
        key = shared_cache_key(request)
        path = child_path(project_folder, f"processing/shared-{key}.npy")
        metadata = json.loads(path.with_suffix(".json").read_text())
        if digest_file(path) != metadata["sha256"]:
            return None
        return np.load(path, allow_pickle=False)
    except (OSError, ValueError, KeyError):
        return None


def prepare_shared_targets(project, request):
    """Use the batch feature definition for previews, making reuse exact."""
    import pyopenms as oms

    from scMM.file.io import extract_peaks, load_single_file, sum_spec
    from scMM.util.peak import filter_spectrum

    from .processing import ProcessingParameters

    cached = cached_shared_targets(project.folder, request)
    if cached is not None:
        return cached
    key = shared_cache_key(request)
    base = ProcessingParameters(**request["parameters"])
    grid, total = None, None
    for sample in request["samples"]:
        experiment, _ = load_single_file(sample["path"])
        summed = sum_spec(
            experiment,
            resolution_200=base.resolution,
            points_per_fwhm=base.resample_points_per_fwhm,
            mz_range=(base.mz_min, base.mz_max),
        )
        mz, intensity = summed.get_peaks()
        if grid is None:
            grid, total = mz.copy(), intensity.astype(float)
        else:
            total += np.interp(grid, mz, intensity, left=0.0, right=0.0)
    spectrum = oms.MSSpectrum()
    spectrum.set_peaks((grid, total))
    filtered = filter_spectrum(spectrum, snr_threshold=base.ms_peak_snr_threshold)
    targets, _ = extract_peaks(filtered, resolution_200=base.resolution)
    targets = targets[(targets >= base.mz_min) & (targets <= base.mz_max)]
    if not len(targets):
        raise ValueError("No shared features detected")
    if key != shared_cache_key(request):
        raise ValueError("Input changed while preparing shared features")
    path = child_path(project.folder, f"processing/shared-{key}.npy")
    temporary = path.with_name(f".{uuid4().hex}.npy")
    try:
        np.save(temporary, targets, allow_pickle=False)
        temporary.replace(path)
        write_json(path.with_suffix(".json"), {"sha256": digest_file(path)})
    finally:
        temporary.unlink(missing_ok=True)
    return targets
