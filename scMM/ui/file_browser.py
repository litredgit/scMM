"""Small server-directory browser with explicit selection and root validation."""

from pathlib import Path

import pandas as pd
import panel as pn
import param

from scMM.application.storage import SUPPORTED_RAW_SUFFIXES


class FileBrowser(pn.viewable.Viewer):
    value = param.List(default=[])

    def __init__(self, catalog, label, *, results=False, **params):
        super().__init__(**params)
        self.catalog, self.label, self.results = catalog, label, results
        self.directory = catalog.root(label).path
        self.path = pn.widgets.TextInput(label="Directory", value=str(self.directory))
        self.search = pn.widgets.TextInput(label="Search", placeholder="搜索名称")
        self.table = pn.widgets.Tabulator(
            pd.DataFrame(),
            show_index=False,
            disabled=True,
            selectable=False,
            height=230,
            text_align="center",
        )
        self.selected = pn.widgets.MultiChoice(label="Selected files", options=[])
        self.status = pn.pane.Markdown("")
        up = pn.widgets.Button(label="上级目录")
        go = pn.widgets.Button(label="打开路径")
        clear = pn.widgets.Button(label="清空选择")
        use = pn.widgets.Button(label="选择当前结果目录", visible=results)
        up.on_click(
            lambda _: self.open(
                self.directory.parent
                if self.directory != self.catalog.root(label).path
                else self.directory
            )
        )
        go.on_click(lambda _: self.open(self.path.value))
        clear.on_click(lambda _: setattr(self, "value", []))
        use.on_click(lambda _: self.choose(self.directory))
        self.table.on_click(self._click)
        self.search.param.watch(lambda _: self.refresh(), "value")
        self.selected.param.watch(lambda e: setattr(self, "value", e.new), "value")
        self.param.watch(self._selection, "value")
        self.panel = pn.Column(
            pn.Row(up, go, use),
            self.path,
            self.search,
            self.table,
            self.selected,
            clear,
            self.status,
            sizing_mode="stretch_width",
        )
        self.refresh()

    def __panel__(self):
        return self.panel

    def open(self, path):
        try:
            target = self.catalog.resolve(self.label, path)
            if not target.is_dir():
                raise ValueError("请选择目录")
            self.directory = target
            self.path.value = str(target)
            self.refresh()
            self.status.object = ""
        except (OSError, ValueError, PermissionError) as exc:
            self.status.object = str(exc)

    def refresh(self):
        rows = []
        for entry in sorted(
            self.directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        ):
            try:
                path = self.catalog.resolve(self.label, entry)
                if self.search.value.lower() not in path.name.lower():
                    continue
                if not path.is_dir() and path.suffix.lower() not in (
                    {".h5ad"} if self.results else SUPPORTED_RAW_SUFFIXES
                ):
                    continue
                rows.append(
                    {
                        "Name": path.name,
                        "Type": "目录" if path.is_dir() else path.suffix,
                        "Size": "" if path.is_dir() else f"{path.stat().st_size / 1024**2:.2f} MB",
                        "path": str(path),
                    }
                )
            except (OSError, PermissionError):
                continue
        self.table.value = pd.DataFrame(rows, columns=["Name", "Type", "Size", "path"])
        self.table.hidden_columns = ["path"]

    def _click(self, event):
        path = Path(self.table.value.iloc[event.row]["path"])
        self.open(path) if path.is_dir() else self.choose(path)

    def choose(self, path):
        path = (
            self.catalog.resolve(self.label, path)
            if self.results
            else self.catalog.resolve_raw_file(self.label, path)
        )
        self.value = [str(path)] if self.results else list(dict.fromkeys([*self.value, str(path)]))

    def _selection(self, event):
        self.selected.options = {
            str(Path(p).relative_to(self.catalog.root(self.label).path)): p for p in event.new
        }
        self.selected.value = list(event.new)
