import { toRaw } from 'vue'
import type { Figure } from '../api/types'

export function applyLegend(figure: Figure, position: string, narrow = false) {
  const outside = position === 'right'
  const below = outside && narrow
  const right = position.endsWith('right')
  const bottom = position.startsWith('bottom')
  const hidden = position === 'hidden'
  const legend = outside
    ? below
      ? { x: 0, y: -0.22, xanchor: 'left', yanchor: 'top', orientation: 'h' }
      : { x: 1.02, y: 1, xanchor: 'left', yanchor: 'top' }
    : {
        x: right ? 0.99 : 0.01,
        y: bottom ? 0.01 : 0.99,
        xanchor: right ? 'right' : 'left',
        yanchor: bottom ? 'bottom' : 'top',
        bgcolor: 'rgba(255,255,255,0.8)',
      }
  figure.layout.showlegend = !hidden
  figure.layout.legend = { ...(figure.layout.legend as object), ...legend }
  const bar = {
    x: outside ? 1.02 : right ? 0.98 : 0.02,
    xanchor: !outside && right ? 'right' : 'left',
    y: bottom ? 0.02 : 0.98,
    yanchor: bottom ? 'bottom' : 'top',
    len: outside ? 1 : 0.65,
  }
  for (const [name, value] of Object.entries(figure.layout)) {
    if (/^coloraxis\d*$/.test(name) && value && typeof value === 'object') {
      const axis = value as Record<string, unknown>
      axis.showscale = !hidden
      axis.colorbar = { ...(axis.colorbar as object), ...bar }
    }
  }
  for (const trace of figure.data as Record<string, unknown>[]) {
    const marker = trace.marker as Record<string, unknown> | undefined
    for (const holder of [trace, marker]) {
      if (holder?.colorbar) {
        holder.showscale = !hidden
        holder.colorbar = { ...(holder.colorbar as object), ...bar }
      }
    }
  }
  return figure
}

const chartKeys: Record<string, string> = {
  embedding: 'analysis.embedding_plot',
  network_plot: 'analysis.network_plot',
  shap_plot: 'analysis.shap_plot',
  qc_plot: 'analysis.qc_plot',
  volcano: 'analysis.volcano',
  violin: 'analysis.violin',
  network: 'analysis.network_plot',
  shap: 'analysis.shap_plot',
  roc: 'analysis.roc',
  pr: 'analysis.pr',
  calibration: 'analysis.calibration',
  'current-qc': 'analysis.qc_plot',
  'raw-tic': 'raw.tic_pane',
  'raw-eic': 'raw.eic_pane',
  'raw-sum': 'raw.spectrum_pane',
  'raw-single': 'raw.scan_pane',
  'raw-cells': 'raw.cell_pane',
}

export function plotChartKey(name: string, viewKey?: string) {
  return viewKey ?? chartKeys[name] ?? name
}

export function copyFigure(figure: Figure): Figure {
  const { meta, ...layout } = toRaw(figure.layout)
  const copiedLayout = JSON.parse(JSON.stringify(layout)) as Figure['layout']
  if (meta && typeof meta === 'object') copiedLayout.meta = { ...meta }
  return {
    ...figure,
    layout: copiedLayout,
    data: (figure.data as Record<string, unknown>[]).map((item) => {
      const trace = { ...toRaw(item) }
      if (trace.marker && typeof trace.marker === 'object') {
        const marker = { ...trace.marker } as Record<string, unknown>
        if (marker.colorbar) marker.colorbar = JSON.parse(JSON.stringify(marker.colorbar))
        trace.marker = marker
      }
      if (trace.colorbar) trace.colorbar = JSON.parse(JSON.stringify(trace.colorbar))
      return trace
    }),
  }
}

export function plotHeight(
  figure: Figure,
  name: string,
  kind: string,
  width: number,
  spectrum: boolean,
) {
  if (spectrum && width < 680) return 560
  if (figure.layout.yaxis2 && (kind === 'cells' || name.includes('signal')))
    return Math.max(560, Math.min(760, width * 0.9))
  if (['tic', 'eic', 'sum', 'single', 'cells'].includes(kind))
    return Math.max(320, Math.min(600, width / 2.2))
  if (['roc', 'pr', 'calibration'].includes(kind)) return Math.max(360, Math.min(460, width * 0.9))
  if (kind === 'violin') return Math.max(380, Number(figure.layout.height) || 380)
  if (kind === 'shap') {
    const traces = figure.data as { y?: unknown[] }[]
    return Math.max(
      400,
      Math.min(1200, 140 + 28 * Math.max(0, ...traces.map((t) => t.y?.length ?? 0))),
    )
  }
  return Math.max(360, Math.min(460, width * (kind === 'network' ? 0.9 : 0.7)))
}
