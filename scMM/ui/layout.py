"""Responsive presentation only; never changes figure coordinates or data."""
# ruff: noqa: RUF001

from typing import ClassVar

import panel as pn
import param


def flow(*objects, **params):
    """Wrap compact controls instead of stretching buttons or overflowing rows."""
    return pn.FlexBox(
        *objects,
        flex_wrap="wrap",
        align_items="center",
        gap="8px",
        sizing_mode="stretch_width",
        **params,
    )


def form(*objects, **params):
    return pn.FlexBox(
        *objects,
        flex_wrap="wrap",
        align_items="flex-start",
        gap="8px",
        sizing_mode="stretch_width",
        **params,
    )


BUTTON_STYLE = """
.bk-btn { border-radius: 6px; padding: 7px 12px; font-weight: 500;
  white-space: normal; overflow-wrap: anywhere; line-height: 1.4; }
.bk-btn-primary { background: #2563eb !important; color: white !important; }
.bk-btn-success { background: #15803d !important; color: white !important; }
.bk-btn-default { background: white !important; color: #475569 !important;
  border: 1px solid #cbd5e1 !important; }
.bk-btn-danger { background: #fff7f7 !important; color: #b91c1c !important;
  border: 1px solid #fca5a5 !important; }
.bk-btn:disabled { opacity: 0.45; }
.bk-btn:hover:not(:disabled) { filter: brightness(0.95); }
:host { max-width: 100%; min-width: 0; }
"""
DOWNLOAD_STYLE = """
.bk-btn { background: #15803d !important; color: white !important;
  border: 1px solid #15803d !important; }
.bk-btn a { color: inherit !important; text-decoration: none; }
"""


def style_button(widget, role=None):
    if role is None:
        declared = next(
            (
                tag.removeprefix("scmm-role-")
                for tag in widget.tags
                if isinstance(tag, str) and tag.startswith("scmm-role-")
            ),
            None,
        )
        role = declared or (
            "download"
            if isinstance(widget, pn.widgets.FileDownload)
            else {
                "primary": "action",
                "danger": "danger",
            }.get(widget.color, "auxiliary")
        )
    widget.tags = [
        tag for tag in widget.tags if not (isinstance(tag, str) and tag.startswith("scmm-role-"))
    ] + [f"scmm-role-{role}"]
    widget.color = {
        "action": "primary",
        "download": "success",
        "danger": "danger",
        "auxiliary": "default",
    }[role]
    widget.variant = "solid" if role in {"action", "download"} else "outline"
    if role == "download":
        widget.icon = "download"
    widget.sizing_mode = None
    widget.width = min(400, max(110, 42 + sum(14 if ord(c) > 127 else 7 for c in widget.label)))
    widget.height = None
    if BUTTON_STYLE not in widget.stylesheets:
        widget.stylesheets = [*widget.stylesheets, BUTTON_STYLE]
    if role == "download" and DOWNLOAD_STYLE not in widget.stylesheets:
        widget.stylesheets = [*widget.stylesheets, DOWNLOAD_STYLE]
    return widget


def fit_plot(pane, kind="analysis"):
    ratio, width = {"square": (1, 720), "spectrum": (2, 1000), "analysis": (4 / 3, 900)}[kind]
    pane.param.update(
        height=None,
        width=None,
        sizing_mode="scale_width",
        aspect_ratio=ratio,
        max_width=width,
        min_width=0,
    )
    return pane


CONTENT_STYLE = """
:host { box-sizing: border-box; padding-right: 360px; min-width: 0; }
@media (max-width: 1100px) { :host { padding-right: 0; padding-bottom: 60px; } }
"""


class UnsavedGuard(pn.reactive.ReactiveHTML):
    """Best-effort browser warning only; never saves or cancels a worker."""

    dirty = param.Boolean(default=False)
    _template = '<span id="guard" aria-hidden="true"></span>'
    _scripts: ClassVar[dict] = {
        "render": """
          state.warn = (event) => {
            if (data.dirty) {
              event.preventDefault();
              event.returnValue = '';
            }
          };
          window.addEventListener('beforeunload', state.warn);
        """,
        "remove": "window.removeEventListener('beforeunload', state.warn);",
    }


class TaskDock(pn.reactive.ReactiveHTML):
    content = param.ClassSelector(class_=pn.viewable.Viewable)
    label = param.String(default="任务与日志（点击展开 / 收起）")
    _template = """
    <details id="drawer" class="task-drawer" open>
      <summary id="toggle" class="task-toggle">${label}</summary>
      <div id="contents" class="task-contents">${content}</div>
    </details>
    """
    _scripts: ClassVar[dict] = {
        "render": """
          state.media = window.matchMedia('(max-width: 1100px)');
          state.resize = () => { drawer.open = !state.media.matches; };
          state.media.addEventListener('change', state.resize);
          state.resize();
        """,
        "remove": "state.media?.removeEventListener('change', state.resize);",
    }
    _stylesheets: ClassVar[list] = [
        """
    :host { position: fixed !important; right: 18px; top: 85px; bottom: 18px;
      width: 340px !important; height: calc(100vh - 103px) !important; z-index: 100;
      background: var(--background-color, white); border: 1px solid #b6cbc8;
      border-radius: 10px; box-shadow: 0 3px 14px #0002; overflow: auto; }
    .task-drawer { padding: 12px; }
    .task-toggle { display: none; cursor: pointer; font-weight: 600; }
    .task-contents { display: block; }
    @media (max-width: 1100px) {
      :host { top: auto; bottom: 10px; right: 10px;
        width: min(360px, calc(100vw - 20px)) !important; height: auto !important; max-height: 65vh; }
      .task-toggle { display: list-item; }
      details:not([open]) > .task-contents { display: none; }
    }
    """
    ]


class PlotWidth(pn.reactive.ReactiveHTML):
    """Report container width for server-side subplot layout without polling."""

    pixels = param.Integer(default=900)
    _template = '<div id="measure" style="width:100%;height:1px"></div>'
    _scripts: ClassVar[dict] = {
        "render": """
          state.observer = new ResizeObserver(entries => {
            const width = Math.round(entries[0].contentRect.width);
            if (width > 0 && Math.abs(width - data.pixels) > 30) data.pixels = width;
          });
          state.observer.observe(measure);
        """,
        "remove": "state.observer?.disconnect();",
    }
