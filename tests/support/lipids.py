"""Synthetic lipid records and exact mass matrices; no network or private data."""

import numpy as np
import pandas as pd
from anndata import AnnData
from pyopenms import EmpiricalFormula

from scMM.application.workbench import AnalysisWorkspace
from scMM.util.intensity import write_intensity_states
from scMM.util.lipid_isotopes import ADDUCTS, adduct_shift, resolved_distribution


def sdf_record(identifier="LMGP01010001", formula="C10H20", name="Synthetic A"):
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
PC 10:0

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
