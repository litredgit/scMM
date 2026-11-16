"""Internal CyESI dataset container assembled from focused capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import numpy as np

from ._dataset_interop import DatasetInteropMixin
from ._dataset_loading import (
    DatasetState,
    load_processed_dataset,
    load_raw_directory,
    load_raw_file,
    make_feature_metadata,
)
from ._dataset_processing import DatasetProcessingMixin


class CyESIData(DatasetProcessingMixin, DatasetInteropMixin):
    """Processed CyESI dataset and its observation/feature metadata.

    Construction lives here, while processing and interoperability methods are
    grouped into private mixins. Interfaces follow the server workbench needs.
    """

    @classmethod
    def load_from_processed(cls, result_dir: str | Path) -> Self:
        """Read the current internal worker artifact."""
        obj = object.__new__(cls)
        obj._apply_state(load_processed_dataset(result_dir))
        return obj

    @classmethod
    def load_from_file(
        cls,
        file_path: str | Path,
        ref_mz: float,
        dtype=np.float64,
        ppm_tol: int = 10,
        resolution: float = 35000,
        resample_points_per_fwhm: float = 5.0,
        ms_peak_snr_threshold: float = 10.0,
        prominence_ratio: float | None = None,
        distance: int = 3,
        mz_range=(100.0, 1000.0),
        raw_timezone=None,
        rt_range=None,
        frame_range=None,
        **preprocess_kwds,
    ) -> Self:
        """Load, align, and preprocess one mzML/mzXML or profile Thermo RAW file."""
        state = load_raw_file(
            file_path,
            ref_mz,
            dtype=dtype,
            ppm_tol=ppm_tol,
            resolution=resolution,
            resample_points_per_fwhm=resample_points_per_fwhm,
            ms_peak_snr_threshold=ms_peak_snr_threshold,
            prominence_ratio=prominence_ratio,
            distance=distance,
            mz_range=mz_range,
            raw_timezone=raw_timezone,
            rt_range=rt_range,
            frame_range=frame_range,
        )
        return cls._from_raw_state(state, preprocess_kwds)

    @classmethod
    def load_from_filelist(
        cls,
        dir_path: str | Path,
        ref_mz: float,
        dtype=np.float64,
        ppm_tol: int = 10,
        resolution: float = 35000,
        resample_points_per_fwhm: float = 5.0,
        ms_peak_snr_threshold: float = 10.0,
        prominence_ratio: float | None = None,
        n_jobs: int | None = None,
        distance: int = 3,
        processing_strategy: str = "legacy",
        feature_merge_ppm: float = 10.0,
        mz_range=(100.0, 1000.0),
        raw_timezone=None,
        rt_range=None,
        frame_range=None,
        **preprocess_kwds,
    ) -> Self:
        """Combine direct XML/RAW files; default RAW workers=1, XML workers=all."""
        if processing_strategy != "legacy":
            return cls.load_from_directory(
                dir_path,
                ref_mz,
                feature_strategy=processing_strategy,
                feature_merge_ppm=feature_merge_ppm,
                rt_range=rt_range,
                frame_range=frame_range,
                mz_range=mz_range,
                raw_timezone=raw_timezone,
                dtype=dtype,
                ppm_tol=ppm_tol,
                resolution=resolution,
                resample_points_per_fwhm=resample_points_per_fwhm,
                ms_peak_snr_threshold=ms_peak_snr_threshold,
                prominence_ratio=prominence_ratio,
                distance=distance,
                n_jobs=n_jobs,
                **preprocess_kwds,
            )
        state = load_raw_directory(
            dir_path,
            ref_mz,
            dtype=dtype,
            ppm_tol=ppm_tol,
            resolution=resolution,
            resample_points_per_fwhm=resample_points_per_fwhm,
            ms_peak_snr_threshold=ms_peak_snr_threshold,
            prominence_ratio=prominence_ratio,
            n_jobs=n_jobs,
            distance=distance,
            mz_range=mz_range,
            raw_timezone=raw_timezone,
            rt_range=rt_range,
            frame_range=frame_range,
        )
        return cls._from_raw_state(state, preprocess_kwds)

    @classmethod
    def load_from_directory(cls, dir_path, ref_mz, *, feature_strategy="shared", **kwargs):
        """Opt-in sequential processing with shared or independently picked features."""
        from ._sequential import load_directory

        return load_directory(cls, dir_path, ref_mz, feature_strategy=feature_strategy, **kwargs)

    @classmethod
    def _from_raw_state(cls, state: DatasetState, preprocess_kwds: dict) -> Self:
        obj = object.__new__(cls)
        obj._apply_state(state)
        obj.file_meta["intensity_state"] = "raw"
        obj.preprocess(**preprocess_kwds)
        obj.feature_meta = make_feature_metadata(obj.data)
        return obj

    def _apply_state(self, state: DatasetState) -> None:
        self.data = state.data
        self.peak_meta = state.peak_meta
        self.file_meta = state.file_meta
        self.ref_mz = state.ref_mz
        if state.feature_meta is not None:
            self.feature_meta = state.feature_meta
        if state.feature_snr is not None:
            self.feature_snr = state.feature_snr
