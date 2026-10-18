"""Validate the source snapshot and wheel independently on Windows.

Consumes an existing UTF-8 WIN-01 runtime; preserves that seed. No account,
service, real RAW, external connection or experimental project is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def default_output():
    # Do not nest another gigabyte-sized tree beside an already relocated seed.
    return Path(tempfile.gettempdir()) / time.strftime("sd-%m%d-%H%M%S")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32" or not sys.flags.isolated:
        parser.error("Run with the validated private Windows Python and -I")
    kit = Path(__file__).resolve().parent
    manifest = json.loads((kit / "delivery.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = (kit / item["path"]).resolve()
        if not path.is_relative_to(kit) or digest(path) != item["sha256"]:
            parser.error("Delivery file checksum or path mismatch")
    seed = args.runtime.resolve(strict=True)
    if (seed / "python/Lib/site-packages/scmm_source.pth").exists():
        parser.error(
            "Seed must be the packaged/UTF-8 trial runtime, not a source-bound environment"
        )
    for path in seed.rglob("*"):
        if path.is_symlink() or path.is_junction():
            parser.error("Seed has links/junctions")
    source_tools = runpy.run_path(str(kit / "source/scripts/scmm_windows.py"))
    source_tools["inspect_python"](seed / "python/python.exe")
    output = (args.output or default_output()).resolve()
    if output.exists() or output.is_relative_to(seed) or seed.is_relative_to(output):
        parser.error("Choose a new output directory outside the seed")
    wheel_runtime = output / "w"
    source_runtime = output / "s"
    repository = output / "中文 源码"
    relocated = {mode: output / f"中文 {mode[0]}" for mode in ("wheel", "source")}
    try:
        longest = source_tools["check_copy_paths"](
            seed, [wheel_runtime, source_runtime, *relocated.values()]
        )
        source_tools["check_copy_paths"](kit / "source", [repository])
    except ValueError as error:
        parser.error(str(error))
    output.parent.mkdir(parents=True, exist_ok=True)
    size = sum(path.stat().st_size for path in seed.rglob("*") if path.is_file())
    if shutil.disk_usage(output.parent).free < size * 3:
        parser.error(
            "Insufficient free space for separate wheel/source copies and temporary computation"
        )
    output.mkdir()
    report = {
        "schema": 1,
        "kind": "Source/wheel synthetic validation; complete Windows product acceptance separate",
        "status": "running",
        "output": str(output),
        "runtime_copy_max_utf16_units": longest,
        "wheel_sha256": manifest["wheel_sha256"],
        "source_sha256": manifest["source_sha256"],
        "remaining_gates": [
            "Windows authentication and NTFS ACL",
            "persistent task/lock/recovery and monitoring",
            "real Thermo RAW and helper redistribution/runtime",
            "clean-machine and Chinese user account",
            "full offline installer and browser workflow",
        ],
    }
    env = source_tools["clean_environment"]()
    for variable, folder in {
        "TEMP": "tmp",
        "TMP": "tmp",
        "MPLCONFIGDIR": "matplotlib",
        "NUMBA_CACHE_DIR": "numba",
    }.items():
        path = output / "validation-state" / folder
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path)

    def execute(python, arguments):
        result = subprocess.run(
            [str(python), "-I", *map(str, arguments)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
        with (output / "diagnostics.txt").open("ab") as stream:
            stream.write(result.stdout)
        if result.returncode:
            raise RuntimeError(f"Child exited {result.returncode}; see diagnostics.txt")

    try:
        print(f"Validation output: {output}")
        print("Copying the packaged dependency seed...")
        shutil.copytree(seed, wheel_runtime)
        python = wheel_runtime / "python/python.exe"
        print("Installing only the current wheel into the independent copy...")
        execute(
            python,
            [
                "-m",
                "pip",
                "--isolated",
                "install",
                "--no-index",
                "--no-deps",
                "--no-cache-dir",
                "--force-reinstall",
                kit / manifest["wheel"],
            ],
        )
        # Actual repository code is placed in a Chinese directory for the source run.
        shutil.copytree(kit / "source", repository)
        poc = json.loads((wheel_runtime / "poc.json").read_text(encoding="utf-8"))
        poc["scmm_wheel"] = {
            "filename": Path(manifest["wheel"]).name,
            "sha256": manifest["wheel_sha256"],
        }
        poc["source_wheel_delivery"] = {
            "source_sha256": manifest["source_sha256"],
            "io_sha256": manifest["io_sha256"],
        }
        poc["validation_script_sha256"] = digest(repository / "scripts/validate_windows_runtime.py")
        (wheel_runtime / "poc.json").write_text(json.dumps(poc, indent=2) + "\n", encoding="utf-8")
        print("Preparing a separate environment bound to the source checkout...")
        execute(
            python,
            [
                repository / "scripts/scmm_windows.py",
                "prepare",
                "--from-runtime",
                wheel_runtime,
                "--runtime",
                source_runtime,
            ],
        )
        for mode, runtime in (("wheel", wheel_runtime), ("source", source_runtime)):
            python = runtime / "python/python.exe"
            print(f"Checking {mode} API, CLI imports and child-process source identity...")
            for module in ("scMM.cli", "scMM.api.cli", "scMM.api.admin_cli"):
                execute(python, ["-m", module, "--help"])
            # Check code identity rather than treating successful help as a full workflow.
            check = (
                "import hashlib,scMM.file.io; from pathlib import Path; p=Path(scMM.file.io.__file__); assert hashlib.sha256(p.read_bytes()).hexdigest()=="
                + repr(manifest["io_sha256"])
            )
            execute(python, ["-c", check])
            arguments = [repository / "scripts/validate_windows_runtime.py"]
            if mode == "source":
                arguments += ["--source-root", repository]
            execute(python, [*arguments, "--report", output / f"{mode}-before.json"])
            moved = relocated[mode]
            runtime.rename(moved)
            python = moved / "python/python.exe"
            execute(python, [*arguments, "--report", output / f"{mode}-after.json"])
            report[mode] = "checks_passed"
        report["status"] = "checks_passed"
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    (output / "delivery-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{report['status']}: {output}")
    return 0 if report["status"] == "checks_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
