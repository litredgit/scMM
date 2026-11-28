import {
  watch,
  onMounted,
  onActivated,
  onDeactivated,
  onBeforeUnmount,
  nextTick,
  type Ref,
  type ComputedRef,
} from 'vue'
import type { Figure } from '../api/types'
import { applyViewport, readViewport } from './plotViewport'
import { applyLegend } from './plotPresentation'
import { isMassSpectrum, type SpectrumSettings } from './spectrumPresentation'
import type { useWorkspace } from '../stores/workspace'

type RenderOptions = {
  props: { figure: Figure; name: string; selectRange?: boolean; compact?: boolean }
  store: ReturnType<typeof useWorkspace>
  element: Ref<HTMLElement | undefined>
  failure: Ref<string>
  orderedFigure: (viewport?: Record<string, unknown>) => Figure
  viewport: Ref<Record<string, unknown>>
  position: ComputedRef<string>
  chartWidth: Ref<number>
  chartHeight: ComputedRef<number>
  chartKind: ComputedRef<string>
  fresh: ComputedRef<boolean>
  emit: {
    (event: 'selection', value: string[]): void
    (event: 'select', value: string): void
    (event: 'range', value: [number, number]): void
    (event: 'viewport', value: Record<string, unknown>): void
    (
      event: 'point-click',
      value: {
        points: {
          customdata?: unknown
          x?: number
          y?: number
          pointIndex?: number
          pointNumber?: number
          curveNumber?: number
        }[]
        xUnitsPerPixel?: number
      },
    ): void
  }
  legendItems: Ref<string[]>
  pointOpacity: Ref<number>
  traceVisibility: Ref<(boolean | string)[]>
  spectrumSettings: Ref<SpectrumSettings>
  spectrumHistory: Ref<Record<string, unknown>[]>
}

export function usePlotRenderer({
  props,
  store,
  element,
  failure,
  orderedFigure,
  viewport,
  position,
  chartWidth,
  chartHeight,
  chartKind,
  fresh,
  emit,
  legendItems,
  pointOpacity,
  traceVisibility,
  spectrumSettings,
  spectrumHistory,
}: RenderOptions) {
  let plotly: (typeof import('plotly.js-strict-dist-min'))['default'] | undefined
  let observer: ResizeObserver | undefined
  let active = true
  let generation = 0
  let figureRevision = 0
  let chain: Promise<unknown> = Promise.resolve()
  async function draw() {
    const token = ++generation
    try {
      plotly ??= (await import('plotly.js-strict-dist-min')).default
      if (!active || !element.value || token !== generation) return
      const copy = orderedFigure(viewport.value)
      const spectrum = isMassSpectrum(copy)
      const nativeStyle =
        spectrum ||
        (copy.layout.meta as Record<string, unknown> | undefined)?.scmm_chromatogram === true
      if (!spectrum) applyViewport(copy, viewport.value)
      const selectedPosition = position.value
      const outside = selectedPosition === 'right'
      const narrow = chartWidth.value < 680
      const inside = !outside
      const below = outside && narrow
      const originalTitle = copy.layout.title as { text?: string } | string | undefined
      const title = (typeof originalTitle === 'string' ? originalTitle : originalTitle?.text) ?? ''
      const wrap = Math.max(12, Math.floor((chartWidth.value - 35) / (spectrum ? 7.5 : 18)))
      const titleText =
        narrow && !title.includes('<br>')
          ? title.match(new RegExp(`.{1,${wrap}}`, 'g'))?.join('<br>')
          : title
      copy.layout = {
        ...copy.layout,
        autosize: true,
        width: undefined,
        height: chartHeight.value,
        font: {
          family: nativeStyle
            ? 'Arial, sans-serif'
            : 'Inter, Microsoft YaHei, system-ui, sans-serif',
          size: nativeStyle ? 12 : 14,
          color: spectrum ? '#222222' : '#21304a',
        },
        title: {
          ...(typeof copy.layout.title === 'object'
            ? (copy.layout.title as object)
            : { text: copy.layout.title }),
          text: titleText,
          font: { size: nativeStyle ? 13 : 20 },
          x: 0.02,
          xanchor: 'left',
          automargin: true,
        },
        showlegend: selectedPosition !== 'hidden',
        legend: {
          traceorder: 'normal',
          title: { text: '' },
          font: { size: 14 },
          itemwidth: 30,
          maxheight: below ? 0.3 : 1,
        },
        uirevision: `${props.name}:${figureRevision}`,
        dragmode: props.selectRange
          ? 'select'
          : (copy.layout.meta as Record<string, unknown> | undefined)?.point_kind ===
              'cell_selection'
            ? 'lasso'
            : spectrum
              ? spectrumSettings.value.interaction
              : 'zoom',
        selectdirection: props.selectRange ? 'h' : undefined,
        margin: {
          ...((copy.layout.margin ?? {}) as object),
          l: spectrum ? 65 : 80,
          r: inside || below ? 35 : Math.min(260, Math.max(120, chartWidth.value * 0.24)),
          t: spectrum
            ? 40 + (titleText?.match(/<br>/g)?.length ?? 0) * 16
            : narrow && titleText?.includes('<br>')
              ? 100
              : 75,
          b: below ? 130 : spectrum ? 55 : 70,
        },
      }
      for (const [key, value] of Object.entries(copy.layout)) {
        if (/^[xy]axis\d*$/.test(key) && value && typeof value === 'object')
          (value as Record<string, unknown>).automargin = true
      }
      if (['roc', 'pr', 'calibration'].includes(chartKind.value)) {
        const x = (copy.layout.xaxis ?? {}) as Record<string, unknown>
        copy.layout.xaxis = { ...x, constrain: 'domain' }
        const y = (copy.layout.yaxis ?? {}) as Record<string, unknown>
        copy.layout.yaxis = { ...y, scaleanchor: 'x', scaleratio: 1, constrain: 'domain' }
      }
      const names = [
        ...new Set(
          (copy.data as { name?: string }[]).map((t) => t.name).filter((n): n is string => !!n),
        ),
      ]
      const displayNames = new Map<string, string>()
      const fileNames = names.filter((n) => /^[/\\]|^[a-z]:[/\\]/i.test(n))
      for (const original of fileNames) {
        const basename = original.replace(/\\/g, '/').split('/').at(-1) || original
        const matches = fileNames.filter(
          (n) => n.replace(/\\/g, '/').split('/').at(-1) === basename,
        )
        displayNames.set(
          original,
          matches.length > 1 ? `${basename}（${matches.indexOf(original) + 1}）` : basename,
        )
      }
      for (const trace of copy.data as Record<string, unknown>[]) {
        if (typeof trace.name === 'string' && displayNames.has(trace.name))
          trace.name = displayNames.get(trace.name)
      }
      applyLegend(copy, selectedPosition, narrow)
      chain = chain
        .catch(() => undefined)
        .then(async () => {
          if (!active || !element.value || token !== generation) return
          failure.value = ''
          await plotly!.react(element.value, copy.data, copy.layout, {
            responsive: true,
            displaylogo: false,
            modeBarButtonsToRemove: [
              'toImage',
              'sendDataToCloud',
              'editInChartStudio',
              'share',
              'sendChartToCloud',
              ...(props.compact
                ? ['select2d', 'lasso2d', 'toggleSpikelines', 'hoverCompareCartesian']
                : []),
            ],
            locale: 'zh-CN',
            scrollZoom: true,
          })
          const graph = element.value as HTMLElement & {
            on?: (
              name: string,
              callback: (data: {
                points?: {
                  customdata?: unknown
                  x?: number
                  y?: number
                  pointIndex?: number
                  pointNumber?: number
                  curveNumber?: number
                }[]
                range?: { x?: [number, number] }
              }) => void,
            ) => void
            removeAllListeners?: (name: string) => void
          }
          graph.removeAllListeners?.('plotly_relayout')
          graph.on?.('plotly_relayout', () => {
            const layout = (graph as unknown as { layout?: Record<string, unknown> }).layout
            if (layout) {
              const next = readViewport(layout)
              const changed = JSON.stringify(viewport.value) !== JSON.stringify(next)
              if (spectrum && changed)
                spectrumHistory.value = [...spectrumHistory.value.slice(-19), { ...viewport.value }]
              viewport.value = next
              emit('viewport', viewport.value)
              if (spectrum && changed) void draw()
            }
          })
          graph.removeAllListeners?.('plotly_restyle')
          graph.on?.('plotly_restyle', () => {
            traceVisibility.value = (
              (graph as unknown as { data?: { visible?: boolean | string }[] }).data ?? []
            ).map((t) => t.visible ?? true)
          })
          graph.removeAllListeners?.('plotly_click')
          graph.on?.('plotly_click', (data) => {
            if (!fresh.value) return
            const axis = (
              graph as unknown as {
                _fullLayout?: { xaxis?: { range?: number[]; _length?: number } }
              }
            )._fullLayout?.xaxis
            const range = axis?.range
            const xUnitsPerPixel =
              range?.length === 2 && axis?._length
                ? Math.abs(range[1]! - range[0]!) / axis._length
                : undefined
            emit('point-click', { points: data.points ?? [], xUnitsPerPixel })
            const customdata = data.points?.[0]?.customdata
            const id = Array.isArray(customdata)
              ? customdata[0]
              : typeof customdata === 'string'
                ? customdata
                : undefined
            if (id) {
              const meta = props.figure.layout.meta as Record<string, unknown> | undefined
              if (['cell', 'sample'].includes(String(meta?.point_kind)) && fresh.value)
                store.selectCell(id)
              else emit('select', id)
            }
          })
          graph.removeAllListeners?.('plotly_selected')
          graph.on?.('plotly_selected', (data) => {
            if (props.selectRange && data?.range?.x) emit('range', data.range.x)
            const meta = props.figure.layout.meta as Record<string, unknown> | undefined
            if (meta?.point_kind === 'cell_selection' && fresh.value) {
              emit(
                'selection',
                (data.points ?? [])
                  .map((point) =>
                    Array.isArray(point.customdata) ? point.customdata[0] : undefined,
                  )
                  .filter((id): id is string => !!id),
              )
            }
          })
        })
      await chain
    } catch (cause) {
      failure.value = String(cause)
    }
  }
  watch(
    () => [
      props.figure,
      position.value,
      props.selectRange,
      chartHeight.value,
      legendItems.value,
      pointOpacity.value,
    ],
    (value, previous) => {
      if (value[0] !== previous?.[0]) figureRevision++
      void draw()
    },
    { deep: false },
  )
  onMounted(() => {
    observer = new ResizeObserver(() => {
      if (active && element.value?.clientWidth) {
        const width = Math.round(element.value.clientWidth)
        if (width !== chartWidth.value) {
          chartWidth.value = width
          void draw()
        }
      }
    })
    if (element.value) {
      chartWidth.value = Math.round(element.value.clientWidth) || 900
      observer.observe(element.value)
    }
    void draw()
  })
  onActivated(() => {
    active = true
    void nextTick(() => {
      chartWidth.value = Math.round(element.value?.clientWidth || 900)
      void draw()
    })
  })
  onDeactivated(() => {
    active = false
    ++generation
  })
  onBeforeUnmount(() => {
    active = false
    ++generation
    observer?.disconnect()
    if (element.value) plotly?.purge(element.value)
  })

  return {
    plotly: () => plotly,
    retry: draw,
    currentViewport: () => {
      const layout = (element.value as unknown as { layout?: Record<string, unknown> })?.layout
      return layout ? readViewport(layout) : viewport.value
    },
    visibility: () =>
      ((element.value as unknown as { data?: { visible?: boolean | string }[] })?.data ?? []).map(
        (t) => t.visible ?? true,
      ),
  }
}
