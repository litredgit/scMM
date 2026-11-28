"""Page paths shared by the SPA host and presence input validation."""

from typing import Literal, get_args

PageRoute = Literal[
    "/projects",
    "/samples",
    "/parameters",
    "/results",
    "/raw",
    "/extraction",
    "/preprocess",
    "/ions",
    "/analysis",
    "/cell-extraction",
    "/annotation",
    "/annotation/evidence",
    "/data-check",
    "/data-editor",
    "/statistics",
    "/admin/monitor",
    "/account",
]
SPA_ROUTES = ("/", *get_args(PageRoute))
