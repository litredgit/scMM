"""Redaction and historical/build coverage of the public-source guard."""

import io
import json
import secrets
import subprocess
import zipfile

from scripts.check_sensitive import archive_findings, current_files, findings, history, main


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)


def repository(root):
    git(root, "init", "-q")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "user.email", "synthetic@example.invalid")


def test_secret_findings_are_redacted_and_notebook_outputs_flagged():
    assert findings(b"SQLite format 3\x00", "unknown.dat")[0]["kind"] == "database_file"
    token = "gh" + "p_" + secrets.token_hex(20)
    result = findings(token.encode(), "example.txt")
    assert result[0]["kind"] == "github_token"
    assert token not in json.dumps(result)
    assert "literal_secret" in {
        x["kind"] for x in findings(json.dumps({"password": token}).encode(), "config.json")
    }
    notebook = {"cells": [{"cell_type": "code", "execution_count": 1, "outputs": ["result"]}]}
    assert findings(json.dumps(notebook).encode(), "example.ipynb")[0]["kind"] == "notebook_output"


def test_archive_contents_checked_without_extracting(tmp_path):
    buffer = io.BytesIO()
    token = "gh" + "p_" + secrets.token_hex(20)
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("package/code.txt", token)
    result = archive_findings(buffer.getvalue(), "package.whl")
    assert result[0]["kind"] == "github_token"
    assert not (tmp_path / "package").exists()
    assert token not in json.dumps(result)


def test_deleted_credentials_remain_in_history_and_check_fails(tmp_path, capsys):
    repository(tmp_path)
    token = "gh" + "p_" + secrets.token_hex(20)
    file = tmp_path / "old.txt"
    file.write_text(token)
    git(tmp_path, "add", "old.txt")
    git(tmp_path, "commit", "-qm", "synthetic old version")
    file.unlink()
    git(tmp_path, "commit", "-qam", "remove synthetic old version")
    assert current_files(tmp_path)["findings"] == []
    assert history(tmp_path)["counts"]["github_token"] == 1
    assert main(["--root", str(tmp_path), "--history"]) == 1
    assert token not in capsys.readouterr().out


def test_ignored_build_files_are_checked(tmp_path):
    repository(tmp_path)
    (tmp_path / ".gitignore").write_text("dist/\n")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.txt").write_text("gh" + "p_" + secrets.token_hex(20))
    assert current_files(tmp_path)["counts"]["github_token"] == 1
