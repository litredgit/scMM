"""PoC input integrity, platform selection and fail-closed assembly boundaries."""

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile

import pytest

from scripts.build_windows import (
    assemble,
    create_kit,
    download_verified,
    extract_runtime,
    windows_wheels,
)


def wheel(name, tag):
    return {
        "url": f"https://example.com/{name}-1.0-{tag}.whl",
        "hashes": {"sha256": "a" * 64},
    }


def test_windows_markers_and_abi_selection_do_not_use_host_platform():
    config = {
        "python": "3.12.13",
        "platform": "win_amd64",
        "required_packages": ["native", "windows"],
    }
    lock = {
        "packages": [
            {
                "name": "native",
                "version": "1.0",
                "wheels": [
                    wheel("native", "cp312-cp312-manylinux_2_17_x86_64"),
                    wheel("native", "cp313-cp313-win_amd64"),
                    wheel("native", "cp39-abi3-win_amd64"),
                    wheel("native", "cp312-cp312-win_amd64"),
                ],
            },
            {
                "name": "windows",
                "version": "1.0",
                "marker": "sys_platform == 'win32' and python_full_version >= '3.12'",
                "wheels": [wheel("windows", "py3-none-any")],
            },
            {"name": "linux", "version": "1.0", "marker": "sys_platform == 'linux'", "wheels": []},
        ]
    }
    selected = windows_wheels(lock, config)
    assert [item["name"] for item in selected] == ["native", "windows"]
    assert selected[0]["filename"] == "native-1.0-cp312-cp312-win_amd64.whl"
    lock["packages"][0]["wheels"] = [wheel("native", "cp313-cp313-win_amd64")]
    with pytest.raises(ValueError, match="No locked Windows"):
        windows_wheels(lock, config)


def test_missing_required_package_and_ambiguous_versions_fail():
    config = {"python": "3.12.13", "platform": "win_amd64", "required_packages": ["tzdata"]}
    with pytest.raises(ValueError, match="Required runtime packages missing"):
        windows_wheels({"packages": []}, config)
    package = {"name": "tzdata", "version": "1.0", "wheels": [wheel("tzdata", "py3-none-any")]}
    with pytest.raises(ValueError, match="Ambiguous active"):
        windows_wheels({"packages": [package, package]}, config)


def test_corrupt_download_never_publishes_and_cached_corruption_is_rejected(tmp_path):
    source = tmp_path / "source.whl"
    source.write_bytes(b"wheel bytes")
    target = tmp_path / "download.whl"
    with pytest.raises(ValueError, match="Downloaded input checksum mismatch"):
        download_verified(source.as_uri(), "0" * 64, target)
    assert not target.exists() and not target.with_suffix(".whl.partial").exists()
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    download_verified(source.as_uri(), expected, target)
    assert target.read_bytes() == source.read_bytes()
    target.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="Existing input checksum mismatch"):
        download_verified(source.as_uri(), expected, target)


@pytest.mark.parametrize(
    "name,link",
    [
        ("../escaped", False),
        ("python/../../escaped", False),
        ("python/C:escape", False),
        ("python/link", True),
    ],
)
def test_unsafe_runtime_archive_does_not_escape_or_extract_partial_files(tmp_path, name, link):
    archive = tmp_path / "python.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        safe = tarfile.TarInfo("python/safe")
        safe.size = 2
        stream.addfile(safe, io.BytesIO(b"ok"))
        member = tarfile.TarInfo(name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = "../../escaped"
        stream.addfile(member)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Unsafe runtime archive member"):
        extract_runtime(archive, output)
    assert not output.exists()


def test_non_windows_assembly_never_creates_output(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ValueError, match="requires native Windows"):
        assemble(tmp_path, tmp_path / "scmm.whl", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_wrong_platform_smoke_writes_failure_evidence_and_never_overwrites(tmp_path, monkeypatch):
    from scripts.validate_windows_runtime import main

    monkeypatch.setattr(sys, "platform", "linux")
    report = tmp_path / "report.json"
    assert main(["--report", str(report)]) == 1
    evidence = report.read_bytes()
    assert json.loads(evidence)["status"] == "failed"
    assert not json.loads(evidence)["native_windows_x64"]
    with pytest.raises(SystemExit):
        main(["--report", str(report)])
    assert report.read_bytes() == evidence


def test_offline_kit_contains_only_manifested_inputs_and_rejects_corruption(tmp_path, monkeypatch):
    from scripts import build_windows

    root = tmp_path / "repository"
    inputs = tmp_path / "inputs"
    (inputs / "wheelhouse").mkdir(parents=True)
    packaging = inputs / "wheelhouse/packaging-26.3-py3-none-any.whl"
    packaging.write_bytes(b"synthetic pure Python wheel")
    python = inputs / "python.tar.gz"
    python.write_bytes(b"synthetic private Python archive")
    uv = tmp_path / "uv.zip"
    with zipfile.ZipFile(uv, "w") as archive:
        archive.writestr("uv.exe", b"synthetic Windows executable; never executed")
    tools = {"uv": {"version": "0.12.3", "sha256": build_windows.digest(uv)}}
    manifest = {
        "runtime": {"uv": "0.12.3", "sha256": build_windows.digest(python)},
        "wheels": [
            {
                "name": "packaging",
                "filename": packaging.name,
                "sha256": build_windows.digest(packaging),
            }
        ],
    }
    (inputs / "inputs.json").write_text(json.dumps(manifest))
    for name in ("pylock.windows.toml", "requirements.txt"):
        (inputs / name).write_text("synthetic lock export")
    for name in (
        "scripts/build_windows.py",
        "scripts/validate_windows_runtime.py",
        "scripts/probe_windows_utf8.py",
        "packaging/windows/runtime.json",
        "packaging/windows/validate-runtime.ps1",
        "packaging/windows/run-win01.ps1",
        "packaging/windows/WIN01-README.txt",
        "packaging/windows/licenses/uv-LICENSE-MIT.txt",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic input")
    (root / "packaging/windows/build-tools.json").write_text(json.dumps(tools))
    monkeypatch.setattr(build_windows, "ROOT", root)
    scmm = tmp_path / "scmm-0.2.0-py3-none-any.whl"
    scmm.write_bytes(b"synthetic scMM wheel")
    output = tmp_path / "kit.zip"
    create_kit(inputs, scmm, uv, output)
    with zipfile.ZipFile(output) as archive:
        kit = json.loads(archive.read("kit.json"))
        assert set(archive.namelist()) == {item["path"] for item in kit["files"]} | {"kit.json"}
        for item in kit["files"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
        assert kit["packaging_wheel"].endswith(packaging.name)
        assert archive.read("tools/uv.exe").startswith(b"synthetic Windows")
    assert output.with_suffix(".zip.sha256").read_text().split()[0] == build_windows.digest(output)
    with pytest.raises(ValueError, match="already exists"):
        create_kit(inputs, scmm, uv, output)
    packaging.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="Kit wheel checksum/path mismatch"):
        create_kit(inputs, scmm, uv, tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()


def test_openms_path_diagnosis_keeps_unicode_failure_separate_from_numerical_baseline(
    tmp_path, monkeypatch
):
    import pyopenms

    from scripts.diagnose_windows_openms import probes

    original = pyopenms.MzMLFile

    class RejectUnicodeStore:
        def __init__(self):
            self.reader = original()

        def __getattr__(self, name):
            return getattr(self.reader, name)

        def store(self, filename, experiment):
            path = filename.decode("utf-8") if isinstance(filename, bytes) else filename
            if not path.isascii():
                raise RuntimeError("synthetic native Unicode path failure")
            self.reader.store(filename, experiment)

    monkeypatch.setattr(pyopenms, "MzMLFile", RejectUnicodeStore)
    result = probes(tmp_path)
    assert result["ascii/str/store"]["status"] == "passed"
    assert result["unicode_filename/str/store"]["status"] == "failed"
    assert "synthetic native Unicode" in result["unicode_filename/str/store"]["error"]
    assert result["unicode_filename/str/load_python_created_file"]["status"] == "passed"
    assert result["unicode_both/python_io_openms_buffer"]["status"] == "passed"
    assert result["unicode_parent/utf8_bytes/store"]["status"] == "failed"


def test_utf8_manifest_preserves_identity_security_long_paths_and_languages():
    from scripts.probe_windows_utf8 import ASMV1, ASMV3, UTF8_SETTINGS, utf8_manifest

    original = b"""<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
      <assemblyIdentity name="Python" version="3.12.13.0" type="win32"/>
      <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges></security></trustInfo>
      <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
        <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      </windowsSettings></application>
    </assembly>"""
    patched = utf8_manifest(original + b"\0")
    root = ET.fromstring(patched)
    assert root.find(f"{{{ASMV1}}}assemblyIdentity").get("version") == "3.12.13.0"
    assert root.find(f".//{{{ASMV3}}}requestedExecutionLevel").attrib == {
        "level": "asInvoker",
        "uiAccess": "false",
    }
    assert (
        root.find(".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}longPathAware").text
        == "true"
    )
    assert root.find(f".//{{{UTF8_SETTINGS}}}activeCodePage").text == "UTF-8"
    assert (
        len(ET.fromstring(utf8_manifest(patched)).findall(f".//{{{UTF8_SETTINGS}}}activeCodePage"))
        == 1
    )
    with pytest.raises(ValueError, match="Unexpected original"):
        utf8_manifest(b"<unrelated/>")


def test_utf8_probe_rejects_signed_executable_without_modifying_it(tmp_path):
    import struct

    from scripts.probe_windows_utf8 import reject_signed_executable

    data = bytearray(512)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\0\0"
    optional = 64 + 24
    struct.pack_into("<H", data, optional, 0x20B)
    path = tmp_path / "python.exe"
    path.write_bytes(data)
    reject_signed_executable(path)
    struct.pack_into("<II", data, optional + 112 + 4 * 8, 1024, 128)
    path.write_bytes(data)
    with pytest.raises(ValueError, match="signed executable"):
        reject_signed_executable(path)
    assert path.read_bytes() == data


def test_source_binding_is_explicit_and_reaches_child_interpreters(tmp_path):
    from scripts.scmm_windows import binding_text

    repository = tmp_path / "中文 repo's folder"
    repository.mkdir()
    (repository / "scmm_source_marker.py").write_text("TOKEN = 'source-checkout'\n")
    site = tmp_path / "site-packages"
    site.mkdir()
    (site / "scmm_source.pth").write_text(binding_text(repository), encoding="utf-8")
    worker = tmp_path / "worker state"
    worker.mkdir()
    code = f"import site; site.addsitedir({str(site)!r}); import scmm_source_marker; print(scmm_source_marker.TOKEN)"
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=worker, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "source-checkout"


def test_delivery_rejects_a_wheel_that_differs_from_repository_source(tmp_path, monkeypatch):
    from scripts import build_windows

    root = tmp_path / "repository"
    (root / "scMM/file").mkdir(parents=True)
    (root / "scMM/file/io.py").write_text("VALUE = 'current source'\n")
    for name in (
        "scripts/scmm_windows.py",
        "scripts/validate_windows_runtime.py",
        "scripts/validate_windows_delivery.py",
        "pyproject.toml",
        "uv.lock",
    ):
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("synthetic input\n")
    monkeypatch.setattr(build_windows, "ROOT", root)
    wheel = tmp_path / "scmm-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("scMM/file/io.py", "VALUE = 'stale wheel'\n")
    with pytest.raises(ValueError, match="Source and wheel differ"):
        build_windows.create_delivery(wheel, tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.write(root / "scMM/file/io.py", "scMM/file/io.py")
    build_windows.create_delivery(wheel, tmp_path / "matching.zip")
    with zipfile.ZipFile(tmp_path / "matching.zip") as archive:
        manifest = json.loads(archive.read("delivery.json"))
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("scMM/stale.py", "unexpected stale code\n")
    with pytest.raises(ValueError, match="inventories differ"):
        build_windows.create_delivery(wheel, tmp_path / "extra-code.zip")
    assert not (tmp_path / "extra-code.zip").exists()


def test_windows_copy_preflight_checks_relocation_before_writing(tmp_path):
    from pathlib import PureWindowsPath

    from scripts.scmm_windows import check_copy_paths

    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "module.py").write_text("pass\n")
    short = PureWindowsPath(r"C:\Temp\sd-1018-123000\w")
    assert check_copy_paths(seed, [short]) < 100
    deep = PureWindowsPath("C:/" + "a" * 245)
    with pytest.raises(ValueError, match="Windows path too long"):
        check_copy_paths(seed, [short, deep])
    assert list(tmp_path.iterdir()) == [seed]


def test_windows_copy_preflight_counts_utf16_and_directory_reserve(tmp_path):
    from pathlib import PureWindowsPath

    from scripts.scmm_windows import check_copy_paths

    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "x").write_text("data")
    # Supplementary Unicode characters occupy two UTF-16 units each.
    destination = PureWindowsPath("C:/" + "\U0001f600" * 122)
    assert len(str(destination)) < 247
    assert check_copy_paths(seed, [destination]) == 249
    with pytest.raises(ValueError, match="limit 247"):
        check_copy_paths(seed, [PureWindowsPath("C:/" + "a" * 245)])


def test_delivery_default_output_uses_temp_instead_of_seed_parent(tmp_path, monkeypatch):
    from scripts import validate_windows_delivery

    monkeypatch.setattr(validate_windows_delivery.tempfile, "gettempdir", lambda: str(tmp_path))
    output = validate_windows_delivery.default_output()
    assert output.parent == tmp_path
    assert output.name.startswith("sd-")
    assert len(output.name) == 14
