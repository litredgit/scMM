"""Inclusive acquisition selection retaining original experiment frame IDs."""

import numpy as np

from .readers.base import spectrum_iterator


def validate_selection(rt_range=None, frame_range=None):
    for name, bounds in (("RT", rt_range), ("frame", frame_range)):
        if bounds is None:
            continue
        if len(bounds) != 2 or not np.isfinite(bounds).all() or not 0 <= bounds[0] <= bounds[1]:
            raise ValueError(f"{name} requires two finite nonnegative ascending bounds")
        if name == "frame" and any(isinstance(v, bool) or int(v) != v for v in bounds):
            raise ValueError("frame bounds must be integers")


def selected_frames(experiment, *, ms_level=1, rt_range=None, frame_range=None):
    validate_selection(rt_range, frame_range)
    with spectrum_iterator(experiment) as spectra:
        for index, spectrum in enumerate(spectra):
            if spectrum.getMSLevel() != ms_level:
                continue
            if rt_range is not None and not rt_range[0] <= spectrum.getRT() <= rt_range[1]:
                continue
            if frame_range is not None and not frame_range[0] <= index <= frame_range[1]:
                continue
            yield index, spectrum
