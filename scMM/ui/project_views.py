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
