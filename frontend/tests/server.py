"""Ephemeral synthetic server for browser tests; never opens user projects."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
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
        data = AnnData(
            np.arange(1.0, 25.0).reshape(6, 4),
            obs=pd.DataFrame(
                {"sample": ["alpha"] * 3 + ["beta"] * 3, "group": ["对照"] * 3 + ["处理"] * 3},
                index=[f"cell{i}" for i in range(6)],
            ),
        )
        data.write_h5ad(results / "example.h5ad")
        os.environ["SCMM_PREFERENCES"] = str(root / "preferences.json")
        app = create_app(
            [StorageRoot("Raw", raw)], [StorageRoot("Results", results)], project_root=projects
        )
        app.state.workspaces.store.create("已有项目", app.state.workspaces.defaults)
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SCMM_E2E_PORT", "5117")))


if __name__ == "__main__":
    main()
