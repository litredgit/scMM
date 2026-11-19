import type { Figure } from '../api/types'
import { applyViewport } from './plotViewport'

export interface SpectrumSettings {
  relative: boolean
  labels: boolean
  decimals: number
  threshold: number
  interaction: 'zoom' | 'pan'
}

export function isMassSpectrum(figure: Figure) {
  const meta = figure.layout.meta as Record<string, unknown> | undefined
  const axis = figure.layout.xaxis as { title?: string | { text?: string } } | undefined
  const title = typeof axis?.title === 'string' ? axis.title : axis?.title?.text
  return meta?.scmm_spectrum === true || /^m\s*\/\s*z$/i.test(title?.trim() ?? '')
}

/** Plotly 6 transports NumPy vectors as little-endian base64 typed arrays. */
function spectrumVector(value: unknown): unknown[] | undefined {
  if (Array.isArray(value)) return value
  if (!value || typeof value !== 'object') return
  const encoded = value as { dtype?: string; bdata?: string }
  if (!encoded.dtype || !encoded.bdata) return
  const readers: Record<string, [number, (data: DataView, offset: number) => number]> = {
    f8: [8, (data, offset) => data.getFloat64(offset, true)],
    f4: [4, (data, offset) => data.getFloat32(offset, true)],
    i4: [4, (data, offset) => data.getInt32(offset, true)],
    u4: [4, (data, offset) => data.getUint32(offset, true)],
    i2: [2, (data, offset) => data.getInt16(offset, true)],
    u2: [2, (data, offset) => data.getUint16(offset, true)],
    i1: [1, (data, offset) => data.getInt8(offset)],
    u1: [1, (data, offset) => data.getUint8(offset)],
  }
  const reader = readers[encoded.dtype.replace(/^[<=>]/, '')]
  if (!reader) return
  const decoded = atob(encoded.bdata)
  const bytes = Uint8Array.from(decoded, (character) => character.charCodeAt(0))
  if (bytes.length % reader[0]) return
  const data = new DataView(bytes.buffer)
  return Array.from({ length: bytes.length / reader[0] }, (_, index) =>
    reader[1](data, index * reader[0]),
  )
}

/** Transform a disposable display copy. Source tables and the scientific inputs stay intact. */
export function spectrumPresentation(
  figure: Figure,
  settings: SpectrumSettings,
  width: number,
  height = 460,
  legend = 'right',
  viewport: Record<string, unknown> = {},
) {
  if (!isMassSpectrum(figure)) {
    const traces = figure.data as Record<string, unknown>[]
    const timeAxis = (axis: Record<string, unknown>) => {
      const title = axis.title as { text?: string } | string | undefined
      return /(?:RT|Time|Retention time)\s*\(s(?:[;)]|$)/i.test(
        typeof title === 'string' ? title : (title?.text ?? ''),
      )
    }
    const timeReferences = new Set(
      Object.entries(figure.layout)
        .filter(
          ([key, value]) => /^xaxis\d*$/.test(key) && timeAxis(value as Record<string, unknown>),
        )
        .flatMap(([key, value]) => [
          key.replace('axis', ''),
          String((value as Record<string, unknown>).matches ?? ''),
        ]),
    )
    for (const [key, value] of Object.entries(figure.layout)) {
      if (!/^xaxis\d*$/.test(key)) continue
      const axis = value as Record<string, unknown>
      const title = axis?.title as { text?: string } | string | undefined
      const text = typeof title === 'string' ? title : (title?.text ?? '')
      if (
        !timeAxis(axis) &&
        (text ||
          (!timeReferences.has(key.replace('axis', '')) &&
            !timeReferences.has(String(axis.matches ?? ''))))
      )
        continue
      const reference = key.replace('axis', '')
      const axisTraces = traces.filter((trace) => (trace.xaxis ?? 'x') === reference)
      let low = Infinity,
        high = -Infinity
      for (const trace of axisTraces) {
        if (typeof trace.hovertemplate === 'string')
          trace.hovertemplate = trace.hovertemplate.replace(/%\{y(?::[^}]*)?\}/g, '%{y:.1e}')
        for (const x of spectrumVector(trace.x) ?? []) {
          if (typeof x !== 'number' || !Number.isFinite(x)) continue
          low = Math.min(low, x)
          high = Math.max(high, x)
        }
        const yKey = String(trace.yaxis ?? 'y').replace('y', 'yaxis')
        figure.layout[yKey] = {
          ...(figure.layout[yKey] as object),
          showgrid: false,
          showline: true,
          linecolor: '#222',
          ticks: 'outside',
          tickformat: '.1e',
        }
      }
      const range = viewport[`${key}.range`] as number[] | undefined
      if (range) {
        low = range[0]!
        high = range[1]!
      }
      const ticks = Number.isFinite(low)
        ? Array.from({ length: 6 }, (_, i) => low + ((high - low) * i) / 5)
        : []
      const tickDecimals = Math.min(
        6,
        Math.max(1, 1 - Math.floor(Math.log10(Math.max((high - low) / 300, 1e-6)))),
      )
      figure.layout[key] = {
        ...axis,
        title: { text: 'RT (min)' },
        showgrid: false,
        showline: true,
        linecolor: '#222',
        ticks: 'outside',
        tickmode: 'array',
        tickvals: ticks,
        ticktext: ticks.map((x) => (x / 60).toFixed(tickDecimals)),
      }
      figure.layout.meta = { ...(figure.layout.meta as object), scmm_chromatogram: true }
      figure.layout.paper_bgcolor = '#fff'
      figure.layout.plot_bgcolor = '#fff'
    }
    return figure
  }
  const decimals = 4
  const threshold = Number.isFinite(settings.threshold)
    ? Math.max(0, Math.min(100, settings.threshold))
    : 1
  const traces = figure.data as Record<string, unknown>[]
  for (const trace of traces) {
    if (typeof trace.hovertemplate === 'string')
      trace.hovertemplate = trace.hovertemplate
        .replace(/%\{y(?::[^}]*)?\}/g, '%{y:.1e}')
        .replace(/%\{x(?::[^}]*)?\}/g, '%{x:.4f}')
    for (const coordinate of ['x', 'y']) {
      const vector = spectrumVector(trace[coordinate])
      if (vector) trace[coordinate] = vector
    }
  }
  const meta = (figure.layout.meta ?? {}) as Record<string, unknown>
  const relative =
    settings.relative &&
    meta.intensity_missing !== true &&
    meta.relative_intensity_allowed !== false
  const observed = traces.filter(
    (trace) => (trace.meta as Record<string, unknown> | undefined)?.spectrum_role !== 'reference',
  )
  let base = 0
  for (const trace of observed)
    for (const y of (Array.isArray(trace.y) ? trace.y : []) as unknown[])
      if (typeof y === 'number' && Number.isFinite(y)) base = Math.max(base, Math.abs(y))
  const factor = relative && base > 0 ? 100 / base : 1
  const originalY = figure.layout.yaxis as Record<string, unknown> | undefined
  figure.layout = {
    ...figure.layout,
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    hovermode: 'closest',
    dragmode: settings.interaction,
    xaxis: {
      ...(figure.layout.xaxis as object),
      showline: true,
      linecolor: '#222222',
      linewidth: 1,
      ticks: 'outside',
      tickcolor: '#222222',
      showgrid: false,
      zeroline: false,
      tickformat: '.4f',
      title: { text: 'm/z' },
    },
    yaxis: {
      ...originalY,
      showline: true,
      linecolor: '#222222',
      linewidth: 1,
      ticks: 'outside',
      tickcolor: '#222222',
      showgrid: false,
      zeroline: false,
      title: relative
        ? { text: 'Relative abundance (%)' }
        : (originalY?.title ?? { text: 'Intensity' }),
      tickformat: '.1e',
    },
    meta: {
      ...meta,
      scmm_spectrum: true,
      spectrum_display: { ...settings, relative, base_peak: base },
    },
  }
  if (relative && Array.isArray(originalY?.range))
    (figure.layout.yaxis as Record<string, unknown>).range = originalY.range.map(
      (value: unknown) => (typeof value === 'number' ? value * factor : value),
    )
  const labelsProvided = traces.some(
    (trace) => String(trace.mode).includes('text') && Array.isArray(trace.text),
  )
  const peaks: { x: number; y: number }[] = []
  const textLabels: { x: number; y: number; text: string; priority: number; font: unknown }[] = []
  for (const trace of traces) {
    const y = (trace.y ?? []) as unknown[]
    const x = (trace.x ?? []) as unknown[]
    if (!Array.isArray(y) || !Array.isArray(x)) continue
    const sourceText = trace.text as unknown[] | undefined
    if (relative && typeof trace.hovertemplate === 'string')
      trace.hovertemplate = trace.hovertemplate.replace(
        /\b(?:Mean )?[Ii]ntensity(?=\s*[:=])/g,
        'Relative abundance (%)',
      )
    if (sourceText && String(trace.mode).includes('text')) {
      const role = (trace.meta as Record<string, unknown> | undefined)?.annotation_role
      const priority =
        role === 'selected' || trace.name === 'Selected peak'
          ? 2
          : ['isotope', 'adduct'].includes(String(role)) ||
              ['Isotope', 'Adduct'].includes(String(trace.name))
            ? 1
            : 0
      for (let index = 0; index < sourceText.length; index++) {
        const text = sourceText[index],
          value = y[index],
          mass = x[index]
        if (
          !settings.labels ||
          !text ||
          typeof mass !== 'number' ||
          typeof value !== 'number' ||
          !Number.isFinite(mass) ||
          !Number.isFinite(value)
        )
          continue
        if (!priority && Math.abs(value) < (base * threshold) / 100) continue
        const display =
          (trace.meta as Record<string, unknown> | undefined)?.label_kind === 'mz'
            ? String(text).replace(/^[\d.]+(?=<br>|$)/, mass.toFixed(decimals))
            : String(text)
        textLabels.push({
          x: mass,
          y: value * factor,
          text: display,
          priority,
          font: trace.textfont,
        })
      }
      // Pixel offsets belong to annotations; traces retain their complete peak and hover data.
      trace.mode = String(trace.mode).replace(/\+?text\+?/, '') || 'markers'
    }
    if (
      String(trace.mode).includes('lines') &&
      (trace.meta as Record<string, unknown> | undefined)?.spectrum_role !== 'reference'
    ) {
      trace.line = { color: '#202020', width: 1, ...(trace.line as object) }
      for (let index = 0; index < y.length; index++) {
        const v = y[index],
          mass = x[index]
        if (
          typeof v !== 'number' ||
          typeof mass !== 'number' ||
          !Number.isFinite(v) ||
          !Number.isFinite(mass) ||
          v <= 0 ||
          v < (base * threshold) / 100
        )
          continue
        const before = y[index - 1],
          after = y[index + 1]
        if ((typeof before === 'number' && before > v) || (typeof after === 'number' && after >= v))
          continue
        peaks.push({ x: mass, y: v * factor })
      }
    }
    if (relative)
      trace.y = y.map((v) => (typeof v === 'number' && Number.isFinite(v) ? v * factor : v))
  }
  const existingAnnotations = (figure.layout.annotations ?? []) as Record<string, unknown>[]
  figure.layout.annotations = existingAnnotations.map((annotation) => ({
    ...annotation,
    ...(relative &&
    (!annotation.yref || annotation.yref === 'y') &&
    typeof annotation.y === 'number'
      ? { y: annotation.y * factor }
      : {}),
  }))
  if (relative)
    figure.layout.shapes = ((figure.layout.shapes ?? []) as Record<string, unknown>[]).map(
      (shape) => ({
        ...shape,
        ...(!shape.yref || shape.yref === 'y'
          ? Object.fromEntries(
              ['y0', 'y1']
                .filter((key) => typeof shape[key] === 'number')
                .map((key) => [key, Number(shape[key]) * factor]),
            )
          : {}),
      }),
    )
  applyViewport(figure, viewport)
  if (textLabels.length) {
    const outsideLegend = legend === 'right'
    const narrow = width < 680
    const rightMargin = outsideLegend && !narrow ? Math.min(260, Math.max(120, width * 0.24)) : 35
    const plotWidth = Math.max(80, width - 65 - rightMargin)
    const title = figure.layout.title as { text?: string } | string | undefined
    const titleText = typeof title === 'string' ? title : (title?.text ?? '')
    const titleLines = narrow
      ? Math.ceil(titleText.length / Math.max(12, Math.floor((width - 35) / 7.5)))
      : 1
    const plotHeight = Math.max(
      120,
      height - 40 - Math.max(0, titleLines - 1) * 16 - (outsideLegend && narrow ? 130 : 55),
    )
    let xMin = Infinity,
      xMax = -Infinity,
      yMin = 0,
      yMax = 0
    for (const trace of traces) {
      for (const value of Array.isArray(trace.x) ? trace.x : []) {
        if (typeof value !== 'number' || !Number.isFinite(value)) continue
        xMin = Math.min(xMin, value)
        xMax = Math.max(xMax, value)
      }
      for (const value of Array.isArray(trace.y) ? trace.y : []) {
        if (typeof value !== 'number' || !Number.isFinite(value)) continue
        yMin = Math.min(yMin, value)
        yMax = Math.max(yMax, value)
      }
    }
    if (!Number.isFinite(xMin) || !Number.isFinite(xMax)) return figure
    const xPadding = Math.max(xMax - xMin, 1) * 0.06
    const yPadding = Math.max(yMax - yMin, 1) * 0.12
    const xAxis = figure.layout.xaxis as Record<string, unknown>
    const yAxis = figure.layout.yaxis as Record<string, unknown>
    // Stable display limits make pixel label placement independent of annotation autoranging.
    const xRange = (xAxis.range as number[] | undefined) ?? [xMin - xPadding, xMax + xPadding]
    const yRange = (yAxis.range as number[] | undefined) ?? [
      yMin < 0 ? yMin - yPadding : 0,
      yMax + yPadding,
    ]
    Object.assign(xAxis, { range: xRange, autorange: false })
    Object.assign(yAxis, { range: yRange, autorange: false })
    ;[xMin, xMax] = [xRange[0]!, xRange[1]!]
    ;[yMin, yMax] = [yRange[0]!, yRange[1]!]
    const xSpan = Math.max(xMax - xMin, Number.EPSILON)
    const ySpan = Math.max(yMax - yMin, Number.EPSILON)
    const measured = document.createElement('canvas').getContext('2d')
    type LabelBox = { left: number; right: number; top: number; bottom: number }
    const boxes: LabelBox[] = []
    let ordinary = 0
    for (const label of textLabels.sort((a, b) => b.priority - a.priority || b.y - a.y)) {
      if (!label.priority && ordinary >= 30) continue
      const font = label.font as { size?: number; family?: string } | undefined
      const fontSize = font?.size ?? 10
      if (measured) measured.font = `${fontSize}px ${font?.family ?? 'Arial, sans-serif'}`
      const lines = label.text.split(/<br\s*\/?\s*>/i)
      const boxWidth = Math.min(
        plotWidth - 4,
        Math.max(
          ...lines.map(
            (line) =>
              measured?.measureText(line.replace(/<[^>]*>/g, '')).width ??
              line.length * fontSize * 0.6,
          ),
        ) + 8,
      )
      const boxHeight = Math.min(plotHeight, lines.length * fontSize * 1.3 + 6)
      const peakX = ((label.x - xMin) / xSpan) * plotWidth
      const peakY = plotHeight - ((label.y - yMin) / ySpan) * plotHeight
      if (peakX < 0 || peakX > plotWidth || peakY < 0 || peakY > plotHeight) continue
      const centerX = Math.max(boxWidth / 2 + 2, Math.min(plotWidth - boxWidth / 2 - 2, peakX))
      const bottom = Math.max(boxHeight, Math.min(plotHeight - 2, peakY - 10))
      let placement: LabelBox | undefined
      for (let displacement = 0; displacement <= plotHeight; displacement += 16) {
        for (const direction of [1, -1]) {
          const candidateBottom = bottom + displacement * direction
          if (candidateBottom > plotHeight - 2 || candidateBottom - boxHeight < 0) continue
          const candidate = {
            left: centerX - boxWidth / 2,
            right: centerX + boxWidth / 2,
            top: candidateBottom - boxHeight,
            bottom: candidateBottom,
          }
          if (
            boxes.every(
              (box) =>
                candidate.right + 5 < box.left ||
                candidate.left > box.right + 5 ||
                candidate.bottom + 12 < box.top ||
                candidate.top > box.bottom + 12,
            )
          ) {
            placement = candidate
            break
          }
        }
        if (placement) break
      }
      if (!placement) continue
      boxes.push(placement)
      if (!label.priority) ordinary++
      ;(figure.layout.annotations as Record<string, unknown>[]).push({
        x: label.x,
        y: label.y,
        text: label.text,
        showarrow: true,
        arrowhead: 0,
        arrowwidth: 0.5,
        arrowcolor: '#9aa1aa',
        ax: centerX - peakX,
        ay: placement.bottom - peakY,
        font: label.font ?? { size: 10 },
        xanchor: 'center',
        yanchor: 'bottom',
      })
    }
  }
  if (settings.labels && !labelsProvided && peaks.length) {
    const masses = peaks.map((peak) => peak.x)
    const span =
      masses.reduce((top, value) => Math.max(top, value), -Infinity) -
      masses.reduce((bottom, value) => Math.min(bottom, value), Infinity)
    const selected: typeof peaks = []
    const distance = span * Math.min(0.15, 72 / Math.max(width, 320))
    for (const peak of peaks.sort((a, b) => b.y - a.y)) {
      if (selected.length >= 35) break
      if (selected.some((other) => Math.abs(other.x - peak.x) < distance)) continue
      selected.push(peak)
    }
    ;(figure.layout.annotations as Record<string, unknown>[]).push(
      ...selected.map((peak) => ({
        x: peak.x,
        y: peak.y,
        text: peak.x.toFixed(decimals),
        showarrow: false,
        yshift: 9,
        font: { family: 'Arial, sans-serif', size: 11, color: '#222222' },
        xanchor: 'center',
        yanchor: 'bottom',
      })),
    )
  }
  return figure
}
