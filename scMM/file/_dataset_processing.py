"""Mutable processing capabilities composed into :class:`CyESIData`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal, Self

import numpy as np
import pandas as pd
from scipy.ndimage import median_filter
from sklearn.ensemble import IsolationForest
from sklearn.impute import KNNImputer, SimpleImputer

from ..util.intensity import dataset_intensity_state, merged_intensity_state, transformed_state
from ..util.normalize import normalize
from ..util.peak import find_cell_peaks
from ._dataset_candidates import commit_candidate, prepare_candidate
from ._dataset_loading import DatasetState, make_feature_metadata
from ._deisotope import DeisotopeParams, analyze_isotopes, zero_is_missing

DebugHook = Callable[[str, dict[str, Any]], None]
logger = logging.getLogger(__name__)


class DatasetProcessingMixin:
    """Provide preprocessing, transformation, alignment, and deisotoping."""

    def _invalidate_analyses(self):
        candidate = prepare_candidate(self, data=self.data)
        commit_candidate(self, candidate)

    def preprocess(
        self,
        baseline_filter=median_filter,
        baseline_filter_size: int = 50,
        cell_snr: float = 5.0,
        peak_snr: float = 3.0,
        max_zero_frac: float = 0.9,
        debug_hook: DebugHook | None = None,
        feature_block_size: int | None = 256,
        extraction_method: str = "legacy",
        reference_mz=None,
        reference_mode: str = "union",
        reference_ppm_tol: float = 10.0,
        feature_snr_threshold: float = 3.0,
        noise_window: int = 51,
        debug_full_baseline: bool = True,
        progress_callback=None,
        cell_min_signal: float = 1e5,
        **kwargs,
    ) -> Self:
        input_state = dataset_intensity_state(self)
        signal = self.data.copy()
        frame_metadata = self.peak_meta.copy()
        if self.ref_mz is None or not np.isfinite(self.ref_mz) or self.ref_mz <= 0:
            raise ValueError("A positive finite ref_mz is required for preprocessing")
        if extraction_method not in {"legacy", "snr_v1"}:
            raise ValueError("extraction_method must be legacy or snr_v1")
        if extraction_method == "legacy" and reference_mz is not None:
            raise ValueError("reference_mz requires extraction_method='snr_v1'")
        if extraction_method == "snr_v1":
            from ..util._cell_snr import find_cell_peaks_snr

            result = find_cell_peaks_snr(
                signal,
                self.ref_mz if reference_mz is None else reference_mz,
                reference_mode=reference_mode,
                reference_ppm_tol=reference_ppm_tol,
                baseline_filter=baseline_filter,
                baseline_window=baseline_filter_size,
                cell_signal_threshold=cell_snr,
                cell_min_signal=cell_min_signal,
                feature_snr_threshold=feature_snr_threshold,
                noise_window=noise_window,
                max_zero_fraction=max_zero_frac,
                feature_block_size=feature_block_size or self.data.shape[1],
                return_full_baseline=debug_hook is not None and debug_full_baseline,
                progress_callback=progress_callback,
                **kwargs,
            )
        else:
            result = find_cell_peaks(
                signal,
                self.ref_mz,
                baseline_filter=baseline_filter,
                baseline_filter_size=baseline_filter_size,
                cell_snr=cell_snr,
                cell_min_signal=cell_min_signal,
                peak_snr=peak_snr,
                max_zero_frac=max_zero_frac,
                feature_block_size=feature_block_size,
                return_full_baseline=debug_hook is not None and debug_full_baseline,
                progress_callback=progress_callback,
                **kwargs,
            )
        if debug_hook is not None:
            debug_metadata = frame_metadata.copy()
            for column in debug_metadata.select_dtypes(include="object"):
                debug_metadata[column] = debug_metadata[column].map(deepcopy)
            debug_hook(
                "find_cells",
                deepcopy(
                    {
                        "signal": signal,
                        "baseline": result["baseline"],
                        "cell_mask": result["cell_mask"],
                        "cell_idx": result["peak_frames"],
                        "frame_obs": debug_metadata,
                        "reference_mz": result.get(
                            "reference_mz_matched", [result.get("ref_mz_matched")]
                        ),
                        "window_ranges": result["window_ranges"],
                        "reference_baseline": result.get("reference_baseline"),
                        "cell_snr": cell_snr,
                        "cell_min_signal": cell_min_signal,
                    }
                ),
            )
        data = result["cell_df"]
        snr = None
        metadata = deepcopy(self.file_meta)
        frames = result["peak_frames"]
        observations = pd.DataFrame(
            frame_metadata.iloc[frames, :],
            index=frame_metadata.index[frames],
        )
        if "rt" in frame_metadata and result["window_ranges"]:
            windows = np.asarray(result["window_ranges"], dtype=int)
            scans = frame_metadata.index.to_numpy()
            times = frame_metadata["rt"].to_numpy()
            observations["cell_apex_scan"] = scans[frames]
            observations["cell_start_scan"] = scans[windows[:, 0]]
            observations["cell_stop_scan"] = scans[windows[:, 1]]
            observations["cell_start_rt"] = times[windows[:, 0]]
            observations["cell_stop_rt"] = times[windows[:, 1]]
            observations["cell_scan_count"] = windows[:, 1] - windows[:, 0] + 1
        if extraction_method == "snr_v1":
            for i, mz in enumerate(result["reference_mz_matched"]):
                observations[f"reference_intensity_{mz:.8g}"] = result["reference_signal"][
                    frames, i
                ]
                observations[f"reference_ratio_{mz:.8g}"] = result["reference_ratio"][frames, i]
            snr = pd.DataFrame(result["feature_snr"], index=data.index, columns=data.columns)
        metadata["processing"] = {
            "extraction_method": extraction_method,
            "baseline_filter_size": baseline_filter_size,
            "cell_snr": cell_snr,
            "cell_min_signal": cell_min_signal,
            "peak_snr": peak_snr,
            "max_zero_frac": max_zero_frac,
        }
        if extraction_method == "snr_v1":
            metadata["processing"].update(
                reference_mz=np.atleast_1d(
                    self.ref_mz if reference_mz is None else reference_mz
                ).tolist(),
                reference_mode=reference_mode,
                reference_ppm_tol=reference_ppm_tol,
                feature_snr_threshold=feature_snr_threshold,
                noise_window=noise_window,
            )
        metadata["length"] = data.shape[0]
        metadata["intensity_state"] = "transformed" if input_state == "normalized" else input_state
        variables = (
            self.feature_meta.reindex(data.columns)
            if hasattr(self, "feature_meta")
            else make_feature_metadata(data)
        )
        candidate = prepare_candidate(
            self,
            data=data,
            peak_meta=observations,
            feature_meta=variables,
            file_meta=metadata,
            feature_snr=snr,
            drop_template=True,
            finite=True,
        )
        commit_candidate(self, candidate)
        return self

    def impute(self, method: str = "knn", missing_values=0, **kwargs) -> Self:
        logger.info("Imputing %s with method %s", self.get_name(), method)
        if kwargs.get("keep_empty_features", True) is not True:
            raise ValueError("keep_empty_features must be True to preserve the feature axis")
        kwargs["keep_empty_features"] = True
        if method == "knn":
            imputer = KNNImputer(missing_values=missing_values, **kwargs)
        else:
            imputer = SimpleImputer(missing_values=missing_values, strategy=method, **kwargs)
        values = imputer.fit_transform(self.data.copy())
        if values.shape != self.data.shape or not np.isfinite(values).all():
            raise ValueError("imputation must preserve matrix shape and produce finite values")
        candidate = pd.DataFrame(
            values,
            index=self.data.index,
            columns=self.data.columns,
        )
        attributes = prepare_candidate(
            self,
            data=candidate,
            file_meta={**self.file_meta, "intensity_state": "transformed"},
            finite=True,
        )
        commit_candidate(self, attributes)
        return self

    def remove_outlier(self, **kwargs) -> Self:
        random_state = kwargs.get("random_state")
        if isinstance(random_state, np.random.RandomState):
            algorithm, keys, position, has_gauss, cached = random_state.get_state()
            seed_record = {
                "kind": "numpy.RandomState",
                "algorithm": algorithm,
                "keys": keys.tolist(),
                "position": position,
                "has_gauss": has_gauss,
                "cached_gaussian": cached,
            }
        else:
            seed_record = int(random_state) if isinstance(random_state, (int, np.integer)) else None
        inliers = IsolationForest(**kwargs).fit_predict(self.data.copy()) == 1
        metadata = deepcopy(self.file_meta)
        metadata["outlier"] = {
            "method": "IsolationForest",
            "random_state": seed_record,
            "input_cells": len(self.data),
            "retained_cells": int(inliers.sum()),
        }
        snr = self.feature_snr.iloc[inliers, :] if hasattr(self, "feature_snr") else None
        candidate = prepare_candidate(
            self,
            data=self.data.iloc[inliers, :].copy(),
            peak_meta=self.peak_meta.iloc[inliers, :],
            file_meta=metadata,
            feature_snr=snr,
            finite=True,
        )
        commit_candidate(self, candidate)
        return self

    def normalize(self, method: str = "total", **norm_kwargs) -> Self:
        logger.info("Normalizing %s with method %s", self.get_name(), method)
        state = transformed_state(dataset_intensity_state(self), "normalize", {"method": method})
        candidate = pd.DataFrame(
            normalize(self.data.to_numpy(copy=True), method, norm_kwargs),
            index=self.data.index,
            columns=self.data.columns,
        )
        attributes = prepare_candidate(
            self,
            data=candidate,
            file_meta={**self.file_meta, "intensity_state": state},
            finite=True,
        )
        commit_candidate(self, attributes)
        return self

    def alignwith(
        self,
        other: Self,
        ppm_tol: float = 5.0,
        mz_merge_options: Literal["union", "ref"] = "union",
    ) -> Self:
        """Append another dataset after aligning its features by m/z."""
        state = merge_dataset_states(self, other, ppm_tol, mz_merge_options)
        invalidated = [
            attribute
            for attribute in ("feature_snr", "_anndata_template")
            if hasattr(self, attribute) or hasattr(other, attribute)
        ]
        if invalidated:
            state.file_meta["invalidated_by_alignment"] = invalidated
        candidate = prepare_candidate(
            self,
            data=state.data,
            peak_meta=state.peak_meta,
            feature_meta=state.feature_meta,
            file_meta=state.file_meta,
            feature_snr=None,
            drop_template=True,
            ref_mz=state.ref_mz,
            finite=True,
        )
        commit_candidate(self, candidate)
        return self

    def deisotope(
        self,
        isotope_diff: float = 1.003355,
        ppm_tol: float = 1.0,
        max_isotope_order: int = 3,
        r_square_threshold: float = 0.95,
        carbon13_abundance: float = 0.0109,
        intensity_threshold: float = 0.0,
        safety_factor: float = 1.0,
        missing_func: Callable[[np.ndarray], np.ndarray] = zero_is_missing,
        merge_mode: str = "keep_parent",
        remove: bool = True,
        inplace: bool = True,
    ):
        """Detect isotope pairs and optionally apply the processed feature set."""
        params = DeisotopeParams(
            isotope_diff=isotope_diff,
            ppm_tol=ppm_tol,
            max_isotope_order=max_isotope_order,
            r_square_threshold=r_square_threshold,
            carbon13_abundance=carbon13_abundance,
            intensity_threshold=intensity_threshold,
            safety_factor=safety_factor,
            merge_mode=merge_mode,
            remove=remove,
        )
        result = analyze_isotopes(
            self.data.copy(),
            getattr(self, "feature_meta", None).copy() if hasattr(self, "feature_meta") else None,
            params,
            missing_func,
        )
        if not inplace:
            return result
        self._apply_deisotope_result(result, merge_mode)
        return self

    def _apply_deisotope_result(self, result: dict, merge_mode: str) -> None:
        data = result["processed_data"]
        changed = merge_mode == "sum" or not data.columns.equals(self.data.columns)
        snr = None
        metadata = deepcopy(getattr(self, "file_meta", None) or {})
        if hasattr(self, "feature_snr"):
            if merge_mode == "sum":
                metadata["feature_snr_invalidated"] = "isotope intensity summation"
            else:
                snr = self.feature_snr.loc[:, data.columns]
        if merge_mode == "sum":
            metadata["intensity_state"] = "transformed"
        metadata["deisotope"] = {
            "params": result["params"],
            "n_candidate_pairs": len(result["candidate_table"]),
            "n_final_isotope_pairs": len(result["final_table"]),
            "n_removed_features": len(result["isotope_features"]),
            "merge_mode": merge_mode,
        }
        candidate = prepare_candidate(
            self,
            data=data,
            feature_meta=result["feature_meta"],
            file_meta=metadata,
            feature_snr=snr,
            invalidate=changed,
            deisotope_result=result,
        )
        commit_candidate(self, candidate)


def merge_dataset_states(left, right, ppm_tol: float, merge_mode: str) -> DatasetState:
    """Return merged frames and provenance without mutating either dataset."""
    _validate_dataset_merge(left, right, ppm_tol, merge_mode)
    rename, matched_right = _match_feature_columns(left.data.columns, right.data.columns, ppm_tol)
    right_data = _align_right_data(right.data, left.data.columns, rename, merge_mode)
    merged_data, unmatched_columns = _merge_data_frames(
        left.data,
        right_data,
        right.data.columns,
        matched_right,
        merge_mode,
    )
    feature_meta = _merge_feature_metadata(
        left,
        right,
        merged_data.columns,
        unmatched_columns,
        merge_mode,
    )
    return DatasetState(
        data=merged_data,
        peak_meta=pd.concat(
            [left.peak_meta, right.peak_meta],
            axis=0,
            ignore_index=True,
            sort=False,
        ),
        feature_meta=feature_meta,
        file_meta={
            "name": f"{left.get_name()}+{right.get_name()}",
            "ref_mz": left.ref_mz,
            "per_file_meta": [*_source_metadata(left), *_source_metadata(right)],
            "intensity_state": merged_intensity_state(left, right),
        },
        ref_mz=left.ref_mz,
    )


def _validate_dataset_merge(left, right, ppm_tol: float, merge_mode: str) -> None:
    if merge_mode not in {"union", "ref"}:
        raise ValueError("mz_merge_options must be either 'union' or 'ref'")
    if ppm_tol < 0:
        raise ValueError("ppm_tol must be non-negative")
    if left.data.columns.has_duplicates or right.data.columns.has_duplicates:
        raise ValueError("Feature columns must be unique before alignment")


def _match_feature_columns(left_columns, right_columns, ppm_tol: float):
    left_mz = left_columns.to_numpy(dtype=float)
    right_mz = right_columns.to_numpy(dtype=float)
    right_order = np.argsort(right_mz)
    right_sorted = right_mz[right_order]
    matched_right: set[int] = set()
    rename: dict[object, object] = {}
    right_start = 0
    for left_index in np.argsort(left_mz):
        target = left_mz[left_index]
        lower, upper = target * (1 - ppm_tol * 1e-6), target * (1 + ppm_tol * 1e-6)
        while right_start < len(right_sorted) and right_sorted[right_start] < lower:
            right_start += 1
        stop = int(np.searchsorted(right_sorted, upper, side="right"))
        candidates = [
            int(right_order[position])
            for position in range(right_start, stop)
            if int(right_order[position]) not in matched_right
        ]
        if candidates:
            match = min(candidates, key=lambda index: abs(right_mz[index] - target))
            matched_right.add(match)
            rename[right_columns[match]] = left_columns[left_index]
    return rename, matched_right


def _align_right_data(right, left_columns, rename: dict, merge_mode: str) -> pd.DataFrame:
    renamed = right.copy().rename(columns=rename)
    if merge_mode == "union":
        return renamed
    aligned = pd.DataFrame(0.0, index=right.index, columns=left_columns)
    for column in rename.values():
        aligned[column] = renamed[column].to_numpy()
    return aligned


def _merge_data_frames(left, right, original_right_columns, matched_right, merge_mode: str):
    merged = pd.concat([left.copy(), right], axis=0, ignore_index=True, sort=False).fillna(0)
    unmatched = [
        original_right_columns[index]
        for index in range(len(original_right_columns))
        if index not in matched_right
    ]
    if merge_mode == "union":
        merged = merged.loc[:, [*left.columns, *unmatched]]
    return merged, unmatched


def _merge_feature_metadata(left, right, columns, unmatched, merge_mode: str) -> pd.DataFrame:
    metadata = left.feature_meta.reindex(left.data.columns).copy()
    if merge_mode == "union":
        metadata = pd.concat([metadata, right.feature_meta.reindex(unmatched).copy()], axis=0)
    metadata = metadata.reindex(columns)
    metadata.index.name = "feature_id"
    return metadata


def _source_metadata(dataset) -> list[dict]:
    return dataset.file_meta.get("per_file_meta", [dataset.file_meta])
