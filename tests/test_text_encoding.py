"""Persisted UTF-8 data must survive a native library switching locale to C."""

import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from scMM.application.preferences import save_preferences
from scMM.application.preview_cache import digest_file, signature
from scMM.application.processing import ProcessingParameters
from scMM.application.projects import write_json

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires POSIX C locale")


def ascii_process(source, *args):
    result = subprocess.run(
        [sys.executable, "-c", source, *map(str, args)],
        cwd=Path(__file__).parents[1],
        env={
            **os.environ,
            "LC_ALL": "C",
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_chinese_preferences_load_with_ascii_default_encoding(tmp_path, monkeypatch):
    path = tmp_path / "preferences.json"
    monkeypatch.setenv("SCMM_PREFERENCES", str(path))
    save_preferences({"哺乳动物": 760.5851, "细菌": 690.5069}, "细菌")
    ascii_process(
        r"""
import locale
from scMM.application.preferences import load_preferences
assert locale.getencoding() in {'ANSI_X3.4-1968', 'ascii'}
preferences = load_preferences()
assert preferences['selected'].encode('utf-8').hex() == 'e7bb86e88f8c'
assert preferences['presets'][preferences['selected']] == 690.5069
"""
    )


def test_preview_metadata_reuse_with_ascii_default_encoding(tmp_path):
    raw = tmp_path / "input.mzML"
    raw.write_bytes(b"identity-only fixture")
    folder = tmp_path / "preview"
    folder.mkdir()
    output = folder / "data.h5ad"
    output.write_bytes(b"digest-only fixture")
    parameters = asdict(ProcessingParameters(ref_mz=150.0))
    identity = signature(raw, parameters)
    write_json(
        folder / "identity.json", {**identity, "sha256": digest_file(output), "note": "中文"}
    )
    write_json(
        folder / "detection.json",
        {"reference_mz": [150.0], "window_ranges": [[1, 3]], "cell_count": 1, "note": "中文"},
    )
    pd.DataFrame({"scan_index": [0], "rt_seconds": [1.0]}).to_csv(
        folder / "traces.csv", index=False
    )
    ascii_process(
        """
import sys
from pathlib import Path
from dataclasses import asdict
from scMM.application.processing import ProcessingParameters
from scMM.application.preview_cache import reusable_preview, load_detection
root = Path(sys.argv[1])
sample = {'path': str(root/'input.mzML'), 'parameters': asdict(ProcessingParameters(ref_mz=150.0)),
          'preview': {'artifact': 'preview'}}
output = reusable_preview(root, sample)
assert output == root/'preview/data.h5ad'
assert load_detection(output).cell_count == 1
""",
        tmp_path,
    )


def test_environment_config_and_task_metadata_use_utf8(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    write_json(root / "state.json", {"status": "completed", "message": "处理完成"})
    config = tmp_path / "config.json"
    write_json(
        config,
        {"prod_results": str(root), "state": str(tmp_path / "state"), "origins": ["中文.invalid"]},
    )
    ascii_process(
        """
import sys
from pathlib import Path
from scripts import scmm_env as manager
values = manager.settings(Path(sys.argv[1]))
assert 'origins' not in values
manager.run = lambda *args, **kwargs: ''
manager.web_idle = lambda *_args, **_kwargs: None
manager.idle(values)
env, _ = manager.environment(values, 'dev')
assert env['PYTHONUTF8'] == '1'
""",
        config,
    )
