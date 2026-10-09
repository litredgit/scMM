"""Project-specific raw preview presentation; numerical work stays in application."""
# ruff: noqa: RUF001

from .raw_components import PreviewWorkspace


class ProjectRawViews(PreviewWorkspace):
    def _invalidate_cells(self):
        if self.preview is None:
            return super()._invalidate_cells()
        self.cell_download.disabled = True
        self.cell_download.data = None
        self.cell_status.object = "参数已改变；下图为旧参数结果，请重新预览后确认。"

    def _invalidate_raw_plots(self):
        if self.preview is None:
            return super()._invalidate_raw_plots()
        for download in (self.tic_download, self.eic_download, self.spectrum_download):
            download.disabled = True
            download.data = None
        self.summary.object = "显示参数已改变；下图尚未刷新。"

    def _calculate_all(self):
        super()._calculate_all()
        if hasattr(self, "selection_mode"):
            self._selection_mode()

    def setup_navigation(self):
        import panel as pn

        self._scan_sync = False
        self.scan_time = pn.widgets.FloatInput(label="Scan time (s)", value=0.0)
        self.scan_slider = pn.widgets.FloatSlider(
            label="Scan time (s)", start=0.0, end=1.0, value=0.0
        )
        self.scan_previous = pn.widgets.Button(label="上一帧")
        self.scan_next = pn.widgets.Button(label="下一帧")
        self.selection_mode = pn.widgets.RadioButtonGroup(
            options={"缩放": "zoom", "选择合谱范围": "select"}, value="zoom"
        )
        self.merge_start = pn.widgets.FloatInput(label="Merge start (s)", value=0.0)
        self.merge_end = pn.widgets.FloatInput(label="Merge end (s)", value=1.0)
        self.merge_note = pn.pane.Markdown("")
        self.merge_update = pn.widgets.Button(label="更新合谱")
        self.merge_update.on_click(self._merge_selected)
        self.selection_mode.param.watch(self._selection_mode, "value")
        for pane in (self.tic_pane, self.eic_pane, self.cell_pane):
            pane.param.watch(self._selected_range, "selected_data")
        self.scan_time.param.watch(lambda e: self._seek_scan(time=e.new), "value")
        self.scan_slider.param.watch(lambda e: self._seek_scan(time=e.new), "value_throttled")
        self.scan_index.param.watch(lambda e: self._seek_scan(index=e.new), "value")
        self.scan_previous.on_click(lambda _: self._seek_scan(step=-1))
        self.scan_next.on_click(lambda _: self._seek_scan(step=1))
        self.ms_level.param.watch(lambda _: self._scan_catalog(), "value")

    def _scan_catalog(self):
        if self.preview is None or not hasattr(self, "scan_time"):
            return
        self._scans = self.preview.total_ion_chromatogram(ms_level=int(self.ms_level.value))
        if not self._scans.empty:
            low, high = float(self._scans.rt_seconds.min()), float(self._scans.rt_seconds.max())
            self._scan_sync = True
            try:
                self.scan_slider.param.update(start=low, end=max(high, low + 0.001), value=low)
                self.merge_start.value, self.merge_end.value = low, high
            finally:
                self._scan_sync = False
            self._seek_scan(index=int(self._scans.scan_index.iloc[0]))

    def _seek_scan(self, *, time=None, index=None, step=None):
        if (
            self._scan_sync
            or self.preview is None
            or not hasattr(self, "_scans")
            or self._scans.empty
        ):
            return
        scans = self._scans
        if time is not None:
            row = scans.iloc[(scans.rt_seconds - time).abs().argmin()]
        else:
            pos = (
                (scans.scan_index - (self.scan_index.value if index is None else index))
                .abs()
                .argmin()
            )
            pos = max(0, min(len(scans) - 1, pos + (step or 0)))
            row = scans.iloc[pos]
        self._scan_sync = True
        try:
            self.scan_index.value = int(row.scan_index)
            self.scan_time.value = float(row.rt_seconds)
            self.scan_slider.value = float(row.rt_seconds)
        finally:
            self._scan_sync = False

    def _selection_mode(self, _=None):
        from copy import deepcopy

        for pane in (self.tic_pane, self.eic_pane, self.cell_pane):
            figure = deepcopy(pane.object)
            figure.update_layout(dragmode=self.selection_mode.value, selectdirection="h")
            pane.object = figure

    def _selected_range(self, event):
        selection = event.new or {}
        if self.selection_mode.value != "select":
            return
        bounds = selection.get("range", {}).get("x")
        if not bounds:
            values = [point["x"] for point in selection.get("points", []) if "x" in point]
            bounds = (min(values), max(values)) if values else None
        if bounds:
            self.merge_start.value, self.merge_end.value = sorted(map(float, bounds))
            self.merge_note.object = "范围已选择，点击更新合谱。"

    def _merge_selected(self, _=None):
        from .raw_components import _spectrum_figure

        if self.preview is None:
            return
        low, high = self.merge_start.value, self.merge_end.value
        if low > high:
            self.merge_note.object = "起始时间不能大于结束时间。"
            return
        try:
            self.spectrum = self.preview.binned_spectrum(
                mz_range=(self.mz_min.value, self.mz_max.value),
                bins=20_000,
                ms_level=int(self.ms_level.value),
                rt_range=(low, high),
                normalize=self.average_spectrum.value,
            )
            self.spectrum_pane.object = _spectrum_figure(
                self.spectrum,
                f"{'平均谱' if self.average_spectrum.value else '合并谱'} · {low:.3f}–{high:.3f} s",
            )
            self.spectrum_download.disabled = self.spectrum.empty
            self.spectrum_download.data = None
            frames = self._scans.loc[self._scans.rt_seconds.between(low, high)]
            self.merge_note.object = f"覆盖 {len(frames)} 帧" + (
                f"（{int(frames.scan_index.iloc[0])}–{int(frames.scan_index.iloc[-1])}）"
                if len(frames)
                else ""
            )
        except Exception as exc:
            self.merge_note.object = f"合谱失败：{exc}"
