"""Synthetic lipid records and exact mass matrices; no network or private data."""

import numpy as np
import pandas as pd
from anndata import AnnData
from pyopenms import EmpiricalFormula

from scMM.application.workbench import AnalysisWorkspace
from scMM.util.intensity import write_intensity_states
from scMM.util.lipid_isotopes import ADDUCTS, adduct_shift, fine_distribution, resolved_distribution


def sdf_record(
    identifier="LMGP01010001", formula="C10H20", name="Synthetic A", abbreviation="PC 10:0"
):
    mass = EmpiricalFormula(formula).getMonoWeight()
    return f"""{name}
  scMM synthetic

>  <LM_ID>
{identifier}

>  <NAME>
{name}

>  <EXACT_MASS>
{mass:.12f}

>  <FORMULA>
{formula}

>  <CATEGORY>
Glycerophospholipids [GP]

>  <MAIN_CLASS>
Glycerophosphocholines [GP01]

>  <ABBREVIATION>
{abbreviation}

$$$$
"""


def synthetic_data(adduct="[M+H]+", ratios=(1.0, 1.0), duplicate=False):
    parent_mz = EmpiricalFormula("C10H20").getMonoWeight() + adduct_shift(adduct)
    peak = resolved_distribution("C10H20", adduct, 3, parent_mz, 35000)[0]
    parent = np.linspace(100.0, 1000.0, 40)
    child = parent * peak["ratio"] * np.repeat(ratios, 20)
    X = np.column_stack((parent, child, parent * 0.3))
    masses = [parent_mz, peak["mz"], parent_mz + 10]
    if duplicate:
        X = np.column_stack((X, parent * 0.2))
        masses.append(parent_mz)
    data = AnnData(
        X,
        obs=pd.DataFrame({"sample": np.repeat(["a", "b"], 20)}, index=[f"c{i}" for i in range(40)]),
        var=pd.DataFrame({"mz": masses}, index=[f"f{i}" for i in range(len(masses))]),
    )
    state = AnalysisWorkspace()
    write_intensity_states(data, {"X": "raw"})
    state.replace(data)
    data = state.require_data()
    data.layers["feature_snr"] = np.ones(data.shape) * 50
    return data


def options(adduct="[M+H]+"):
    return {
        "database": "test.sdf",
        "polarity": ADDUCTS[adduct]["polarity"],
        "adducts": [adduct],
        "annotation_ppm": 10.0,
        "isotope_ppm": 10.0,
        "max_isotope_order": 3,
        "isotope_tolerance": 0.2,
        "min_valid_cells": 20,
        "intensity_layer": "",
        "resolution": 35000.0,
    }


def overlap_profile(competing=350.0):
    adduct = "[M+H]+"
    width = 0.043
    formulas = ("C42H80NO8P", "C42H82NO8P")
    masses = [
        EmpiricalFormula(formula).getMonoWeight() + adduct_shift(adduct) for formula in formulas
    ]
    mz = np.concatenate([np.linspace(mass - 0.15, mass + 0.15, 201) for mass in masses])
    intensity = np.full_like(mz, 4.0)
    for formula, mono, height in zip(formulas, masses, (1000.0, competing), strict=True):
        for delta, probability, _ in [(0, 1, 0), *fine_distribution(formula, adduct, 3)]:
            intensity += (
                height * probability * np.exp(-4 * np.log(2) * ((mz - mono - delta) / width) ** 2)
            )
    return mz, intensity, masses, [{"formula": formula, "adduct": adduct} for formula in formulas]


def write_annotation_acquisition(path):
    import pyopenms as oms

    mz, intensity, masses, _ = overlap_profile()
    profile = oms.MSSpectrum()
    profile.setMSLevel(1)
    profile.setNativeID("scan=47")
    profile.setRT(30.0)
    profile.setType(oms.SpectrumSettings.SpectrumType.PROFILE)
    profile.set_peaks((mz, intensity))
    fragment = oms.MSSpectrum()
    fragment.setMSLevel(2)
    fragment.setNativeID("scan=48")
    fragment.setRT(31.0)
    fragment.setType(oms.SpectrumSettings.SpectrumType.CENTROID)
    fragment.set_peaks((np.array([120.0, 140.0, 160.0]), np.array([20.0, 60.0, 10.0])))
    precursor = oms.Precursor()
    precursor.setMZ(masses[0])
    precursor.setCharge(1)
    precursor.setIsolationWindowLowerOffset(0.4)
    precursor.setIsolationWindowUpperOffset(0.6)
    precursor.setActivationEnergy(25.0)
    precursor.setActivationMethods({oms.ActivationMethod.HCD})
    fragment.setPrecursors([precursor])
    instrument = fragment.getInstrumentSettings()
    instrument.setPolarity(oms.IonSource.Polarity.POSITIVE)
    fragment.setInstrumentSettings(instrument)
    experiment = oms.MSExperiment()
    experiment.setSpectra([profile, fragment])
    oms.MzMLFile().store(str(path), experiment)
    return masses
