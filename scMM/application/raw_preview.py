"""Raw mass-spectrometry summaries for interactive previews."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyopenms as oms

from scMM.file.io import load_single_file, sum_spec
from scMM.file.readers.base import spectrum_iterator
from scMM.file.readers.source import ThermoRawSource

from .processing import ProcessingParameters
from .storage import StorageCatalog


@dataclass(frozen=True)
class CellDetectionPreview:
    """Production detection traces; RT is always in seconds, frame_id is positional."""

    traces: pd.DataFrame
    reference_mz: tuple[float, ...]
    window_ranges: tuple[tuple[int, int], ...]
    cell_count: int


@dataclass(frozen=True)
class RawFileSummary:
    """Compact metadata shown before a processing workflow starts."""

    name: str
    path: Path
    size_bytes: int
    scan_count: int
    scans_by_ms_level: tuple[tuple[int, int], ...]
    rt_min_seconds: float | None
    rt_max_seconds: float | None
    mz_min: float | None
    mz_max: float | None
    instrument: str


class RawFilePreview:
    """A loaded raw file with reusable TIC, EIC, and spectrum calculations."""

    def __init__(
        self,
        path: Path,
        experiment: oms.MSExperiment | ThermoRawSource,
        metadata: dict[str, object],
    ) -> None:
        from .preview_cache import file_identity

        self.path = path
        self.open_identity = file_identity(path)
        self.experiment = experiment
        self.metadata = metadata
        self.summary = _summarize(path, experiment, metadata)

    @property
    def ms_levels(self) -> tuple[int, ...]:
        """Return the MS levels represented in the file."""
        return tuple(level for level, _ in self.summary.scans_by_ms_level)

    def cell_detection(
        self,
        parameters: ProcessingParameters,
        *,
        extraction_method=None,
        reference_mz=None,
        reference_mode=None,
        reference_ppm_tol=None,
        feature_snr_threshold=None,
        noise_window=None,
        feature_block_size=None,
        progress_callback=None,
        targets=None,
    ) -> CellDetectionPreview:
        """Preview production cell windows (RAW sources reopen for each pass).

        Uses full-file MS1 scans and the same alignment and preprocessing as
        load_from_file. This is a full extraction, not a downsampled approximation.
        No full frame-by-feature baseline is retained and no dataset is saved.
        """
        from scMM.file._dataset_loading import _raw_config, align_raw_experiment
        from scMM.file.data import CyESIData

        from .preview_cache import file_identity

        if file_identity(self.path) != self.open_identity:
            raise ValueError("Input changed since opening; reopen the file")
        config = _raw_config(
            parameters.ref_mz,
            np.float64,
            parameters.ppm_tol,
            parameters.resolution,
            parameters.resample_points_per_fwhm,
            parameters.ms_peak_snr_threshold,
            None,
            3,
            (parameters.mz_min, parameters.mz_max),
        )
        if targets is None:
            state = align_raw_experiment(self.experiment, self.metadata, self.path, config)
        else:
            from scMM.file._dataset_loading import DatasetState, _annotate_single_file_frames
            from scMM.file.io import align_frame

            frame, obs = align_frame(self.experiment, targets, ppm=parameters.ppm_tol)
            metadata = dict(self.metadata)
            _annotate_single_file_frames(obs, metadata)
            metadata.update(
                ref_mz=parameters.ref_mz, mz_range=[parameters.mz_min, parameters.mz_max]
            )
            state = DatasetState(frame, obs, metadata, parameters.ref_mz)
        captured = {}

        def capture(event, payload):
            if event != "find_cells":
                return
            signal = payload["signal"]
            references = tuple(float(mz) for mz in payload["reference_mz"])
            traces = pd.DataFrame(
                {
                    "frame_id": np.arange(len(signal)),
                    "rt_seconds": payload["frame_obs"]["rt"].to_numpy(copy=True),
                    "cell_window": np.asarray(payload["cell_mask"]).copy(),
                    "cell_apex": np.zeros(len(signal), dtype=bool),
                }
            )
            traces.loc[payload["cell_idx"], "cell_apex"] = True
            for i, mz in enumerate(references):
                traces[f"reference_{i}"] = signal[mz].to_numpy(copy=True)
            captured.update(
                traces=traces,
                reference_mz=references,
                window_ranges=tuple(payload["window_ranges"]),
                cell_count=len(payload["cell_idx"]),
            )

        self.last_targets = np.asarray(state.data.columns, dtype=float)
        self.last_dataset = CyESIData._from_raw_state(
            state,
            {
                "baseline_filter_size": parameters.baseline_filter_size,
                "cell_snr": parameters.cell_snr,
                "peak_snr": parameters.peak_snr,
                "max_zero_frac": parameters.max_zero_frac,
                "n_jobs": parameters.n_jobs,
                "extraction_method": extraction_method or parameters.extraction_method,
                "reference_mz": reference_mz
                if reference_mz is not None
                else (parameters.reference_mz or None),
                "reference_mode": reference_mode or parameters.reference_mode,
                "reference_ppm_tol": parameters.reference_ppm_tol
                if reference_ppm_tol is None
                else reference_ppm_tol,
                "feature_snr_threshold": parameters.feature_snr_threshold
                if feature_snr_threshold is None
                else feature_snr_threshold,
                "noise_window": parameters.noise_window if noise_window is None else noise_window,
                "feature_block_size": parameters.feature_block_size
                if feature_block_size is None
                else feature_block_size,
                "progress_callback": progress_callback,
                "debug_hook": capture,
                "debug_full_baseline": False,
            },
        )
        if file_identity(self.path) != self.open_identity:
            self.last_dataset = None
            raise ValueError("Input changed during preview; reopen the file")
        self.last_detection = CellDetectionPreview(**captured)
        return self.last_detection

    def single_spectrum(self, scan_index: int) -> tuple[pd.DataFrame, dict]:
        """Read a zero-based scan index; RAW scans stream sequentially to it."""
        if isinstance(scan_index, bool) or not isinstance(scan_index, int):
            raise ValueError("scan_index must be an integer")
        if not 0 <= scan_index < self.experiment.getNrSpectra():
            raise ValueError("scan_index is outside the loaded experiment")
        if isinstance(self.experiment, ThermoRawSource):
            with spectrum_iterator(self.experiment) as scans:
                for index, candidate in enumerate(scans):
                    if index == scan_index:
                        spectrum = candidate
                        break
                else:
                    raise ValueError("scan_index is outside the RAW stream")
        else:
            spectrum = self.experiment[scan_index]
        mz, intensity = spectrum.get_peaks()
        return pd.DataFrame({"mz": mz, "intensity": intensity}), {
            "scan_index": scan_index,
            "native_id": spectrum.getNativeID()
            if hasattr(spectrum, "getNativeID")
            else f"scan={spectrum.scan_number}",
            "rt_seconds": float(spectrum.getRT()),
            "ms_level": int(spectrum.getMSLevel()),
        }

    def extracted_ion_chromatograms(
        self, references, *, ppm_tolerance=5.0, ms_level=1, rt_range=None
    ) -> pd.DataFrame:
        """Compute all EICs in one pass, retaining reference-major output order."""
        references = np.atleast_1d(references).astype(float)
        if references.ndim != 1 or not len(references):
            raise ValueError("at least one reference m/z is required")
        if not np.isfinite(references).all() or (references <= 0).any():
            raise ValueError("target_mz must be a positive finite number")
        if not np.isfinite(ppm_tolerance) or ppm_tolerance <= 0:
            raise ValueError("ppm_tolerance must be a positive finite number")
        _validate_ms_level(ms_level)
        references = np.unique(references)
        delta = references * ppm_tolerance * 1e-6
        lower, upper = references - delta, references + delta
        rows = [[] for _ in references]
        with spectrum_iterator(_selected_spectra(self.experiment, ms_level, rt_range)) as scans:
            for scan_index, spectrum in scans:
                mz, intensity = spectrum.get_peaks()
                mz = np.asarray(mz, dtype=np.float64)
                intensity = np.asarray(intensity, dtype=np.float64)
                valid = np.isfinite(mz) & np.isfinite(intensity)
                for i in range(len(references)):
                    value = intensity[valid & (mz >= lower[i]) & (mz <= upper[i])].sum()
                    rows[i].append((scan_index, float(spectrum.getRT()), float(value)))
        frames = [
            pd.DataFrame(values, columns=["scan_index", "rt_seconds", "intensity"]).assign(
                reference_mz=reference
            )
            for reference, values in zip(references, rows, strict=True)
        ]
        return pd.concat(frames, ignore_index=True)

    def total_ion_chromatogram(
        self,
        *,
        ms_level: int = 1,
        rt_range: tuple[float, float] | None = None,
    ) -> pd.DataFrame:
        """Return total ion intensity for each selected scan."""
        _validate_ms_level(ms_level)
        rows = []
        with spectrum_iterator(_selected_spectra(self.experiment, ms_level, rt_range)) as scans:
            for scan_index, spectrum in scans:
                _, intensity = spectrum.get_peaks()
                rows.append(
                    {
                        "scan_index": scan_index,
                        "rt_seconds": float(spectrum.getRT()),
                        "intensity": float(np.nansum(intensity)),
                    }
                )
        return pd.DataFrame(rows, columns=["scan_index", "rt_seconds", "intensity"])

    def extracted_ion_chromatogram(
        self,
        target_mz: float,
        *,
        ppm_tolerance: float = 5.0,
        ms_level: int = 1,
        rt_range: tuple[float, float] | None = None,
    ) -> pd.DataFrame:
        """Sum signal inside a target-centered ppm window for each scan."""
        if not np.isfinite(target_mz) or target_mz <= 0:
            raise ValueError("target_mz must be a positive finite number")
        if not np.isfinite(ppm_tolerance) or ppm_tolerance <= 0:
            raise ValueError("ppm_tolerance must be a positive finite number")
        _validate_ms_level(ms_level)
        delta = target_mz * ppm_tolerance * 1e-6
        lower, upper = target_mz - delta, target_mz + delta
        rows = []
        with spectrum_iterator(_selected_spectra(self.experiment, ms_level, rt_range)) as scans:
            for scan_index, spectrum in scans:
                mz, intensity = spectrum.get_peaks()
                mz = np.asarray(mz, dtype=np.float64)
                intensity = np.asarray(intensity, dtype=np.float64)
                valid = np.isfinite(mz) & np.isfinite(intensity)
                selected_intensity = intensity[valid & (mz >= lower) & (mz <= upper)]
                rows.append(
                    {
                        "scan_index": scan_index,
                        "rt_seconds": float(spectrum.getRT()),
                        "intensity": float(selected_intensity.sum()),
                    }
                )
        return pd.DataFrame(rows, columns=["scan_index", "rt_seconds", "intensity"])

    def summed_spectrum(
        self,
        *,
        mz_range: tuple[float, float],
        resolution_200: float = 35_000.0,
        points_per_fwhm: float = 3.0,
        ms_level: int = 1,
        rt_range: tuple[float, float] | None = None,
        normalize: bool = False,
    ) -> pd.DataFrame:
        """Return a summed or average profile spectrum over selected scans."""
        _validate_ms_level(ms_level)
        with spectrum_iterator(_selected_spectra(self.experiment, ms_level, rt_range)) as scans:
            spectrum = sum_spec(
                (spectrum for _, spectrum in scans),
                mz_range=mz_range,
                resolution_200=resolution_200,
                points_per_fwhm=points_per_fwhm,
                ms_level=ms_level,
                normalize=normalize,
            )
        mz, intensity = spectrum.get_peaks()
        return pd.DataFrame(
            {
                "mz": np.asarray(mz, dtype=np.float64),
                "intensity": np.asarray(intensity, dtype=np.float64),
            }
        )

    def binned_spectrum(
        self,
        *,
        mz_range: tuple[float, float],
        bins: int = 20_000,
        ms_level: int = 1,
        rt_range: tuple[float, float] | None = None,
        normalize: bool = False,
    ) -> pd.DataFrame:
        """Return a fast fixed-bin preview spectrum without high-resolution interpolation."""
        _validate_ms_level(ms_level)
        mz_min, mz_max = map(float, mz_range)
        if not np.isfinite(mz_min) or not np.isfinite(mz_max) or mz_max <= mz_min:
            raise ValueError("mz_range must contain finite values in ascending order")
        if isinstance(bins, bool) or not isinstance(bins, int) or not 2 <= bins <= 1_000_000:
            raise ValueError("bins must be an integer between 2 and 1000000")
        accumulated = np.zeros(bins, dtype=np.float64)
        selected_count = 0
        scale = bins / (mz_max - mz_min)
        with spectrum_iterator(_selected_spectra(self.experiment, ms_level, rt_range)) as scans:
            for _, spectrum in scans:
                selected_count += 1
                mz, intensity = spectrum.get_peaks()
                mz = np.asarray(mz, dtype=np.float64)
                intensity = np.asarray(intensity, dtype=np.float64)
                valid = np.isfinite(mz) & np.isfinite(intensity) & (mz >= mz_min) & (mz <= mz_max)
                selected_mz = mz[valid]
                if selected_mz.size == 0:
                    continue
                indices = np.floor((selected_mz - mz_min) * scale).astype(np.int64)
                np.minimum(indices, bins - 1, out=indices)
                np.add.at(accumulated, indices, intensity[valid])
        if selected_count == 0:
            raise ValueError("No spectra found.")
        if normalize:
            accumulated /= selected_count
        width = (mz_max - mz_min) / bins
        centers = mz_min + (np.arange(bins, dtype=np.float64) + 0.5) * width
        return pd.DataFrame({"mz": centers, "intensity": accumulated})


class RawPreviewService:
    """Open raw files only after validating them against a storage catalog."""

    def __init__(self, storage: StorageCatalog) -> None:
        self.storage = storage

    def open(self, root_label: str, selected_path: str | Path) -> RawFilePreview:
        """Load one validated raw file for an interactive session."""
        path = self.storage.resolve_raw_file(root_label, selected_path)
        experiment, metadata = load_single_file(path)
        return RawFilePreview(path, experiment, metadata)


def _summarize(
    path: Path,
    experiment: oms.MSExperiment | ThermoRawSource,
    metadata: dict[str, object],
) -> RawFileSummary:
    levels: Counter[int] = Counter()
    retention_times: list[float] = []
    mz_min: float | None = None
    mz_max: float | None = None
    with spectrum_iterator(experiment) as scans:
        for spectrum in scans:
            levels[int(spectrum.getMSLevel())] += 1
            retention_times.append(float(spectrum.getRT()))
            mz, _ = spectrum.get_peaks()
            finite_mz = np.asarray(mz, dtype=np.float64)
            finite_mz = finite_mz[np.isfinite(finite_mz)]
            if finite_mz.size:
                local_min, local_max = float(finite_mz.min()), float(finite_mz.max())
                mz_min = local_min if mz_min is None else min(mz_min, local_min)
                mz_max = local_max if mz_max is None else max(mz_max, local_max)
    return RawFileSummary(
        name=str(metadata.get("name", path.stem)),
        path=path,
        size_bytes=path.stat().st_size,
        scan_count=int(experiment.getNrSpectra()),
        scans_by_ms_level=tuple(sorted(levels.items())),
        rt_min_seconds=min(retention_times) if retention_times else None,
        rt_max_seconds=max(retention_times) if retention_times else None,
        mz_min=mz_min,
        mz_max=mz_max,
        instrument=str(metadata.get("instrument", "")),
    )


def _validate_ms_level(ms_level: int) -> None:
    if ms_level < 1:
        raise ValueError("ms_level must be at least 1")


def _selected_spectra(
    experiment: oms.MSExperiment | ThermoRawSource,
    ms_level: int,
    rt_range: tuple[float, float] | None,
):
    if rt_range is not None:
        rt_min, rt_max = map(float, rt_range)
        if not np.isfinite(rt_min) or not np.isfinite(rt_max) or rt_max < rt_min:
            raise ValueError("rt_range must contain finite values in ascending order")
    else:
        rt_min = rt_max = None
    with spectrum_iterator(experiment) as scans:
        for scan_index, spectrum in enumerate(scans):
            rt = float(spectrum.getRT())
            if spectrum.getMSLevel() != ms_level:
                continue
            if rt_min is not None and not (rt_min <= rt <= rt_max):
                continue
            yield scan_index, spectrum
