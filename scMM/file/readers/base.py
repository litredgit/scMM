"""Lossless per-scan values with the accessors used by scMM algorithms."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Spectrum:
    scan_number: int
    retention_time: float  # seconds, as in OpenMS
    mz: np.ndarray
    intensity: np.ndarray
    ms_level: int = 1
    is_profile: bool = True

    def get_peaks(self):
        return self.mz, self.intensity

    def getRT(self):
        return self.retention_time

    def getMSLevel(self):
        return self.ms_level
