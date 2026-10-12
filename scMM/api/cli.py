"""Explicit Vue/FastAPI entry, alongside the retained Panel entry."""

import sys


def main(argv=None):
    from scMM.ui.cli import main as ui_main

    return ui_main(sys.argv[1:] if argv is None else argv, frontend="vue", prog="scmm-web")
