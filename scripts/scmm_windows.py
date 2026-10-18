"""Prepare and run an isolated Windows source checkout with process UTF-8.

Use a validated portable runtime as the dependency seed. The installed/package
runtime remains separate; all source children resolve this checkout via .pth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / ".tmp/windows-source/runtime"


def check_copy_paths(seed, destinations):
    """Conservatively support hosts/native libraries without long-path opt-in.

    Windows counts UTF-16 code units, excluding the terminating NUL here.
    Directory creation additionally reserves space for an 8.3 file name.
    Inspect relocation targets as well as the initial copy before any write.
    """
    longest = 0
    entries = [(Path(), True)] + [
        (path.relative_to(seed), path.is_dir()) for path in seed.rglob("*")
    ]
    for destination in destinations:
        for relative, directory in entries:
            target = destination / relative
            length = len(str(target).encode("utf-16-le")) // 2
            limit = 247 if directory else 259
            if length > limit:
                raise ValueError(
                    f"Windows path too long ({length} UTF-16 units; limit {limit}): "
                    f"{target}. Choose a shorter new directory with --output "
                    "(delivery check) or --runtime (source prepare)."
                )
            longest = max(longest, length)
    return longest


def binding_text(repository):
    return f"import sys; sys.path.insert(0, {str(repository.resolve())!r})\n"


def clean_environment():
    env = os.environ.copy()
    for name in list(env):
        if name.upper().startswith(("PYTHON", "UV_")):
            env.pop(name)
    return env


def inspect_python(python, *, source=False):
    code = "import ctypes,json,sys; info={'acp':ctypes.windll.kernel32.GetACP(),'prefix':sys.prefix,'version':list(sys.version_info[:3]),'bits':64 if sys.maxsize>2**32 else 32};"
    if source:
        code += "import scMM; info['scmm']=scMM.__file__;"
    code += "print(json.dumps(info))"
    result = subprocess.check_output([python, "-I", "-c", code], env=clean_environment(), text=True)
    info = json.loads(result)
    if info["version"][:2] != [3, 12] or info["bits"] != 64:
        raise ValueError(
            "Windows source support currently requires the validated Python 3.12 x64 family"
        )
    if info["acp"] != 65001:
        raise ValueError(
            "This interpreter lacks native process UTF-8; use an updated assembled/validated runtime"
        )
    if Path(info["prefix"]).resolve() != python.parent.resolve():
        raise ValueError("Interpreter prefix escapes the private runtime")
    if source and Path(info["scmm"]).resolve() != (ROOT / "scMM/__init__.py").resolve():
        raise ValueError("Source environment is loading a different scMM checkout")
    return info


def prepare(seed, output):
    if output.exists() or output.is_relative_to(seed) or seed.is_relative_to(output):
        raise ValueError("Choose a new source runtime directory outside the seed")
    check_copy_paths(seed, [output])
    if not (seed / "poc.json").is_file():
        raise ValueError("Seed must be an assembled WIN-01 runtime, not a system Python/venv")
    manifest = json.loads((seed / "poc.json").read_text(encoding="utf-8"))
    if (
        manifest.get("uv_lock_sha256")
        != hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    ):
        raise ValueError(
            "Seed dependencies differ from this checkout's lock; assemble the current lock first"
        )
    inspect_python(seed / "python/python.exe")
    size = 0
    for path in seed.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Seed contains links/junctions")
        if path.is_file():
            size += path.stat().st_size
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < size * 2:
        raise ValueError("Insufficient space for a separate source environment")
    if (seed / "python/Lib/site-packages/scmm_source.pth").exists():
        raise ValueError("Seed is already bound to source; use the packaged seed")
    shutil.copytree(seed, output)
    site = output / "python/Lib/site-packages"
    if not site.is_dir():
        raise ValueError("Private site-packages directory is missing")
    (site / "scmm_source.pth").write_text(binding_text(ROOT), encoding="utf-8")
    info = inspect_python(output / "python/python.exe", source=True)
    (output / "source.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "repository": str(ROOT),
                "interpreter": info,
                "pyproject_sha256": hashlib.sha256(
                    (ROOT / "pyproject.toml").read_bytes()
                ).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Source environment ready: {output / 'python/python.exe'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("prepare")
    setup.add_argument("--from-runtime", type=Path, required=True)
    setup.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    execute = subparsers.add_parser("run")
    execute.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    execute.add_argument("python_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("This entry is for Windows; Linux keeps its existing uv workflow")
    try:
        runtime = args.runtime.resolve()
        if args.command == "prepare":
            prepare(args.from_runtime.resolve(strict=True), runtime)
            return 0
        if not (runtime / "source.json").is_file():
            raise ValueError(
                "Prepare the source runtime first; no fallback to system/package Python"
            )
        binding = json.loads((runtime / "source.json").read_text(encoding="utf-8"))
        if (
            binding["pyproject_sha256"]
            != hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest()
        ):
            raise ValueError(
                "Project dependencies/version changed; prepare a current source runtime"
            )
        python = runtime / "python/python.exe"
        inspect_python(python, source=True)
        arguments = args.python_args
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        if not arguments:
            raise ValueError(
                "Supply Python arguments after run -- (for example -m scMM.cli --help)"
            )
        return subprocess.run(
            [python, "-I", *arguments], env=clean_environment(), check=False
        ).returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Windows source environment failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
