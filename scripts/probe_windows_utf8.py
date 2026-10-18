"""Test a process-local UTF-8 manifest in a fresh WIN-01 runtime copy.

The original executable, runtime, dependencies and Windows locale are untouched.
This is a candidate repair probe, never a production release operation.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

ASMV1 = "urn:schemas-microsoft-com:asm.v1"
ASMV3 = "urn:schemas-microsoft-com:asm.v3"
UTF8_SETTINGS = "http://schemas.microsoft.com/SMI/2019/WindowsSettings"
SOURCE_EXE_SHA256 = "d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def utf8_manifest(data):
    root = ET.fromstring(data.rstrip(b"\0"))
    if root.tag != f"{{{ASMV1}}}assembly" or root.get("manifestVersion") != "1.0":
        raise ValueError("Unexpected original Python manifest")
    applications = root.findall(f"{{{ASMV3}}}application") + root.findall(f"{{{ASMV1}}}application")
    if len(applications) > 1:
        raise ValueError("Ambiguous application elements in Python manifest")
    application = (
        applications[0] if applications else ET.SubElement(root, f"{{{ASMV3}}}application")
    )
    namespace = application.tag.partition("}")[0] + "}"
    settings = application.find(namespace + "windowsSettings")
    if settings is None:
        settings = ET.SubElement(application, namespace + "windowsSettings")
    existing = root.findall(f".//{{{UTF8_SETTINGS}}}activeCodePage")
    if len(existing) > 1:
        raise ValueError("Ambiguous activeCodePage declarations")
    setting = (
        existing[0] if existing else ET.SubElement(settings, f"{{{UTF8_SETTINGS}}}activeCodePage")
    )
    setting.text = "UTF-8"
    ET.register_namespace("", ASMV1)
    ET.register_namespace("asmv3", ASMV3)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def reject_signed_executable(path):
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("Expected a Windows PE executable")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[offset : offset + 4] != b"PE\0\0":
        raise ValueError("Invalid PE header")
    optional = offset + 24
    if struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise ValueError("Expected PE32+ Windows x64 executable")
    certificate = struct.unpack_from("<II", data, optional + 112 + 4 * 8)
    if any(certificate):
        raise ValueError("Refusing to invalidate a signed executable")


def patch_copy(executable):
    """Preserve every existing manifest language and all other PE resources."""
    reject_signed_executable(executable)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    boolean = ctypes.c_int
    word = ctypes.c_ushort
    dword = ctypes.c_uint32
    callback_type = ctypes.WINFUNCTYPE(boolean, pointer, pointer, pointer, word, ctypes.c_ssize_t)
    signatures = {
        "LoadLibraryExW": ([ctypes.c_wchar_p, pointer, dword], pointer),
        "EnumResourceLanguagesW": (
            [pointer, pointer, pointer, callback_type, ctypes.c_ssize_t],
            boolean,
        ),
        "FindResourceExW": ([pointer, pointer, pointer, word], pointer),
        "SizeofResource": ([pointer, pointer], dword),
        "LoadResource": ([pointer, pointer], pointer),
        "LockResource": ([pointer], pointer),
        "FreeLibrary": ([pointer], boolean),
        "BeginUpdateResourceW": ([ctypes.c_wchar_p, boolean], pointer),
        "UpdateResourceW": ([pointer, pointer, pointer, word, pointer, dword], boolean),
        "EndUpdateResourceW": ([pointer, boolean], boolean),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    module = kernel.LoadLibraryExW(str(executable), None, 0x02 | 0x20)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    languages = []

    @callback_type
    def language_callback(module, resource_type, resource_name, language, parameter):
        languages.append(language)
        return 1

    manifests = []
    try:
        if not kernel.EnumResourceLanguagesW(module, 24, 1, language_callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        for language in languages:
            resource = kernel.FindResourceExW(module, 24, 1, language)
            if not resource:
                raise ctypes.WinError(ctypes.get_last_error())
            size = kernel.SizeofResource(module, resource)
            loaded = kernel.LoadResource(module, resource)
            address = kernel.LockResource(loaded) if loaded else None
            if not size or not address:
                raise ctypes.WinError(ctypes.get_last_error())
            original = ctypes.string_at(address, size)
            manifests.append((language, original, utf8_manifest(original)))
    finally:
        kernel.FreeLibrary(module)
    update = kernel.BeginUpdateResourceW(str(executable), False)
    if not update:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for language, _original, patched in manifests:
            buffer = ctypes.create_string_buffer(patched)
            if not kernel.UpdateResourceW(update, 24, 1, language, buffer, len(patched)):
                raise ctypes.WinError(ctypes.get_last_error())
        handle, update = update, None
        if not kernel.EndUpdateResourceW(handle, False):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if update is not None:
            kernel.EndUpdateResourceW(update, True)
    return [
        {
            "language": language,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "patched_sha256": hashlib.sha256(patched).hexdigest(),
        }
        for language, original, patched in manifests
    ]


def environment(output):
    env = os.environ.copy()
    for name in list(env):
        if name.upper().startswith(("PYTHON", "UV_")):
            env.pop(name)
    for variable, folder in {
        "TEMP": "tmp",
        "TMP": "tmp",
        "MPLCONFIGDIR": "matplotlib",
        "NUMBA_CACHE_DIR": "numba",
    }.items():
        path = output / "validation-state" / folder
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path)
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32" or not sys.flags.isolated or sys.getwindowsversion().build < 22000:
        parser.error("Use the original private Python on Windows 11 x64 with -I")
    source = args.runtime.resolve(strict=True)
    original_python = source / "python/python.exe"
    if digest(original_python) != SOURCE_EXE_SHA256:
        parser.error(
            "Source python.exe differs from the pinned WIN-01 interpreter; no changes made"
        )
    output = (args.output or source.parent / time.strftime("utf8-trial-%Y%m%d-%H%M%S")).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        parser.error("Choose a new output directory outside the original runtime")
    if str(output).startswith("\\\\"):
        parser.error("Choose a local output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    for path in source.rglob("*"):
        if path.is_symlink() or path.is_junction():
            parser.error("Source runtime contains a link/junction; no changes made")
        if path.is_file():
            size += path.stat().st_size
    if shutil.disk_usage(output.parent).free < size * 2:
        parser.error(
            f"Insufficient free disk space for an independent copy and validation ({size * 2} bytes)"
        )
    output.mkdir()
    report = {
        "schema": 1,
        "kind": "Candidate process UTF-8 repair; native acceptance pending",
        "status": "running",
        "source_python_sha256": SOURCE_EXE_SHA256,
        "original_runtime_unchanged": True,
    }
    try:
        runtime = output / "runtime"
        print("Copying the existing runtime; preserving the original...")
        shutil.copytree(source, runtime)
        python = runtime / "python/python.exe"
        report["manifest_updates"] = patch_copy(python)
        report["patched_python_sha256"] = digest(python)
        env = environment(output)

        def run(arguments):
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
                raise RuntimeError(
                    f"Candidate child exited {result.returncode}; inspect diagnostics.txt"
                )
            return result.stdout

        report["candidate_ansi_codepage"] = int(
            run(["-c", "import ctypes; print(ctypes.windll.kernel32.GetACP())"]).strip()
        )
        if report["candidate_ansi_codepage"] != 65001:
            raise RuntimeError("Manifest did not activate process UTF-8; stopping")
        scripts = Path(__file__).resolve().parent
        run(
            [scripts / "diagnose_windows_openms.py", "--report", output / "openms-utf8-report.json"]
        )
        diagnostic = json.loads((output / "openms-utf8-report.json").read_text(encoding="utf-8"))
        if diagnostic["status"] != "diagnosis_completed" or any(
            check["status"] != "passed" for check in diagnostic["checks"].values()
        ):
            raise RuntimeError("Some OpenMS path probes still fail; candidate not accepted")
        shutil.copy2(scripts / "validate_windows_runtime.py", runtime)
        manifest = json.loads((runtime / "poc.json").read_text(encoding="utf-8"))
        manifest["validation_script_sha256"] = digest(runtime / "validate_windows_runtime.py")
        manifest["candidate_process_encoding"] = {
            "ansi_codepage": 65001,
            "source_python_sha256": SOURCE_EXE_SHA256,
            "patched_python_sha256": report["patched_python_sha256"],
        }
        (runtime / "poc.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print("Running all scientific checks with process UTF-8...")
        run([runtime / "validate_windows_runtime.py", "--report", output / "before.json"])
        moved = output / "中文 relocation" / "runtime"
        moved.parent.mkdir()
        runtime.rename(moved)
        python = moved / "python/python.exe"
        print("Repeating all checks after Chinese/space path relocation...")
        run([moved / "validate_windows_runtime.py", "--report", output / "after.json"])
        report["status"] = "passed"
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    finally:
        report["source_python_still_matches"] = digest(original_python) == SOURCE_EXE_SHA256
        if not report["source_python_still_matches"]:
            report["status"] = "failed"
        (output / "utf8-probe.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"{report['status']}: {output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
