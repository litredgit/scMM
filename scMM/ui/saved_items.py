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
        self.preview = pn.pane.Markdown("先选择内容并预览删除计划。")
        self.confirm = pn.widgets.Checkbox(label="确认将上述项目或结果移入回收区")
        self.move_button = self.button("确认移入回收区", self.move, role="danger")
        self.move_button.disabled = True
        self.trash = pn.widgets.Select(label="回收区条目", options={}, width=480)
        self.restore_note = pn.pane.Markdown("")
        self.trash.param.watch(self._restore_preview, "value")
        self.restore_button = self.button("恢复到原路径", self.restore)
        self.confirm.param.watch(
            lambda e: setattr(self.move_button, "disabled", not (e.new and self.plan)), "value"
        )
        self.root.param.watch(lambda _: self._browse(), "value")
        for widget in (self.project, self.root, self.path):
            widget.param.watch(lambda _: self.invalidate(), "value")
        self.panel = pn.Column(
            "删除会将内容移入所在存储的 scMM 回收区，不释放磁盘空间；可恢复到原路径。"
            "原始谱不能删除。项目须先保存并关闭；被其他项目引用的结果和未结束任务受保护。",
            pn.Tabs(
                (
                    "已保存项目",
                    pn.Column(self.project, self.button("预览删除所选项目", self.plan_project)),
                ),
                (
                    "独立结果",
                    pn.Column(
                        self.root,
                        self.browser_area,
                        self.path,
                        self.button("预览删除所选结果", self.plan_result),
                    ),
                ),
                ("回收区", pn.Column(self.trash, self.restore_note, self.restore_button)),
                dynamic=True,
            ),
            flow(self.button("刷新已保存内容", self.refresh)),
            self.preview,
            self.confirm,
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
        self.confirm.value = False
        self.move_button.disabled = True
        self.preview.object = "选择已变化，请重新预览删除计划。"

    def _browse(self):
        self.browser = FileBrowser(self.manager.catalog, self.root.value, results=True)
        self.browser.param.watch(
            lambda e: setattr(self.path, "value", e.new[0] if e.new else ""), "value"
        )
        self.browser_area[:] = [self.browser]
        apply_presentation(self.browser_area)

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

    def plan_project(self):
        if not self.project.value:
            raise ValueError("请选择已保存项目")
        self.show_plan("项目结果", self.project.value)

    def plan_result(self):
        if not self.path.value:
            raise ValueError("请选择结果")
        self.show_plan(self.root.value, self.path.value)

    def move(self):
        if not self.confirm.value or self.plan is None:
            raise ValueError("请先预览删除计划并明确确认")
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

    def refresh(self):
        self.invalidate()
        previous_project, previous_trash = self.project.value, self.trash.value
        self.project.options = {
            f"{r['name']} · {beijing_time(r['saved_at'])}": r["path"]
            for r in self.manager.store.list()
        }
        self.trash.options = {
            f"{beijing_time(r['deleted_at'])} · {r['kind']} · {r['path']}": r["entry"]
            for r in self.manager.list_trash()
        }
        projects, entries = list(self.project.options.values()), list(self.trash.options.values())
        self.project.value = (
            previous_project
            if previous_project in projects
            else (projects[0] if projects else None)
        )
        self.trash.value = (
            previous_trash if previous_trash in entries else (entries[0] if entries else None)
        )
        self.restore_button.disabled = not self.trash.value
        self._restore_preview()
        if self.browser.directory.exists():
            self.browser.refresh()
