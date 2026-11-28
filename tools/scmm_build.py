"""Copy canonical workbench Markdown into the installed package."""

from pathlib import Path
from shutil import rmtree

from setuptools.command.build_py import build_py


class BuildWorkbench(build_py):
    def run(self):
        root = Path(__file__).resolve().parents[1]
        build_package = Path(self.build_lib).resolve() / "scMM"
        if build_package == root / "scMM":
            raise ValueError("Build workbench resources outside the source package")
        destination = build_package / "resources/workbench_docs"
        if build_package.is_dir():
            rmtree(build_package)
        super().run()
        files = [
            *(root / name for name in ("README.md", "AGENTS.md", "CHANGELOG.md")),
            *(root / "docs").glob("*.md"),
            *(root / "docs/appendix").glob("*.md"),
            root / "docs/validation/README.md",
        ]
        for source in files:
            target = destination / source.relative_to(root)
            self.mkpath(str(target.parent))
            self.copy_file(str(source), str(target))
