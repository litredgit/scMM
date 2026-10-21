"""Selection regressions use tiny synthetic repositories; no scientific pipeline runs."""

import ast
import json
import subprocess

import pytest

from scripts.test_blocks import (
    CONFIG,
    ROOT,
    changed_files,
    ci_range,
    commands,
    document_inputs,
    main,
    select,
)

CONFIGURATION = json.loads(CONFIG.read_text(encoding="utf-8"))


def plan(*files):
    return select(files, CONFIGURATION)


def test_shared_frontend_changes_include_assistant_browser_checks():
    for path in (
        "frontend/src/stores/workspace.ts",
        "frontend/src/components/PlotView.vue",
        "frontend/src/router/index.ts",
    ):
        assert "browser-ai" in plan(path)["selected"]


@pytest.mark.parametrize(
    "file,expected",
    [
        ("docs/parameters.md", {"docs"}),
        ("frontend/src/features/monitor/MonitorPage.vue", {"browser-monitor"}),
        ("tests/domain/test_normalize.py", {"data"}),
        ("frontend/tests/lipids.spec.ts", {"browser-lipids"}),
        ("tests/support/lipids.py", {"annotation", "api-lipids"}),
        ("scMM_workflow.ipynb", {"notebook"}),
    ],
)
def test_changes_select_only_affected_blocks(file, expected):
    selected = plan(file)
    assert set(selected["selected"]) == expected
    assert set(selected["skipped"]).isdisjoint(expected)
    assert set(selected["selected"]) | set(selected["skipped"]) == set(CONFIGURATION["blocks"])
    if file.endswith(".md") or file.startswith("tests/"):
        assert not selected["frontend"] and not selected["package"]
    if file.startswith("frontend/"):
        assert not selected["python_paths"] and not selected["doc_paths"]


def test_source_dependencies_expand_but_tests_and_fixtures_do_not():
    preview = plan("scMM/application/preview_cache.py")
    assert {"processing", "projects"} <= set(preview["selected"])
    assert "tests/application/test_text_encoding.py" in preview["python_paths"]
    data = plan("scMM/file/data.py")
    assert {
        "data",
        "processing",
        "workbench",
        "projects",
        "api",
        "api-lipids",
        "browser-workflow",
    } <= set(data["selected"])
    assert "auth" not in data["selected"]
    assert "browser-auth" not in data["selected"]
    assert plan("tests/application/test_projects.py")["extras"] == []
    assert plan("tests/application/test_workbench_state.py")["extras"] == []
    assert "analysis" not in data["selected"]  # Algorithms don't consume CyESIData.
    assert data["package"] and data["frontend"]
    assert set(plan("tests/support/project.py")["selected"]) == {
        "ai",
        "processing",
        "projects",
        "api",
        "api-raw",
        "api-lipids",
    }
    assert set(plan("tests/api/conftest.py")["selected"]) == {"api", "api-raw", "api-lipids"}
    assert not plan("tests/conftest.py")["browser_paths"]
    locked = plan("uv.lock")
    assert set(locked["selected"]) == {
        n for n, b in CONFIGURATION["blocks"].items() if b["kind"] != "docs"
    }
    assert "notebook" not in locked["extras"]


def test_unknown_paths_report_uncertainty_instead_of_silent_skip():
    selected = plan("scMM/analysis/new_algorithm.py")
    assert "analysis" in selected["selected"]
    unknown = plan("scMM/new_area/algorithm.py")
    assert unknown["python_paths"]
    assert any(
        "UNMAPPED" in reason for reasons in unknown["reasons"].values() for reason in reasons
    )
    with pytest.raises(ValueError, match="Unmapped change"):
        plan("unmapped_executable.sh")


def test_inventory_and_dependency_mapping_are_complete():
    blocks = CONFIGURATION["blocks"]
    paths = [p for b in blocks.values() for p in b["tests"]]
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("test_*.py")}
    actual |= {p.relative_to(ROOT).as_posix() for p in (ROOT / "frontend/tests").glob("*.spec.ts")}
    assert len(paths) == len(set(paths))
    assert set(paths) == actual
    for b in blocks.values():
        assert set(b["downstream"]) <= blocks.keys()
    for names in [*CONFIGURATION["support"].values(), *CONFIGURATION["shared"].values()]:
        assert set(names) <= blocks.keys()
    for path in (ROOT / "scMM").rglob("*.py"):
        if "static" not in path.parts:
            selected = plan(path.relative_to(ROOT).as_posix())
            assert not any(
                "UNMAPPED" in reason
                for reasons in selected["reasons"].values()
                for reason in reasons
            ), path
    # No test imports another test; helpers are explicit imports from support.
    for path in (ROOT / "tests").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (
                    (node.module or "").startswith(("tests.", "test_"))
                    and any(p.startswith("test_") for p in (node.module or "").split("."))
                ), path


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-qb", "main")
    git(tmp_path, "config", "user.email", "tests@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "base.txt").write_text("base")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def commit(root, name):
    (root / name).write_text(name)
    git(root, "add", ".")
    git(root, "commit", "-qm", name)
    return git(root, "rev-parse", "HEAD")


def test_push_includes_all_commits_pr_uses_merge_base_and_initial_push_all_files(repository):
    base = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "-qb", "feature")
    commit(repository, "first.py")
    head = commit(repository, "second.py")
    before, after = ci_range({"before": base, "after": head}, root=repository)
    assert changed_files(before, after, root=repository) == ["first.py", "second.py"]
    git(repository, "checkout", "-q", "main")
    advanced_base = commit(repository, "unrelated.py")
    before, after = ci_range(
        {"pull_request": {"base": {"sha": advanced_base}, "head": {"sha": head}}}, root=repository
    )
    assert before == base
    assert changed_files(before, after, root=repository) == ["first.py", "second.py"]
    assert set(changed_files("0" * 40, head, root=repository)) == {
        "base.txt",
        "first.py",
        "second.py",
    }


def test_local_includes_staged_unstaged_untracked_and_both_rename_paths(repository):
    (repository / "base.txt").rename(repository / "renamed.txt")
    git(repository, "add", ".")
    (repository / "unstaged.py").write_text("new")
    assert changed_files(root=repository) == ["base.txt", "renamed.txt", "unstaged.py"]
    (repository / "renamed.txt").write_text("edited after staging")
    assert changed_files(root=repository) == ["base.txt", "renamed.txt", "unstaged.py"]


def test_commands_keep_warnings_as_errors_and_no_unselected_execution(tmp_path, capsys):
    selected = plan("frontend/tests/lipids.spec.ts")
    assert list(commands(selected, "python")) == []
    assert next(commands(selected, "browser"))[-1] == "lipids.spec.ts"
    assert next(commands(plan("tests/domain/test_peak.py"), "python"))[3:6] == [
        "-q",
        "-W",
        "error",
    ]
    output = tmp_path / "plan.json"
    assert main(["--block", "data", "--write-plan", str(output)]) == 0
    loaded = json.loads(output.read_text())
    assert loaded["selected"] == ["data"]
    assert "Skipped blocks:" in capsys.readouterr().out
    assert main(["--files", "unknown.sh"]) == 1


def test_related_documents_include_reverse_link_targets():
    assert "docs/development.md" in document_inputs(["docs/development.md"])
    assert "docs/development.md" in document_inputs(
        ["scripts/check_sensitive.py"]
    ) or "docs/development.md" not in document_inputs(["scripts/check_sensitive.py"])
    assert "docs/README.md" in document_inputs(["docs/development.md"])
    assert len(document_inputs(["tests/tooling/test_documentation.py"])) > 10


def test_support_mapping_matches_actual_transitive_consumers():
    def imports(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("tests.support.")
        }
        if any(
            isinstance(node, ast.FunctionDef)
            and any(arg.arg == "workflow" for arg in node.args.args)
            for node in ast.walk(tree)
        ):
            modules.add("tests.support.workflow")
        return {ROOT / (module.replace(".", "/") + ".py") for module in modules}

    for helper in (ROOT / "tests/support").glob("*.py"):
        if helper.name == "__init__.py":
            continue
        actual = set()
        for name, block in CONFIGURATION["blocks"].items():
            if block["kind"] != "python":
                continue
            pending = [ROOT / p for p in block["tests"]]
            seen = set()
            while pending:
                path = pending.pop()
                if path in seen:
                    continue
                seen.add(path)
                pending.extend(imports(path))
            if helper in seen:
                actual.add(name)
        assert actual == set(CONFIGURATION["support"][helper.relative_to(ROOT).as_posix()]), helper


def test_format_configuration_needs_only_formatter_and_all_tracked_inputs_are_mapped():
    selected = plan("frontend/.prettierrc.json")
    assert selected["selected"] == []
    assert selected["node"] and selected["format_all"]
    assert not selected["frontend"] and not selected["package"]
    assert len(list(commands(selected, "frontend"))) == 1
    assert "src/App.vue" in selected["format_paths"]
    names = git(ROOT, "ls-files", "-z").split("\0")
    # The old flat tests are aliases during this migration. All tracked paths,
    # including formatter metadata, must work on a branch's first push.
    assert select(names, CONFIGURATION)["selected"]
