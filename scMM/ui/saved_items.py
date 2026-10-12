"""Saved-item management with an explicit plan and reversible removal."""
# ruff: noqa: RUF001

from html import escape

import panel as pn

from scMM.application.naming import beijing_time
from scMM.application.trash import SavedItems

from .file_browser import FileBrowser
from .layout import flow, style_button
from .presentation import apply_presentation


class SavedItemsPanel(pn.viewable.Viewer):
    def __init__(self, store, roots, *, active_paths, changed, **params):
        super().__init__(**params)
        self.manager = SavedItems(store, roots, active_paths=active_paths)
        self.changed = changed
        self.plan = None
        self.project = pn.widgets.Select(label="已保存项目", options={})
        self.root = pn.widgets.Select(
            label="结果存储", options=[r.label for r in self.manager.catalog.roots]
        )
        self.path = pn.widgets.TextInput(
            label="结果路径", placeholder="选择 H5AD 或结果目录", width=480
        )
        self.browser_area = pn.Column()
        self.notice = pn.pane.Markdown("")
        self.preview = pn.pane.Markdown("选择内容后显示待删除清单，点击移入回收区立即执行。")
        self.move_button = self.button("移入回收区", self.move, role="danger")
        self.move_button.disabled = True
        self.trash = pn.widgets.Select(label="回收区条目", options={}, width=480)
        self.restore_note = pn.pane.Markdown("")
        self.trash.param.watch(self._restore_preview, "value")
        self.restore_button = self.button("恢复到原路径", self.restore)
        self.root.param.watch(lambda _: self._browse(), "value")
        self.project.param.watch(lambda _: self._selected_plan(), "value")
        self.path.param.watch(lambda _: self._selected_plan(), "value")
        self.tabs = pn.Tabs(
            (
                "已保存项目",
                pn.Column(self.project),
            ),
            (
                "独立结果",
                pn.Column(
                    self.root,
                    self.browser_area,
                    self.path,
                ),
            ),
            (
                "回收区",
                pn.Column(
                    self.trash,
                    self.restore_note,
                    self.restore_button,
                    "开发与生产共用回收区；点击清空会立即永久删除全部回收条目，无法恢复。",
                    self.button("清空回收区", self.clear, role="danger"),
                ),
            ),
            dynamic=True,
        )
        self.tabs.param.watch(lambda _: self._selected_plan(), "active")
        self.panel = pn.Column(
            "删除会将内容移入共享回收区 ~/data/results/recycle，不释放磁盘空间；可恢复到原路径。"
            "原始谱不能删除。项目须先保存并关闭；被其他项目引用的结果和未结束任务受保护。",
            self.tabs,
            flow(self.button("刷新已保存内容", self.refresh)),
            self.preview,
            self.move_button,
            self.notice,
            css_classes=["scmm-saved-items"],
            sizing_mode="stretch_width",
        )
        self._browse()
        self.refresh()
        apply_presentation(self.panel)

    def __panel__(self):
        return self.panel

    def button(self, label, action, *, role="auxiliary"):
        button = style_button(pn.widgets.Button(label=label), role)
        button.on_click(lambda _: self.run(action))
        return button

    def run(self, action):
        try:
            action()
        except Exception as exc:
            self.notice.object = f"❌ {escape(str(exc))}"

    def invalidate(self):
        self.plan = None
        self.move_button.disabled = True
        self.preview.object = "请选择待移入回收区的内容。"

    def _browse(self):
        self.path.value = ""
        self.invalidate()
        self.browser = FileBrowser(self.manager.catalog, self.root.value, results=True)
        self.browser.param.watch(
            lambda e: setattr(self.path, "value", e.new[0] if e.new else ""), "value"
        )
        self.browser_area[:] = [self.browser]
        apply_presentation(self.browser_area)

    def _selected_plan(self):
        if not hasattr(self, "tabs"):
            return
        if self.tabs.active == 2:
            self.invalidate()
            return
        label, path = (
            ("项目结果", self.project.value)
            if self.tabs.active == 0
            else (self.root.value, self.path.value)
        )
        self._selection_plan(label, path)

    def _selection_plan(self, label, path):
        if not path:
            self.invalidate()
            return
        self.run(lambda: self.show_plan(label, path))

    def show_plan(self, label, path):
        self.invalidate()
        self.plan = self.manager.plan(label, path)
        p = self.plan
        self.preview.object = (
            f"**待移入回收区：{p['kind']}**\n\n原路径：`{escape(p['path'])}`\n\n"
            f"包含 **{p['files']} 个文件**，共 **{p['bytes'] / 1024**2:.3f} MB**。"
            "目录内容将整体移动；原始谱引用不会移动原文件。"
        )
        self.notice.object = ""
        self.move_button.disabled = False

    def plan_project(self):
        if not self.project.value:
            raise ValueError("请选择已保存项目")
        self.show_plan("项目结果", self.project.value)

    def plan_result(self):
        if not self.path.value:
            raise ValueError("请选择结果")
        self.show_plan(self.root.value, self.path.value)

    def move(self):
        if self.plan is None:
            raise ValueError("请选择待移入回收区的内容")
        self.manager.move(self.plan)
        self.invalidate()
        self.refresh()
        self.changed()
        self.notice.object = "已移入回收区，可在“回收区”页恢复。"

    def _restore_preview(self, _=None):
        row = next((r for r in self.manager.list_trash() if r["entry"] == self.trash.value), None)
        self.restore_note.object = (
            f"恢复路径：`{escape(row['path'])}`；不会覆盖同名内容。" if row else "回收区为空。"
        )

    def restore(self):
        if not self.trash.value:
            raise ValueError("请选择回收区条目")
        original = self.manager.restore(self.trash.value)
        self.refresh()
        self.changed()
        self.notice.object = f"已恢复：`{escape(str(original))}`"

    def clear(self):
        try:
            count = self.manager.clear()
        finally:
            self.refresh()
        self.changed()
        self.notice.object = f"已永久清空回收区，共清理 {count} 项。"

    def refresh(self):
        self.invalidate()
        previous_project, previous_trash = self.project.value, self.trash.value
        self.project.options = {
            "请选择待管理项目": None,
            **{
                f"{r['name']} · {beijing_time(r['saved_at'])}": r["path"]
                for r in self.manager.store.list()
            },
        }
        self.trash.options = {
            f"{beijing_time(r['deleted_at'])} · {r['kind']} · {r['path']}": r["entry"]
            for r in self.manager.list_trash()
        }
        projects, entries = list(self.project.options.values()), list(self.trash.options.values())
        self.project.value = previous_project if previous_project in projects else None
        self.trash.value = (
            previous_trash if previous_trash in entries else (entries[0] if entries else None)
        )
        self.restore_button.disabled = not self.trash.value
        self._restore_preview()
        self._selected_plan()
        if self.browser.directory.exists():
            self.browser.refresh()
