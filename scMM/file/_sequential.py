"""Sequential, file-local extraction with explicit feature-merging policy."""

from pathlib import Path

import numpy as np
import pandas as pd
import pyopenms as oms

from ..util.peak import filter_spectrum
from ._dataset_loading import (
    DatasetState,
    _annotate_single_file_frames,
    _file_signature,
    make_feature_metadata,
    validate_mz_range,
)
from .io import align_frame, extract_peaks, load_single_file, sum_spec


def load_directory(
    cls,
    directory,
    ref_mz,
    *,
    feature_strategy="shared",
    feature_merge_ppm=10.0,
    msconvert_path=None,
    raw_timezone=None,
    dtype=np.float64,
    ppm_tol=10.0,
    resolution=35000.0,
    resample_points_per_fwhm=5.0,
    ms_peak_snr_threshold=10.0,
    prominence_ratio=None,
    distance=3,
    n_jobs=1,
    progress_callback=None,
    metadata_by_file=None,
    mz_range=(100.0, 1000.0),
    **preprocess,
):
    if msconvert_path is not None:
        raise ValueError(
            "Automatic RAW conversion was removed; use ThermoRawReader or convert explicitly"
        )
    load_options = {"raw_timezone": raw_timezone} if raw_timezone is not None else {}
    if feature_strategy not in {"shared", "independent"}:
        raise ValueError("feature_strategy must be shared or independent")
    if not np.isfinite(feature_merge_ppm) or feature_merge_ppm < 0:
        raise ValueError("feature_merge_ppm must be finite and nonnegative")
    if not np.isfinite(ref_mz) or ref_mz <= 0:
        raise ValueError("ref_mz must be positive and finite")
    mz_range = validate_mz_range(mz_range, ref_mz)
    root = Path(directory).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(root)
    files = sorted(
        p for p in root.iterdir() if p.suffix.lower() in {".mzml", ".mzxml", ".raw"} and p.is_file()
    )
    if not files:
        raise FileNotFoundError(f"No supported MS files in {root}")
    peak_options = dict(
        dtype=dtype, prominence_ratio=prominence_ratio, distance=distance, resolution_200=resolution
    )

    def report(value, message):
        if progress_callback is not None:
            progress_callback(value, message)

    objects = []
    signatures = {source: _file_signature(source) for source in files}
    targets = None
    if feature_strategy == "shared":
        grid, total = None, None
        for i, source in enumerate(files):
            exp, _ = load_single_file(source, **load_options)
            summed = sum_spec(
                exp,
                resolution_200=resolution,
                points_per_fwhm=resample_points_per_fwhm,
                mz_range=mz_range,
            )
            mz, intensity = summed.get_peaks()
            if grid is None:
                grid, total = mz.copy(), intensity.astype(float)
            else:
                total += np.interp(grid, mz, intensity, left=0.0, right=0.0)
            del exp, summed
            report(0.4 * (i + 1) / len(files), f"Shared spectrum {i + 1}/{len(files)}")
        summed = oms.MSSpectrum()
        summed.set_peaks((grid, total))
        filtered = filter_spectrum(summed, snr_threshold=ms_peak_snr_threshold)
        targets, _ = extract_peaks(filtered, **peak_options)
        targets = targets[(targets >= mz_range[0]) & (targets <= mz_range[1])]
        del summed, filtered, grid, total
        if not len(targets):
            raise ValueError("No features detected in shared spectrum")
    for i, source in enumerate(files):
        if _file_signature(source) != signatures[source]:
            raise ValueError(f"MS file changed between passes: {source}")

        def file_progress(value, message, file_index=i, name=source.name):
            report(
                0.4 + 0.55 * (file_index + value) / len(files),
                f"{name}: {message}",
            )

        file_preprocess = {**preprocess, "progress_callback": file_progress}
        if targets is None:
            obj = cls.load_from_file(
                source,
                ref_mz,
                dtype=dtype,
                ppm_tol=ppm_tol,
                resolution=resolution,
                resample_points_per_fwhm=resample_points_per_fwhm,
                ms_peak_snr_threshold=ms_peak_snr_threshold,
                prominence_ratio=prominence_ratio,
                distance=distance,
                mz_range=mz_range,
                **load_options,
                **file_preprocess,
            )
        else:
            exp, meta = load_single_file(source, **load_options)
            frame, obs = align_frame(exp, targets, ppm=ppm_tol, **peak_options)
            del exp
            _annotate_single_file_frames(obs, meta)
            obs["frame_id"] = obs.index.to_numpy()
            obs["acquisition_time"] = meta["timestamp"] + obs["rt"].to_numpy()
            meta["ref_mz"] = ref_mz
            meta["mz_range"] = list(mz_range)
            obj = cls._from_raw_state(DatasetState(frame, obs, meta, ref_mz), file_preprocess)
            del frame, obs
        obj.file_meta.update(
            name=source.stem,
            source_file=source.name,
            path=str(source.resolve()),
            converted_from_raw=False,
        )
        obj.peak_meta["source_file"] = source.name
        obj.peak_meta["label"] = source.stem
        if metadata_by_file:
            metadata = metadata_by_file.get(source.name, {})
            overlap = set(metadata) & set(obj.peak_meta.columns)
            if overlap:
                raise ValueError(
                    f"sample metadata would overwrite existing columns: {sorted(overlap)}"
                )
            for key, value in metadata.items():
                obj.peak_meta[key] = value
        if _file_signature(source) != signatures[source]:
            raise ValueError(f"MS file changed during processing: {source}")
        objects.append(obj)
        report(0.4 + 0.55 * (i + 1) / len(files), f"Extracted cells {i + 1}/{len(files)}")
    result = merge_objects(cls, objects, 0.0 if feature_strategy == "shared" else feature_merge_ppm)
    result.file_meta.update(
        name=root.name,
        processing={
            "architecture": "sequential_v1",
            "feature_strategy": feature_strategy,
            "feature_merge_ppm": feature_merge_ppm,
            "ppm_tol": ppm_tol,
            "resolution": resolution,
            "resample_points_per_fwhm": resample_points_per_fwhm,
            "ms_peak_snr_threshold": ms_peak_snr_threshold,
            "mz_range": list(mz_range),
        },
    )
    report(1.0, "Processing complete")
    return result


def merge_objects(cls, objects, ppm_tolerance):
    """Union feature masses around running medians; collisions use max intensity."""
    entries = sorted(
        (float(mz), i, j) for i, obj in enumerate(objects) for j, mz in enumerate(obj.data.columns)
    )
    clusters = []
    for mz, i, j in entries:
        if (
            not clusters
            or abs(mz - np.median(clusters[-1][0])) / np.median(clusters[-1][0]) * 1e6
            > ppm_tolerance
        ):
            clusters.append(([mz], [(i, j)]))
        else:
            clusters[-1][0].append(mz)
            clusters[-1][1].append((i, j))
    centers = [float(np.median(masses)) for masses, _ in clusters]
    parts, snr_parts = [], []
    have_snr = all(hasattr(obj, "feature_snr") for obj in objects)
    for i, obj in enumerate(objects):
        values = np.zeros((len(obj.data), len(clusters)), dtype=obj.data.values.dtype)
        snr = np.zeros_like(values)
        for k, (_, members) in enumerate(clusters):
            columns = [j for owner, j in members if owner == i]
            if columns:
                values[:, k] = obj.data.iloc[:, columns].max(axis=1)
                if have_snr:
                    snr[:, k] = obj.feature_snr.iloc[:, columns].max(axis=1)
        parts.append(pd.DataFrame(values, columns=centers))
        snr_parts.append(pd.DataFrame(snr, columns=centers))
    data = pd.concat(parts, ignore_index=True)
    obs = pd.concat([obj.peak_meta for obj in objects], ignore_index=True)
    var = make_feature_metadata(data)
    var["source_file_count"] = [len({i for i, _ in members}) for _, members in clusters]
    var["zero_fraction"] = (data == 0).mean().to_numpy()
    result = object.__new__(cls)
    result._apply_state(
        DatasetState(
            data,
            obs,
            {
                "name": "merged",
                "ref_mz": objects[0].ref_mz,
                "per_file_meta": [obj.file_meta for obj in objects],
            },
            objects[0].ref_mz,
            var,
        )
    )
    if have_snr:
        result.feature_snr = pd.concat(snr_parts, ignore_index=True)
    return result
