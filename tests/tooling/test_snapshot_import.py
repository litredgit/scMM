import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.import_upstream_snapshot import import_snapshot


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


@pytest.fixture
def project(tmp_path):
    git(tmp_path, "init", "-b", "develop")
    git(tmp_path, "config", "user.name", "Snapshot test")
    git(tmp_path, "config", "user.email", "snapshot@example.invalid")
    (tmp_path / "README.md").write_text("maintained code\n")
    (tmp_path / ".gitignore").write_text("*.pdf\n")
    git(tmp_path, "add", "README.md", ".gitignore")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def package(path, value):
    (path / "file").mkdir(parents=True)
    (path / "__init__.py").write_text("")
    (path / "file" / "data.py").write_text(value)


def test_sequential_snapshots_normalize_paths_preserve_bytes_and_main_index(project):
    first = project / "first"
    package(first, "old\n")
    (first / "obsolete.py").write_text("old only\n")
    (first / "__pycache__").mkdir()
    (first / "__pycache__" / "data.pyc").write_bytes(b"cache")
    before_head = git(project, "rev-parse", "HEAD")
    before_index = (project / ".git" / "index").read_bytes()
    a = import_snapshot(project, Path("first"), claimed_base="reported-base")
    second = project / "second"
    package(second / "scMM", "new\n")
    document = b"%PDF-1.4 binary snapshot\x00\xff"
    (second / "guide.pdf").write_bytes(document)
    b = import_snapshot(project, second)
    repository = project / ".upstream-snapshots.git"
    assert git(repository, "rev-parse", "snapshots^").strip().decode() == a["commit"]
    assert git(repository, "show", "snapshots:scMM/file/data.py") == b"new\n"
    assert git(repository, "show", "snapshot/first:scMM/file/data.py") == b"old\n"
    assert git(repository, "show", "snapshots:guide.pdf") == document
    tree = git(repository, "ls-tree", "-r", "--name-only", "snapshots").decode()
    assert "obsolete.py" not in tree and "__pycache__" not in tree
    metadata = json.loads(git(repository, "show", "snapshots:.snapshot.json"))
    assert metadata["files"]["guide.pdf"]["sha256"] == hashlib.sha256(document).hexdigest()
    assert git(project, "rev-parse", "vendor/snapshots").strip().decode() == b["commit"]
    assert git(project, "rev-parse", "HEAD") == before_head
    assert (project / ".git" / "index").read_bytes() == before_index
    assert git(project, "status", "--porcelain") == b""
    assert (first / "file" / "data.py").read_bytes() == b"old\n"
    assert import_snapshot(project, second)["commit"] == b["commit"]
    assert git(repository, "rev-list", "--count", "snapshots").strip() == b"2"


def test_existing_tag_is_immutable(project):
    source = project / "drop"
    package(source, "first")
    original = import_snapshot(project, source)
    (source / "file" / "data.py").write_text("changed")
    with pytest.raises(ValueError, match="different content"):
        import_snapshot(project, source)
    assert git(project, "rev-parse", "vendor/snapshots").decode().strip() == original["commit"]
    updated = import_snapshot(project, source, name="drop-revised")
    assert updated["commit"] != original["commit"]


def test_rejects_source_symlinks_and_tracked_directories(project):
    source = project / "drop"
    package(source, "data")
    (source / "external").symlink_to(project / "README.md")
    with pytest.raises(ValueError, match="regular"):
        import_snapshot(project, source)
    (source / "external").unlink()
    git(project, "add", "drop")
    with pytest.raises(ValueError, match="tracked"):
        import_snapshot(project, source)


def test_unsupported_source_does_not_create_repository(project):
    source = project / "unknown"
    source.mkdir()
    with pytest.raises(ValueError, match="Expected"):
        import_snapshot(project, source)
    assert not (project / ".upstream-snapshots.git").exists()
