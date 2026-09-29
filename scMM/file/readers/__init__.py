"""Spectrum readers; vendor dependencies are optional and loaded on demand."""

from .base import Spectrum
from .thermo_raw import ThermoRawError, ThermoRawReader

__all__ = ["Spectrum", "ThermoRawError", "ThermoRawReader"]
