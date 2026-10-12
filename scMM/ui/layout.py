"""Responsive presentation only; never changes figure coordinates or data."""

from typing import ClassVar

import panel as pn
import param


def flow(*objects, **params):
    """Wrap compact controls instead of stretching buttons or overflowing rows."""
    return pn.FlexBox(
        *objects,
        flex_wrap="wrap",
        align_items="flex-end",
        gap="8px",
        sizing_mode="stretch_width",
        **params,
    )


def form(*objects, **params):
    return pn.FlexBox(
        *objects,
        flex_wrap="wrap",
        align_items="flex-start",
        gap="12px",
        stylesheets=[
            """
          [id^="flexbox-"] { display: grid !important;
            grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
            align-items: end; }
          [id^="flex-item-"] > * { width: 100% !important; min-width: 0; }
        """
        ],
        sizing_mode="stretch_width",
        **params,
    )


FIELD_STYLE = """
:host { min-width: 0; max-width: 100%; }
.bk-input-group { white-space: normal; }
.bk-input-group > label { display: grid; grid-template-columns: minmax(0, 1fr) 28px;
  align-items: start; width: 100%; min-height: 28px; line-height: 1.4;
  white-space: normal; overflow-wrap: anywhere; padding-bottom: 4px; }
.bk-description { margin: 0; width: 28px; height: 28px; display: inline-flex;
  align-items: center; justify-content: center; }
.bk-description:focus-visible { outline: 2px solid #2563eb; border-radius: 4px; }
.bk-input { min-height: 36px; }
@media (pointer: coarse) { .bk-input { min-height: 44px; } }
"""


CONTROL_BUTTON_STYLE = """
.bk-btn { min-height: 38px; white-space: normal; overflow-wrap: anywhere;
  line-height: 1.4; padding: 7px 12px; box-sizing: border-box; }
@media (pointer: coarse) { .bk-btn { min-height: 44px; } }
"""


BUTTON_STYLE = """
.bk-btn { border-radius: 6px; padding: 7px 12px; font-weight: 500;
  white-space: normal; overflow-wrap: anywhere; line-height: 1.4;
  min-height: 38px; width: 100%; box-sizing: border-box; }
@media (pointer: coarse) { .bk-btn { min-height: 44px; } }
.bk-btn-primary { background: #2563eb !important; color: white !important; }
.bk-btn-success { background: #15803d !important; color: white !important; }
.bk-btn-default { background: white !important; color: #475569 !important;
  border: 1px solid #cbd5e1 !important; }
.bk-btn-danger { background: #fff7f7 !important; color: #b91c1c !important;
  border: 1px solid #fca5a5 !important; }
.bk-btn:disabled { opacity: 0.45; }
.bk-btn:hover:not(:disabled) { filter: brightness(0.95); }
:host { max-width: 100%; min-width: 0; width: fit-content; flex: 0 1 auto; }
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
    widget.width = None
    widget.styles = {**widget.styles, "width": "fit-content", "max-width": "100%", "min-width": "0"}
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
:host { box-sizing: border-box; padding: 0; min-width: 0; }
"""


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


class ResponsivePage(pn.reactive.ReactiveHTML):
    """Collapse navigation on narrow windows while keeping manual access."""

    _template = '<div id="marker" style="height:0"></div>'
    _scripts: ClassVar[dict] = {
        "render": """
          state.style = document.createElement("style");
          state.style.textContent = `
            #main { min-width: 0; }
            .pn-wrapper { min-width: 0; }
            @media (max-width: 1000px) {
              #sidebar { position: fixed; top: 64px; left: 0; z-index: 1000;
                background: var(--neutral-fill-rest, white); }
              #sidebar:not(.hidden) { box-shadow: 4px 0 16px #0002; }
              #main { padding: 0 8px; }
            }
            @media (max-width: 600px) {
              .title { font-size: 18px; }
            }
          `;
          document.head.appendChild(state.style);
          state.media = window.matchMedia("(max-width: 1000px)");
          state.update = () => {
            if (state.media.matches) window.closeNav?.();
            else window.openNav?.();
          };
          state.media.addEventListener("change", state.update);
          state.update();
        """,
        "remove": """
          state.media?.removeEventListener("change", state.update);
          state.style?.remove();
        """,
    }
