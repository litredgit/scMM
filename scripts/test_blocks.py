#!/usr/bin/env python3
"""Select affected test blocks from tests/blocks.json; shared by local checks and CI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tests/blocks.json"


def git(*args, root=ROOT):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().rstrip("\n")


def changed_files(base=None, head=None, *, root=ROOT):
    """PR: merge base to head; push: before to after; local: HEAD plus untracked."""
    if base and set(base) == {"0"}:
        # First branch push: all files are new to that branch.
        return sorted(
            filter(
                None, git("ls-tree", "-rz", "--name-only", head or "HEAD", root=root).split("\0")
            )
        )
    args = ["diff", "--name-only", "--no-renames", "-z", base or "HEAD"]
    if head:
        args.append(head)
    names = git(*args, root=root).split("\0")
    if head is None:
        names += git("ls-files", "--others", "--exclude-standard", "-z", root=root).split("\0")
    return sorted(set(filter(None, names)))


def ci_range(event, *, root=ROOT):
    if "pull_request" in event:
        head = event["pull_request"]["head"]["sha"]
        base = git("merge-base", event["pull_request"]["base"]["sha"], head, root=root)
        return base, head
    if "before" in event and "after" in event:
        return event["before"], event["after"]
    raise ValueError("CI event has no PR or push comparison range")


def matches(path, patterns):
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def select(files, config, *, explicit=(), all_blocks=False):
    blocks = config["blocks"]
    reasons = {}
    files = sorted(set(filter(None, files)))

    def add(name, reason, *, propagate=False):
        if name not in blocks:
            raise ValueError(f"Unknown block: {name}")
        reasons.setdefault(name, set()).add(reason)
        if propagate:
            pending, visited = [name], {name}
            while pending:
                parent = pending.pop(0)
                for dependent in blocks[parent]["downstream"]:
                    if dependent not in visited:
                        visited.add(dependent)
                        reasons.setdefault(dependent, set()).add(f"{reason} → depends on {parent}")
                        pending.append(dependent)

    for name in blocks if all_blocks else explicit:
        add(name, "explicit --all" if all_blocks else "explicit --block")
    for path in files:
        # Moving a test must select both its former and current owner. The basename
        # alias also handles the former flat layout without keeping duplicate rules.
        owners = [
            n
            for n, b in blocks.items()
            if path in b["tests"]
            or (
                path.startswith("tests/test_")
                and Path(path).name in map(lambda t: Path(t).name, b["tests"])
            )
        ]
        if owners:
            for name in owners:
                add(name, f"{path}: test changed")
            continue
        if path.startswith("tests/") and Path(path).name == "__init__.py":
            add("tooling", f"{path}: test package layout")
            continue
        if path in config["support"]:
            for name in config["support"][path]:
                add(name, f"{path}: shared fixture consumer")
            continue
        if path.endswith(".md") or path.startswith("docs/"):
            add("docs", f"{path}: documentation/link target")
            continue
        if matches(path, config["format_sources"]):
            continue
        direct = [n for n, b in blocks.items() if matches(path, b["sources"])]
        for pattern, names in config["shared"].items():
            if matches(path, [pattern]):
                for name in names:
                    add(name, f"{path}: shared contract/dependency", propagate=True)
        if direct:
            for name in direct:
                add(name, f"{path}: source mapping", propagate=True)
        elif (
            not any(matches(path, [p]) for p in config["shared"]) and path not in config["support"]
        ):
            # Fail visibly for a new executable/test location. Maintainers must map
            # it instead of silently reporting zero impact or defaulting to all.
            fallback = next(
                (names for prefix, names in config["fallbacks"].items() if path.startswith(prefix)),
                None,
            )
            if fallback:
                for name in fallback:
                    add(
                        name,
                        f"{path}: UNMAPPED within known area; conservative area selection",
                        propagate=True,
                    )
            elif path == "MANIFEST.in" or path.startswith("LICENSE"):
                add("tooling", f"{path}: packaging metadata")
            elif path in {"tests/test_user_todo.py", "tests/web_auth_support.py"}:
                # Deleted mixed tests/helpers: new owners are selected from the
                # added files. This alias is only needed for the migration diff.
                for name in (
                    "processing",
                    "workbench",
                    "projects",
                    "analysis",
                    "plotting",
                    "api",
                    "auth",
                    "monitor",
                    "spectra",
                ):
                    add(name, f"{path}: former mixed tests/helper")
            else:
                raise ValueError(
                    f"Unmapped change: {path}; add an explicit rule in tests/blocks.json"
                )

    selected = [n for n in blocks if n in reasons]

    def paths(kind):
        return sorted(
            {p for n in selected if blocks[n]["kind"] == kind for p in blocks[n]["tests"]}
        )

    package = all_blocks or any(
        matches(p, config["package_sources"]) and not p.endswith(".md") for p in files
    )
    browsers = paths("browser")
    frontend = (
        all_blocks
        or bool(browsers)
        or any(matches(p, config["frontend_sources"]) and not p.endswith(".md") for p in files)
    )
    python_paths = paths("python")
    format_all = all_blocks or any(
        matches(p, [*config["format_sources"], "frontend/package*.json"]) for p in files
    )
    format_inputs = (
        git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "frontend").split("\0")
        if format_all
        else files
    )
    format_paths = sorted(
        p.removeprefix("frontend/")
        for p in set(format_inputs)
        if p.startswith("frontend/")
        and p.endswith((".ts", ".vue", ".css", ".html", ".json", ".mjs"))
        and (ROOT / p).is_file()
    )
    return {
        "files": files,
        "selected": selected,
        "reasons": {n: sorted(reasons[n]) for n in selected},
        "skipped": [n for n in blocks if n not in reasons],
        "python_paths": python_paths,
        "doc_paths": paths("docs"),
        "browser_paths": browsers,
        "python": bool(python_paths),
        "docs": bool(paths("docs")),
        "frontend": frontend or package,
        "node": frontend or package or bool(format_paths),
        "format_all": format_all,
        "package": package,
        "extras": sorted(
            {e for n in selected if blocks[n]["kind"] == "python" for e in blocks[n]["extras"]}
        ),
        "browser_extras": sorted(
            {e for n in selected if blocks[n]["kind"] == "browser" for e in blocks[n]["extras"]}
        ),
        "lint_paths": sorted(p for p in files if p.endswith(".py") and (ROOT / p).is_file()),
        "format_paths": format_paths,
    }


def document_inputs(files):
    """Changed Markdown plus guides linking to changed/deleted files or anchors."""
    guides = [*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")]
    changed = set(files)
    chosen = set(p for p in guides if p.relative_to(ROOT).as_posix() in changed)
    # A changed target can invalidate a link in an unchanged guide.
    import re
    from urllib.parse import unquote

    for guide in guides:
        for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", guide.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            local = unquote(target.split("#", 1)[0])
            resolved = (guide.parent / local).resolve() if local else guide.resolve()
            if resolved.is_relative_to(ROOT) and resolved.relative_to(ROOT).as_posix() in changed:
                chosen.add(guide)
    # Changing the checker itself changes what is accepted in every guide.
    if (
        not files
        or "tests/tooling/test_documentation.py" in changed
        or "tests/test_documentation.py" in changed
    ):
        chosen.update(guides)
    return sorted(p.relative_to(ROOT).as_posix() for p in chosen)


def commands(plan, phase):
    """Commands are argv lists, never shell interpolation of changed filenames."""
    if phase == "python" and plan["python_paths"]:
        yield [sys.executable, "-m", "pytest", "-q", "-W", "error", *plan["python_paths"]]
    if phase == "docs" and plan["doc_paths"]:
        yield [sys.executable, "-m", "pytest", "-q", "-W", "error", *plan["doc_paths"]]
    if phase == "lint" and plan["lint_paths"]:
        yield [sys.executable, "-m", "ruff", "format", "--check", *plan["lint_paths"]]
        yield [sys.executable, "-m", "ruff", "check", *plan["lint_paths"]]
    if phase == "frontend":
        if plan["format_paths"]:
            yield [
                "npm",
                "--prefix",
                "frontend",
                "exec",
                "--",
                "prettier",
                "--check",
                *[f"frontend/{p}" for p in plan["format_paths"]],
            ]
        if plan["frontend"]:
            yield [
                "npm",
                "--prefix",
                "frontend",
                "run",
                "typecheck" if plan.get("typecheck_only") else "build",
            ]
    if phase == "browser" and plan["browser_paths"]:
        yield [
            "npm",
            "--prefix",
            "frontend",
            "run",
            "test:e2e",
            "--",
            *[Path(p).name for p in plan["browser_paths"]],
        ]
    if phase == "package" and plan["package"]:
        yield ["uv", "build", "--no-sources"]
    if phase == "scan" and plan["files"]:
        yield [sys.executable, "scripts/check_sensitive.py", "--files", *plan["files"]]
    if phase == "artifacts" and plan["frontend"] and not plan.get("typecheck_only"):
        yield [sys.executable, "scripts/check_sensitive.py", "--artifacts-only"]


def lightweight(plan):
    """Automatic CI checks contracts in a clean tree; full plan remains local/manual."""
    plan = dict(plan)
    # Packaging implies a frontend build locally, but automatic CI does not package.
    # Retain typechecking only for actual frontend inputs, using the same mapping.
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    plan["frontend"] = any(matches(p, config["frontend_sources"]) for p in plan["files"])
    plan["node"] = plan["frontend"] or bool(plan["format_paths"])
    plan["python_paths"] = (
        [
            "tests/tooling/test_test_blocks.py",
            "tests/api/test_server_config.py",
        ]
        if plan["python"] or plan["frontend"]
        else []
    )
    plan["python"] = bool(plan["python_paths"])
    plan["extras"] = ["web"] if plan["python_paths"] else []
    plan["browser_paths"] = []
    plan["browser_extras"] = []
    plan["package"] = False
    plan["typecheck_only"] = True
    plan["profile"] = "lightweight"
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--ci-event", type=Path)
    parser.add_argument("--files", nargs="*")
    parser.add_argument("--block", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--lightweight", action="store_true", help="Automatic CI contract smoke profile"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--phase",
        choices=["python", "docs", "lint", "frontend", "browser", "package", "scan", "artifacts"],
    )
    parser.add_argument("--plan", type=Path, help="Read an already calculated plan (CI phases)")
    parser.add_argument("--write-plan", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.plan:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
        else:
            base, head = args.base, args.head
            if args.ci_event:
                base, head = ci_range(json.loads(args.ci_event.read_text(encoding="utf-8")))
                print(f"Comparison: {base} → {head}")
            files = (
                args.files
                if args.files is not None
                else (
                    []
                    if (args.block or args.all) and not (base or head or args.ci_event)
                    else changed_files(base, head)
                )
            )
            plan = select(
                files,
                json.loads(CONFIG.read_text(encoding="utf-8")),
                explicit=args.block,
                all_blocks=args.all,
            )
            documents = document_inputs(files)
            if documents and files and "docs" not in plan["selected"]:
                plan = select(
                    files,
                    json.loads(CONFIG.read_text(encoding="utf-8")),
                    explicit=[*args.block, "docs"],
                    all_blocks=args.all,
                )
                plan["reasons"]["docs"] = ["changed file is a Markdown link target"]
            plan["documents"] = documents
        if args.lightweight:
            plan = lightweight(plan)
        print("Execution profile: " + plan.get("profile", "affected/full"))
        print("Selected blocks:")
        for name in plan["selected"]:
            print(f"  {name}: " + "; ".join(plan["reasons"][name]))
        print("Skipped blocks: " + (", ".join(plan["skipped"]) or "none"))
        if plan["format_all"]:
            print(
                "Frontend formatter/dependency inputs changed: check all frontend formatting inputs."
            )
        if plan["package"]:
            print(
                "Package inputs changed: build distributions; frontend build supplies bundled assets."
            )
        if args.write_plan:
            args.write_plan.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as handle:
                for key in ("python", "docs", "frontend", "package", "node"):
                    handle.write(f"{key}={str(plan[key]).lower()}\n")
        if args.run:
            os.environ["PYTHONUTF8"] = "1"
            os.environ["SCMM_DOCUMENTS"] = json.dumps(plan["documents"])
            for phase in (
                [args.phase]
                if args.phase
                else [
                    "python",
                    "docs",
                    "lint",
                    "scan",
                    "frontend",
                    "browser",
                    "package",
                    "artifacts",
                ]
            ):
                for command in commands(plan, phase):
                    print("Run: " + repr(command), flush=True)
                    subprocess.run(command, cwd=ROOT, check=True)
                    if phase == "frontend" and plan["frontend"] and not plan.get("typecheck_only"):
                        # The shared entry just built these assets; standalone browser
                        # runs otherwise build their own isolated assets in server.py.
                        os.environ.setdefault(
                            "SCMM_TEST_STATIC_ROOT", str(ROOT / "scMM/api/static")
                        )

    except (ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
