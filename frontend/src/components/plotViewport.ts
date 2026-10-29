import type { Figure } from '../api/types'

/** Store complete axis ranges after Plotly applies zoom, pan or reset. */
export function readViewport(layout: Record<string, unknown>) {
  const result: Record<string, unknown> = {}
  for (const [name, value] of Object.entries(layout)) {
    if (/^[xy]axis\d*$/.test(name) && value && typeof value === 'object') {
      const axis = value as { range?: unknown[]; autorange?: boolean | string }
      if (axis.range?.length === 2) result[`${name}.range`] = [...axis.range]
      if (axis.autorange !== undefined) result[`${name}.autorange`] = axis.autorange
    } else if (/^scene\d*$/.test(name) && value && typeof value === 'object') {
      const camera = (value as { camera?: unknown }).camera
      if (camera) result[`${name}.camera`] = JSON.parse(JSON.stringify(camera))
    }
  }
  return result
}

export function applyViewport(figure: Figure, viewport: Record<string, unknown>, freeze = false) {
  // Accept legacy incremental viewport records saved by older projects.
  for (const [key, value] of Object.entries(viewport)) {
    const match = /^([xy]axis\d*)\.range(?:\[(\d)\])?$/.exec(key)
    if (match) {
      const axis = (figure.layout[match[1]!] ??= {}) as Record<string, unknown>
      if (match[2] === undefined) axis.range = value
      else ((axis.range ??= []) as unknown[])[Number(match[2])] = value
      if (freeze || viewport[`${match[1]}.autorange`] !== true) axis.autorange = false
    }
  }
  for (const [key, value] of Object.entries(viewport)) {
    if (key.endsWith('.autorange')) {
      const name = key.split('.')[0]!
      const axis = (figure.layout[name] ??= {}) as Record<string, unknown>
      axis.autorange = freeze && axis.range ? false : value
      if (axis.autorange === true) delete axis.range
    } else if (/^scene\d*\.camera$/.test(key)) {
      const name = key.split('.')[0]!
      figure.layout[name] = { ...(figure.layout[name] as object), camera: value }
    }
  }
  return figure
}
