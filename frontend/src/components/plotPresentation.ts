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
