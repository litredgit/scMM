"""Element-based ion forms with explicit signed charge and oligomer count."""

import re
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from scMM.util._adducts import (
    FORMULA_ADDUCTS,
    fine_isotope_ratios,
    formula_mass_shift,
    resolve_isotope_ratios,
)

CARBON13_SHIFT = 1.00335483507


@dataclass(frozen=True)
class IonSpec:
    id: str
    charge: int
    add: str = ""
    remove: str = ""
    oligomer: int = 1
    fragment_form: bool = False

    def __post_init__(self):
        if (
            not self.id
            or type(self.charge) is not int
            or not self.charge
            or type(self.oligomer) is not int
            or self.oligomer < 1
        ):
            raise ValueError("invalid ion species")
        from pyopenms import EmpiricalFormula

        for formula in (self.add, self.remove):
            try:
                parsed = EmpiricalFormula(formula)
                if parsed.getCharge() or any(
                    v < 0 for v in parsed.getElementalComposition().values()
                ):
                    raise ValueError("ion offsets must be neutral nonnegative formulas")
            except RuntimeError as exc:
                raise ValueError("invalid ion offset formula") from exc

    @property
    def polarity(self):
        return "pos" if self.charge > 0 else "neg"

    @cached_property
    def shift(self):
        return formula_mass_shift(self.add, self.remove, self.charge)

    def mz(self, neutral_mass, *, isotope_shift=0.0):
        if not np.isfinite(neutral_mass) or neutral_mass <= 0:
            raise ValueError("neutral mass must be finite and positive")
        result = (self.oligomer * neutral_mass + self.shift + isotope_shift) / abs(self.charge)
        if result <= 0 or not np.isfinite(result):
            raise ValueError("ion m/z must be finite and positive")
        return float(result)

    def neutral_mass(self, mz, *, isotope_shift=0.0):
        if not np.isfinite(mz) or mz <= 0:
            raise ValueError("m/z must be finite and positive")
        return float((abs(self.charge) * mz - self.shift - isotope_shift) / self.oligomer)

    def neutral_interval(self, mz, ppm):
        if not np.isfinite(ppm) or not 0 <= ppm < 1e6:
            raise ValueError("invalid mass tolerance")
        # The tolerance denominator is predicted m/z, not the observed mass difference.
        return (self.neutral_mass(mz / (1 + ppm * 1e-6)), self.neutral_mass(mz / (1 - ppm * 1e-6)))


def _formula_species(name, *, fragment_form=False):
    form = FORMULA_ADDUCTS[name]
    return IonSpec(name, form["charge"], form["add"], form["remove"], fragment_form=fragment_form)


ION_SPECS = {
    spec.id: spec
    for spec in (
        _formula_species("[M+H]+"),
        _formula_species("[M+Na]+"),
        _formula_species("[M+K]+"),
        _formula_species("[M+NH4]+"),
        _formula_species("[M+H-H2O]+", fragment_form=True),
        IonSpec("[M+2H]2+", 2, "H2"),
        IonSpec("[M+H+Na]2+", 2, "HNa"),
        IonSpec("[2M+H]+", 1, "H", oligomer=2),
        IonSpec("[2M+Na]+", 1, "Na", oligomer=2),
        _formula_species("[M-H]-"),
        IonSpec("[M-2H]2-", -2, remove="H2"),
        IonSpec("[2M-H]-", -1, remove="H", oligomer=2),
        _formula_species("[M+Cl]-"),
        _formula_species("[M+HCOO]-"),
        _formula_species("[M+OAc]-"),
    )
}
DEFAULT_POSITIVE = ("[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+", "[M+H-H2O]+")
DEFAULT_NEGATIVE = ("[M-H]-", "[M-2H]2-", "[2M-H]-")


def resolved_isotopes(formula, spec, *, parent_mz, resolution_200, max_order=3):
    """Natural fine structure of actual ion composition, merged at one local FWHM."""
    from pyopenms import EmpiricalFormula

    if (
        not isinstance(formula, str)
        or not formula
        or any(token in formula for token in ("(", ")"))
        or re.search(r"(?:D|T)(?![a-z])", formula)
    ):
        raise ValueError("natural neutral formula required")
    molecule = EmpiricalFormula(formula)
    if molecule.getCharge():
        raise ValueError("neutral formula required")
    ion = EmpiricalFormula()
    for _ in range(spec.oligomer):
        ion = ion + molecule
    ion = ion + EmpiricalFormula(spec.add) - EmpiricalFormula(spec.remove)
    if any(count < 0 for count in ion.getElementalComposition().values()):
        raise ValueError("ion removes unavailable atoms")
    fine = fine_isotope_ratios(ion, max_order)
    clusters = resolve_isotope_ratios(fine, parent_mz, spec.charge, resolution_200)
    for cluster in clusters:
        del cluster["components"]
    return clusters
