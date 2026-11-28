"""Adduct definitions and neutral/ion mass conversion."""

from __future__ import annotations

PROTON = 1.007276466812
NA = 22.989218
K = 38.963158
NH4 = 18.033823
CL = 34.969402
FA = 44.998201
ELECTRON_MASS = 0.000548579909065

FORMULA_ADDUCTS = {
    "[M+H-H2O]+": {"polarity": "pos", "add": "H", "remove": "H2O", "charge": 1},
    "[M+H]+": {"polarity": "pos", "add": "H", "remove": "", "charge": 1},
    "[M+Na]+": {"polarity": "pos", "add": "Na", "remove": "", "charge": 1},
    "[M+K]+": {"polarity": "pos", "add": "K", "remove": "", "charge": 1},
    "[M+NH4]+": {"polarity": "pos", "add": "NH4", "remove": "", "charge": 1},
    "[M+2Na-H]+": {"polarity": "pos", "add": "Na2", "remove": "H", "charge": 1},
    "[M]+": {"polarity": "pos", "add": "", "remove": "", "charge": 1},
    "[M-H]-": {"polarity": "neg", "add": "", "remove": "H", "charge": -1},
    "[M+Cl]-": {"polarity": "neg", "add": "Cl", "remove": "", "charge": -1},
    "[M+HCOO]-": {"polarity": "neg", "add": "CHO2", "remove": "", "charge": -1},
    "[M+OAc]-": {"polarity": "neg", "add": "C2H3O2", "remove": "", "charge": -1},
}


def formula_mass_shift(add, remove, charge):
    from pyopenms import EmpiricalFormula

    return (
        EmpiricalFormula(add).getMonoWeight()
        - EmpiricalFormula(remove).getMonoWeight()
        - charge * ELECTRON_MASS
    )


def fine_isotope_ratios(ion, max_order):
    from pyopenms import FineIsotopePatternGenerator

    mass = ion.getMonoWeight()
    values = ion.getIsotopeDistribution(FineIsotopePatternGenerator(1e-6)).getContainer()
    peaks = [(float(value.getMZ()) - mass, float(value.getIntensity())) for value in values]
    p0 = sum(p for delta, p in peaks if abs(delta) < 1e-5)
    if p0 <= 0:
        raise ValueError("monoisotopic probability unavailable")
    return [(delta, p / p0, round(delta)) for delta, p in peaks if 1 <= round(delta) <= max_order]


def resolve_isotope_ratios(fine, parent_mz, charge, resolution_200):
    from scMM.file._spectrum import orbitrap_fwhm_at_mz

    clusters = []
    for delta, ratio, order in sorted(fine):
        mz = parent_mz + delta / abs(charge)
        width = orbitrap_fwhm_at_mz(mz, resolution_200)
        if clusters and clusters[-1]["order"] == order and mz - clusters[-1]["first_mz"] <= width:
            group = clusters[-1]
            group["mz"] = (group["mz"] * group["ratio"] + mz * ratio) / (group["ratio"] + ratio)
            group["ratio"] += ratio
            group["components"] += 1
        else:
            clusters.append(
                {"order": order, "mz": mz, "first_mz": mz, "ratio": ratio, "components": 1}
            )
    return clusters


DEFAULT_ADDUCTS_POS = {
    "[M+H]+": {"mass_shift": PROTON, "charge": 1},
    "[M+Na]+": {"mass_shift": NA, "charge": 1},
    "[M+K]+": {"mass_shift": K, "charge": 1},
    "[M+NH4]+": {"mass_shift": NH4, "charge": 1},
}

DEFAULT_ADDUCTS_NEG = {
    "[M-H]-": {"mass_shift": -PROTON, "charge": 1},
    "[M+Cl]-": {"mass_shift": CL, "charge": 1},
    "[M+FA-H]-": {"mass_shift": FA - PROTON, "charge": 1},
}


def theoretical_mz(neutral_mass: float, adduct_info: dict) -> float:
    """Convert neutral mass to theoretical ion m/z for one adduct."""
    charge = adduct_info["charge"]
    if charge == 0:
        raise ValueError("Adduct charge cannot be zero")
    return (neutral_mass + adduct_info["mass_shift"]) / abs(charge)


def neutral_mass_from_mz(mz: float, adduct_info: dict) -> float:
    """Convert observed ion m/z back to neutral mass for one adduct."""
    charge = adduct_info["charge"]
    if charge == 0:
        raise ValueError("Adduct charge cannot be zero")
    return mz * abs(charge) - adduct_info["mass_shift"]
