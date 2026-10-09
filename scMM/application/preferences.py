"""Explicitly saved global UI preferences; project parameters remain snapshots."""

import json
import math
import os
from pathlib import Path

BUILTIN_PRESETS = {"哺乳动物": 760.5851, "藻类": 734.5929, "细菌": 690.5069}


def cpu_default():
    count = os.cpu_count() or 1
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else count
    return max(1, min(count // 4, available))


def preferences_path():
    return Path(
        os.environ.get("SCMM_PREFERENCES", "~/data/results/.scmm-preferences.json")
    ).expanduser()


def load_preferences():
    path = preferences_path()
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"presets": dict(BUILTIN_PRESETS), "selected": "哺乳动物"}
    )


def save_preferences(presets, selected):
    from .projects import write_json

    if (
        selected not in presets
        or not presets
        or any(
            not str(k).strip() or not math.isfinite(float(v)) or float(v) <= 0
            for k, v in presets.items()
        )
    ):
        raise ValueError("Presets need unique nonempty names and positive finite masses")
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"presets": {k: float(v) for k, v in presets.items()}, "selected": selected})
