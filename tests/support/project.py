"""Small real mzML project used by batch, preview and HTTP checks."""

from dataclasses import asdict

import numpy as np
import pyopenms as oms

from scMM.application import StorageCatalog, StorageRoot
from scMM.application.processing import ProcessingParameters
from scMM.application.projects import ProjectStore
from scMM.file.io import save_spectra


def setup_project(tmp_path, *, storage_label="data", sample_names=("a", "b")):
    spectra = []
    for i in range(31):
        s = oms.MSSpectrum()
        s.setMSLevel(1)
        s.setRT(float(i))
        s.set_peaks(
            (np.array([149.9, 150.0, 150.1]), np.array([0.0, 20.0 if i in {8, 22} else 1.0, 0.0]))
        )
        spectra.append(s)
    save_spectra(spectra, tmp_path / "a.mzML")
    save_spectra(spectra, tmp_path / "b.mzML")
    store = ProjectStore(tmp_path)
    project = store.create("batch")
    catalog = StorageCatalog((StorageRoot(storage_label, tmp_path),))
    project.add_files(catalog, storage_label, ["a.mzML", "b.mzML"])
    for sample, name in zip(project.samples, sample_names, strict=True):
        sample["name"] = name
    project.manifest["parameters"] = asdict(
        ProcessingParameters(
            ref_mz=150.0,
            mz_min=140.0,
            mz_max=160.0,
            resolution=5000.0,
            resample_points_per_fwhm=2.0,
            ppm_tol=500.0,
            baseline_filter_size=5,
            cell_min_signal=0,
        )
    )
    return project, catalog
