"""Ephemeral synthetic server for browser tests; never opens user projects."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pyopenms as oms
import uvicorn
from anndata import AnnData

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scMM.api.app import create_app
from scMM.application.storage import StorageRoot


def main():
    with TemporaryDirectory(prefix="scmm-vue-e2e-") as temporary:
        root = Path(temporary)
        raw, results, projects = (root / name for name in ("raw", "results", "projects"))
        for directory in (raw, results, projects):
            directory.mkdir()
        for name in ("alpha.mzML", "beta.mzXML"):
            (raw / name).write_text("Synthetic sample, not used for extraction")
        spectra = []
        for i in range(31):
            spectrum = oms.MSSpectrum()
            spectrum.setMSLevel(1)
            spectrum.setRT(float(i))
            spectrum.set_peaks(
                (
                    np.array([149.9, 150.0, 150.1]),
                    np.array([0.0, 20.0 if i in {8, 22} else 1.0, 0.0]),
                )
            )
            spectra.append(spectrum)
        from scMM.file.io import save_spectra

        save_spectra(spectra, raw / "extract.mzML")
        data = AnnData(
            np.arange(1.0, 25.0).reshape(6, 4),
            obs=pd.DataFrame(
                {"sample": ["alpha"] * 3 + ["beta"] * 3, "group": ["对照"] * 3 + ["处理"] * 3},
                index=[f"cell{i}" for i in range(6)],
            ),
        )
        data.write_h5ad(results / "example.h5ad")
        rng = np.random.default_rng(12)
        analysis = AnnData(
            rng.uniform(1, 10, (64, 8)),
            obs=pd.DataFrame(
                {
                    "sample": np.repeat([f"s{i}" for i in range(8)], 8),
                    "group": ["a"] * 32 + ["b"] * 32,
                    "subject": np.repeat([f"s{i}" for i in range(8)], 8),
                },
                index=[f"c{i}" for i in range(64)],
            ),
            var=pd.DataFrame({"mz": np.arange(8.0) + 150}, index=[f"f{i}" for i in range(8)]),
        )
        analysis.X[:32, 0] *= 5
        analysis.write_h5ad(results / "analysis.h5ad")
        os.environ["SCMM_PREFERENCES"] = str(root / "preferences.json")
        app = create_app(
            [StorageRoot("Raw", raw)], [StorageRoot("Results", results)], project_root=projects
        )
        app.state.workspaces.store.create("已有项目", app.state.workspaces.defaults)
        from scMM.application.trash import SavedItems

        manager = app.state.workspaces
        manager.saved_items = lambda: SavedItems(
            manager.store,
            [StorageRoot("Results", results)],
            active_paths=manager.active_paths,
            trash_root=root / "trash",
        )
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SCMM_E2E_PORT", "5117")))


if __name__ == "__main__":
    main()
