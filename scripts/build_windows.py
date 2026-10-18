"""WIN-01 dependency audit and offline portable runtime PoC; never an installer.

Run with the repository's locked development environment (packaging is supplied
by build). Audit/download work on Linux; assemble requires native Windows x64.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import runpy
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "packaging/windows/runtime.json"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def requirements(wheels):
    return "".join(f"{w['name']}=={w['version']} --hash=sha256:{w['sha256']}\n" for w in wheels)


def windows_wheels(lock, config):
    """Select one compatible wheel per active package, never a source archive."""
    version = tuple(map(int, config["python"].split(".")))
    environment = default_environment()
    environment.update(
        implementation_name="cpython",
        implementation_version=config["python"],
        os_name="nt",
        platform_machine="AMD64",
        platform_python_implementation="CPython",
        platform_release="11",
        platform_system="Windows",
        platform_version="",
        python_full_version=config["python"],
        python_version=".".join(map(str, version[:2])),
        sys_platform="win32",
        extra="",
    )
    tags = list(cpython_tags(version[:2], platforms=[config["platform"]]))
    tags += list(compatible_tags(version[:2], interpreter="cp312", platforms=[config["platform"]]))
    priority = {tag: index for index, tag in reversed(list(enumerate(tags)))}
    selected = {}
    for package in lock["packages"]:
        if package.get("marker") and not Marker(package["marker"]).evaluate(environment):
            continue
        name = canonicalize_name(package["name"])
        if name in selected:
            raise ValueError(f"Ambiguous active versions: {name}")
        choices = []
        for wheel in package.get("wheels", []):
            filename = unquote(Path(urlsplit(wheel["url"]).path).name)
            wheel_name, wheel_version, _, wheel_tags = parse_wheel_filename(filename)
            matches = wheel_tags & priority.keys()
            if matches and wheel_name == name and str(wheel_version) == package["version"]:
                choices.append((min(priority[tag] for tag in matches), filename, wheel))
        if not choices:
            raise ValueError(
                f"No locked Windows CPython 3.12 x64 wheel: {name}=={package['version']}"
            )
        _, filename, wheel = min(choices, key=lambda item: item[:2])
        selected[name] = {
            "name": name,
            "version": package["version"],
            "filename": filename,
            "url": wheel["url"],
            "sha256": wheel["hashes"]["sha256"],
        }
    missing = set(config["required_packages"]) - selected.keys()
    if missing:
        raise ValueError(f"Required runtime packages missing: {sorted(missing)}")
    return list(selected.values())


def run(command, **kwargs):
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def require_uv(config):
    actual = subprocess.check_output(["uv", "--version"], text=True).strip()
    if actual.split()[:2] != ["uv", config["uv"]]:
        raise ValueError(f"Expected uv {config['uv']}, found {actual}")


def audit(output, config):
    require_uv(config)
    output.mkdir(parents=True, exist_ok=False)
    exported = output / "pylock.windows.toml"
    command = [
        "uv",
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--format",
        "pylock.toml",
    ]
    for extra in config["extras"]:
        command.extend(["--extra", extra])
    run([*command, "--output-file", exported], cwd=ROOT, stdout=subprocess.DEVNULL)
    wheels = windows_wheels(tomllib.loads(exported.read_text(encoding="utf-8")), config)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    manifest = {
        "schema": 1,
        "purpose": "WIN-01 PoC, not a release",
        "git_commit": revision,
        "dirty": bool(dirty),
        "uv_lock_sha256": digest(ROOT / "uv.lock"),
        "pyproject_sha256": digest(ROOT / "pyproject.toml"),
        "runtime": config,
        "wheels": wheels,
    }
    write_json(output / "inputs.json", manifest)
    (output / "requirements.txt").write_text(
        requirements(wheels),
        encoding="utf-8",
    )
    print(f"Audited {len(wheels)} locked Windows wheels; native execution pending: {output}")


def download_verified(url, expected, destination):
    if destination.exists():
        if digest(destination) != expected:
            raise ValueError(f"Existing input checksum mismatch: {destination.name}")
        return
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if digest(temporary) != expected:
            raise ValueError(f"Downloaded input checksum mismatch: {destination.name}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def download(inputs):
    manifest = json.loads((inputs / "inputs.json").read_text(encoding="utf-8"))
    wheels = inputs / "wheelhouse"
    wheels.mkdir(exist_ok=True)
    for wheel in manifest["wheels"]:
        download_verified(wheel["url"], wheel["sha256"], wheels / wheel["filename"])
    runtime = manifest["runtime"]
    download_verified(runtime["url"], runtime["sha256"], inputs / "python.tar.gz")
    print(f"Verified {len(manifest['wheels'])} wheels and Python archive: {inputs}")


def extract_runtime(archive, destination):
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            parts = Path(member.name).parts
            if (
                not parts
                or parts[0] != "python"
                or ".." in parts
                or "\\" in member.name
                or ":" in member.name
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError(f"Unsafe runtime archive member: {member.name}")
        source.extractall(destination, filter="data")


def isolated_environment(runtime):
    environment = os.environ.copy()
    for key in list(environment):
        if key.upper().startswith(("PYTHON", "UV_")):
            environment.pop(key)
    state = runtime.parent / (runtime.name + "-validation-state")
    state.mkdir(exist_ok=True)
    for variable, directory in {
        "TEMP": "tmp",
        "TMP": "tmp",
        "MPLCONFIGDIR": "matplotlib",
        "NUMBA_CACHE_DIR": "numba",
    }.items():
        path = state / directory
        path.mkdir(exist_ok=True)
        environment[variable] = str(path)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    return environment


def assemble(inputs, wheel, output):
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError(
            "Assembly requires native Windows x64; Linux audit is not Windows acceptance"
        )
    manifest = json.loads((inputs / "inputs.json").read_text(encoding="utf-8"))
    require_uv(manifest["runtime"])
    if output.exists():
        raise ValueError("Output already exists; choose a new PoC directory")
    name, version, _, _ = parse_wheel_filename(wheel.name)
    if name != "scmm":
        raise ValueError("Expected a scMM wheel")
    with zipfile.ZipFile(wheel) as package:
        if "scMM/api/static/index.html" not in package.namelist():
            raise ValueError("scMM wheel must contain the built Vue page")
        if not any(name.startswith("scMM/resources/lipid_rules/") for name in package.namelist()):
            raise ValueError("scMM wheel lacks rule resources")
    if digest(inputs / "python.tar.gz") != manifest["runtime"]["sha256"]:
        raise ValueError("Python archive checksum mismatch")
    for item in manifest["wheels"]:
        if digest(inputs / "wheelhouse" / item["filename"]) != item["sha256"]:
            raise ValueError(f"Wheel checksum mismatch: {item['filename']}")
    output.mkdir(parents=True)
    # Reconstruct from verified inputs rather than trusting an edited requirements file.
    install_requirements = output / "runtime-requirements.txt"
    install_requirements.write_text(
        requirements(manifest["wheels"])
        + f"scmm[{','.join(manifest['runtime']['extras'])}]=={version} --hash=sha256:{digest(wheel)}\n",
        encoding="utf-8",
    )
    extract_runtime(inputs / "python.tar.gz", output)
    python = output / "python/python.exe"
    encoding_tools = runpy.run_path(
        str(ROOT / "scripts/probe_windows_utf8.py"), run_name="scmm_encoding_tools"
    )
    original_python_hash = digest(python)
    if original_python_hash != encoding_tools["SOURCE_EXE_SHA256"]:
        raise ValueError("Extracted Python differs from the validated UTF-8 candidate")
    manifest["windows_encoding"] = {
        "source_python_sha256": original_python_hash,
        "manifest_updates": encoding_tools["patch_copy"](python),
        "patched_python_sha256": digest(python),
        "ansi_codepage": 65001,
    }
    environment = isolated_environment(output)
    codepage = subprocess.check_output(
        [python, "-I", "-c", "import ctypes; print(ctypes.windll.kernel32.GetACP())"],
        text=True,
        env=environment,
    ).strip()
    if codepage != "65001":
        raise ValueError("Portable Python process UTF-8 activation failed")
    actual = subprocess.check_output(
        [python, "-I", "-c", "import platform; print(platform.python_version())"],
        text=True,
        env=environment,
    ).strip()
    if actual != manifest["runtime"]["python"]:
        raise ValueError(f"Unexpected portable Python version: {actual}")
    base = [
        "uv",
        "--no-config",
        "--offline",
        "--no-cache",
        "pip",
        "install",
        "--python",
        python,
        "--system",
        "--no-index",
        "--only-binary",
        ":all:",
    ]
    run(
        [
            *base,
            "--find-links",
            inputs / "wheelhouse",
            "--find-links",
            wheel.parent,
            "--require-hashes",
            "-r",
            install_requirements,
        ],
        env=environment,
    )
    run(["uv", "--offline", "pip", "check", "--python", python], env=environment)
    shutil.copy2(ROOT / "scripts/validate_windows_runtime.py", output)
    shutil.copy2(ROOT / "packaging/windows/validate-runtime.ps1", output)
    manifest["scmm_wheel"] = {"filename": wheel.name, "sha256": digest(wheel)}
    manifest["validation_script_sha256"] = digest(output / "validate_windows_runtime.py")
    # Successful assembly alone says nothing about scientific/clean-machine acceptance.
    write_json(output / "poc.json", manifest)
    print(f"Offline runtime assembled; validate before and after relocation: {output}")


def create_kit(inputs, wheel, uv_archive, output):
    """Package native build inputs and bootstrap without executing Windows code."""
    if output.exists() or output.with_suffix(output.suffix + ".partial").exists():
        raise ValueError("Kit output already exists; choose a new path")
    manifest = json.loads((inputs / "inputs.json").read_text(encoding="utf-8"))
    tools = json.loads((ROOT / "packaging/windows/build-tools.json").read_text(encoding="utf-8"))
    if tools["uv"]["version"] != manifest["runtime"]["uv"]:
        raise ValueError("Kit uv version differs from runtime inputs")
    if digest(uv_archive) != tools["uv"]["sha256"]:
        raise ValueError("Kit uv archive checksum mismatch")
    if digest(inputs / "python.tar.gz") != manifest["runtime"]["sha256"]:
        raise ValueError("Kit Python archive checksum mismatch")
    files = {}
    for item in manifest["wheels"]:
        path = inputs / "wheelhouse" / item["filename"]
        if Path(item["filename"]).name != item["filename"] or digest(path) != item["sha256"]:
            raise ValueError(f"Kit wheel checksum/path mismatch: {item['name']}")
        files[f"inputs/wheelhouse/{item['filename']}"] = path
    for name in ("inputs.json", "python.tar.gz", "pylock.windows.toml", "requirements.txt"):
        files[f"inputs/{name}"] = inputs / name
    wheel_name, _, _, _ = parse_wheel_filename(wheel.name)
    if wheel_name != "scmm":
        raise ValueError("Expected scMM wheel in kit")
    files[f"dist/{wheel.name}"] = wheel
    for name in (
        "scripts/build_windows.py",
        "scripts/validate_windows_runtime.py",
        "scripts/probe_windows_utf8.py",
        "packaging/windows/runtime.json",
        "packaging/windows/build-tools.json",
        "packaging/windows/validate-runtime.ps1",
    ):
        files[name] = ROOT / name
    files["run-win01.ps1"] = ROOT / "packaging/windows/run-win01.ps1"
    files["README.txt"] = ROOT / "packaging/windows/WIN01-README.txt"
    for path in sorted((ROOT / "packaging/windows/licenses").glob("*.txt")):
        files[f"licenses/{path.name}"] = path
    if not any(name.startswith("licenses/") for name in files):
        raise ValueError("Kit requires bundled build tool license notices")
    with zipfile.ZipFile(uv_archive) as archive:
        uv_executable = archive.read("uv.exe")
    entries = [{"path": name, "sha256": digest(path)} for name, path in sorted(files.items())]
    entries.append({"path": "tools/uv.exe", "sha256": hashlib.sha256(uv_executable).hexdigest()})
    packaging_wheel = next(item for item in manifest["wheels"] if item["name"] == "packaging")
    kit = {
        "schema": 1,
        "kind": "WIN-01 validation only; not an application installer",
        "kit_id": hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        "packaging_wheel": f"inputs/wheelhouse/{packaging_wheel['filename']}",
        "scmm_wheel": f"dist/{wheel.name}",
        "build_tools": tools,
        "files": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            for name, path in sorted(files.items()):
                archive.write(path, name)
            archive.writestr("tools/uv.exe", uv_executable)
            archive.writestr("kit.json", json.dumps(kit, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = digest(output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{checksum}  {output.name}\n", encoding="ascii"
    )
    print(f"Offline WIN-01 kit: {output} ({output.stat().st_size} bytes); SHA-256 {checksum}")


def create_delivery(wheel, output):
    if output.exists():
        raise ValueError("Delivery output already exists")
    files = {}
    extensions = {".py", ".json", ".html", ".js", ".css"}
    for path in (ROOT / "scMM").rglob("*"):
        if path.is_file() and path.suffix in extensions and "__pycache__" not in path.parts:
            relative = path.relative_to(ROOT).as_posix()
            files[f"source/{relative}"] = path
    with zipfile.ZipFile(wheel) as package:
        expected = {name.removeprefix("source/") for name in files}
        actual = {
            name
            for name in package.namelist()
            if name.startswith("scMM/") and Path(name).suffix in extensions
        }
        if actual != expected:
            raise ValueError("Source/wheel inventories differ; rebuild from the current checkout")
        for name, path in files.items():
            relative = name.removeprefix("source/")
            if package.read(relative) != path.read_bytes():
                raise ValueError(f"Source and wheel differ: {relative}; rebuild the wheel")
    for name in (
        "scripts/scmm_windows.py",
        "scripts/validate_windows_runtime.py",
        "pyproject.toml",
        "uv.lock",
    ):
        files[f"source/{name}"] = ROOT / name
    files["validate-delivery.py"] = ROOT / "scripts/validate_windows_delivery.py"
    files[f"dist/{wheel.name}"] = wheel
    entries = [{"path": name, "sha256": digest(path)} for name, path in sorted(files.items())]
    manifest = {
        "schema": 1,
        "wheel": f"dist/{wheel.name}",
        "wheel_sha256": digest(wheel),
        "source_sha256": hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        "io_sha256": digest(ROOT / "scMM/file/io.py"),
        "files": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    if temporary.exists():
        raise ValueError("Partial delivery archive exists; choose a new output")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in sorted(files.items()):
                archive.write(path, name)
            archive.writestr("delivery.json", json.dumps(manifest, indent=2) + "\n")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest(output)}  {output.name}\n", encoding="ascii"
    )
    print(f"Source/wheel native verification kit: {output} ({output.stat().st_size} bytes)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("audit")
    plan.add_argument("--output", type=Path, required=True)
    fetch = commands.add_parser("download")
    fetch.add_argument("--inputs", type=Path, required=True)
    build = commands.add_parser("assemble")
    build.add_argument("--inputs", type=Path, required=True)
    build.add_argument("--wheel", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    kit = commands.add_parser("kit", help="Create the self-contained Windows validation ZIP")
    kit.add_argument("--inputs", type=Path, required=True)
    kit.add_argument("--wheel", type=Path, required=True)
    kit.add_argument("--uv-archive", type=Path, required=True)
    kit.add_argument("--output", type=Path, required=True)
    delivery = commands.add_parser(
        "delivery", help="Package matching source and wheel for native verification"
    )
    delivery.add_argument("--wheel", type=Path, required=True)
    delivery.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            audit(args.output.resolve(), json.loads(CONFIG.read_text(encoding="utf-8")))
        elif args.command == "download":
            download(args.inputs.resolve())
        elif args.command == "assemble":
            assemble(args.inputs.resolve(), args.wheel.resolve(), args.output.resolve())
        elif args.command == "kit":
            create_kit(
                args.inputs.resolve(),
                args.wheel.resolve(),
                args.uv_archive.resolve(),
                args.output.resolve(),
            )
        else:
            create_delivery(args.wheel.resolve(), args.output.resolve())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"WIN-01 failed: {error}\n")


if __name__ == "__main__":
    main()
