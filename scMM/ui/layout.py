"""Responsive presentation only; never changes figure coordinates or data."""
# ruff: noqa: RUF001

from typing import ClassVar

import panel as pn
import param


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
