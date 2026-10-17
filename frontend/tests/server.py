"""Ephemeral synthetic server for browser tests; never opens user projects."""

import json
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

from types import SimpleNamespace

from scMM.api.app import STATIC_ROOT, create_app
from scMM.application.auth import AuthStore
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
        # Local synthetic lipid database and peaks: browser tests never download LMSD.
        from scMM.util.lipid_isotopes import adduct_shift, resolved_distribution

        formula = "C10H20"
        mass = oms.EmpiricalFormula(formula).getMonoWeight()
        protonated = mass + adduct_shift("[M+H]+")
        peak = resolved_distribution(formula, "[M+H]+", 3, protonated, 35000)[0]
        parent = np.linspace(100.0, 1000.0, 40)
        lipids = AnnData(
            np.column_stack([parent, parent * peak["ratio"], parent * 0.3, parent * 0.1]),
            obs=pd.DataFrame(
                {"sample": np.repeat(["a", "b"], 20)}, index=[f"lipid-cell{i}" for i in range(40)]
            ),
            var=pd.DataFrame(
                {"mz": [protonated, peak["mz"], mass + adduct_shift("[M+Na]+"), 300.0]},
                index=["f_h", "f_iso", "f_na", "f_unknown"],
            ),
        )
        lipids.write_h5ad(results / "lipids.h5ad")
        database = root / "lipid-database"
        database.mkdir()
        records = []
        for i, name in enumerate(["Synthetic lipid A", "Synthetic lipid B"], 1):
            properties = {
                "LM_ID": f"LMGP0101000{i}",
                "NAME": name,
                "EXACT_MASS": str(mass),
                "FORMULA": formula,
                "CATEGORY": "Glycerophospholipids [GP]",
                "MAIN_CLASS": "Glycerophosphocholines [GP01]",
                "ABBREVIATION": "PC 10:0",
            }
            records.append(
                name
                + "\n  synthetic\n\n"
                + "".join(f">  <{key}>\n{value}\n\n" for key, value in properties.items())
                + "$$$$\n"
            )
        (database / "synthetic.sdf").write_text("".join(records))
        os.environ["SCMM_LIPID_DATABASE_DIR"] = str(database)
        os.environ["SCMM_PREFERENCES"] = str(root / "preferences.json")
        # Load the review files into this temporary preset store, never the live one.
        from scMM.application.web_lipids import save_rules_preset

        rules_root = Path(__file__).resolve().parents[2] / "rules/lipids"
        for path in sorted(rules_root.glob("*.review-v1.json")):
            rules = json.loads(path.read_text(encoding="utf-8"))
            save_rules_preset(rules["name"], rules)
        auth, initial = AuthStore.initialize(root / "auth.sqlite3", "browser")
        _, principal = auth.login("browser", initial, "local")
        auth.change_password(
            principal, "", os.environ.get("SCMM_E2E_PASSWORD", "Synthetic browser passphrase")
        )
        app = create_app(
            [StorageRoot("Raw", raw)],
            [StorageRoot("Results", results)],
            project_root=projects,
            static_root=os.environ.get("SCMM_TEST_STATIC_ROOT") or STATIC_ROOT,
            auth_store=auth,
            server_config=SimpleNamespace(cookie_name="scmm_e2e", cookie_secure=False, origins=()),
        )
        # AI uses real encrypted settings and HTTP routes, with a synthetic upstream.
        # No user credentials or external model service are needed by browser tests.
        import asyncio

        import httpx

        from scMM.application.ai_client import ChatClient, normalize_url
        from scMM.application.ai_config import AIConfigStore

        app.state.ai_config = AIConfigStore.initialize(
            root / "private-ai.sqlite3", root / "keys/ai.key"
        )

        class SyntheticPolicy:
            async def target(self, value):
                normalize_url(value)
                return (
                    "https://127.0.0.1/v1/chat/completions",
                    "synthetic.example",
                    "synthetic.example",
                )

        class SyntheticStream(httpx.AsyncByteStream):
            def __init__(self, slow):
                self.slow = slow

            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"synthetic answer"}}]}\n\n'
                await asyncio.sleep(5 if self.slow else 0.1)
                yield b'data: {"choices":[{"delta":{"content":" completed"}}]}\n\ndata: [DONE]\n\n'

        def upstream(request):
            payload = json.loads(request.content)
            slow = "慢" in payload["messages"][-1]["content"]
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=SyntheticStream(slow)
            )

        app.state.ai_client = ChatClient(SyntheticPolicy(), transport=httpx.MockTransport(upstream))
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
