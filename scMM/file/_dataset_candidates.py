"""Prepare complete dataset transformations before replacing live attributes."""

from copy import deepcopy

import numpy as np
import pandas as pd

from ..util.lifecycle import invalidate_derived

_KEEP = object()


def validate_axes(
    data, peak_meta, feature_meta, feature_snr=None, *, finite=False, aligned_observations=False
):
    if not all(isinstance(frame, pd.DataFrame) for frame in (data, peak_meta, feature_meta)):
        raise ValueError("dataset data and metadata must be DataFrames")
    if len(peak_meta) != len(data):
        raise ValueError("peak_meta row count must match data row count")
    if aligned_observations and not peak_meta.index.equals(data.index):
        raise ValueError("peak_meta index must match data index in order")
    if len(feature_meta) != data.shape[1]:
        raise ValueError("feature_meta row count must match data column count")
    if not feature_meta.index.equals(data.columns):
        raise ValueError("feature_meta index must match data columns in order")
    if feature_snr is not None and (
        not isinstance(feature_snr, pd.DataFrame)
        or feature_snr.shape != data.shape
        or not feature_snr.index.equals(data.index)
        or not feature_snr.columns.equals(data.columns)
    ):
        raise ValueError("feature_snr axes must match data axes")
    if finite and data.size and not np.isfinite(data.to_numpy()).all():
        raise ValueError("transformation must produce finite matrix values")


def prepare_candidate(
    dataset,
    *,
    data,
    peak_meta=None,
    feature_meta=None,
    file_meta=None,
    feature_snr=_KEEP,
    invalidate=True,
    drop_template=False,
    ref_mz=_KEEP,
    deisotope_result=_KEEP,
    finite=False,
):
    """Return owned metadata/artifact candidates without mutating ``dataset``."""
    attributes = dict(dataset.__dict__)
    observations = (dataset.peak_meta if peak_meta is None else peak_meta).copy()
    if feature_meta is None and not hasattr(dataset, "feature_meta"):
        from ._dataset_loading import make_feature_metadata

        variables = make_feature_metadata(data)
    else:
        variables = (dataset.feature_meta if feature_meta is None else feature_meta).copy()
    metadata = deepcopy(dataset.file_meta if file_meta is None else file_meta)
    if not isinstance(metadata, dict):
        raise ValueError("file_meta must be a mapping")
    if "length" in metadata:
        metadata["length"] = len(data)
    snr = getattr(dataset, "feature_snr", None) if feature_snr is _KEEP else feature_snr
    if snr is not None:
        snr = snr.copy()
    template = getattr(dataset, "_anndata_template", None)
    if drop_template:
        attributes.pop("_anndata_template", None)
    elif invalidate and template is not None:
        template = template.copy()
        derived = template.uns.get("scmm_workbench", {}).get("derived_obs", [])
        invalidate_derived(template)
        observations = observations.drop(columns=derived, errors="ignore")
        attributes["_anndata_template"] = template
    if invalidate:
        attributes.pop("deisotope_result", None)
    validate_axes(
        data,
        observations,
        variables,
        snr,
        finite=finite,
        aligned_observations=template is not None and not drop_template,
    )
    attributes.update(data=data, peak_meta=observations, feature_meta=variables, file_meta=metadata)
    if snr is None:
        attributes.pop("feature_snr", None)
    else:
        attributes["feature_snr"] = snr
    if ref_mz is not _KEEP:
        attributes["ref_mz"] = ref_mz
    if deisotope_result is not _KEEP:
        attributes["deisotope_result"] = deisotope_result
    return attributes


def commit_candidate(dataset, attributes):
    """Publish already constructed attributes in one instance-state replacement."""
    dataset.__dict__ = attributes
