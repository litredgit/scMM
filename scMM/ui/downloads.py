"""Panel downloads whose cached bytes can be cleared while mounted."""

import panel as pn


class FileDownload(pn.widgets.FileDownload):
    def _process_param_change(self, params):
        properties = super()._process_param_change(params)
        # Panel accepts None but its Bokeh model requires a string on updates.
        if "data" in properties and properties["data"] is None:
            properties["data"] = ""
        return properties
