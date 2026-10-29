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
import type { useWorkspace } from '../stores/workspace'

type RenderOptions = {
  props: { figure: Figure; name: string; selectRange?: boolean; compact?: boolean }
  store: ReturnType<typeof useWorkspace>
  element: Ref<HTMLElement | undefined>
  failure: Ref<string>
  orderedFigure: () => Figure
  viewport: Ref<Record<string, unknown>>
  position: ComputedRef<string>
  chartWidth: Ref<number>
  chartHeight: ComputedRef<number>
  chartKind: ComputedRef<string>
  exporting: Ref<boolean>
  fresh: ComputedRef<boolean>
  image: (format: string) => Promise<void>
  emit: {
    (event: 'select', value: string): void
    (event: 'range', value: [number, number]): void
    (event: 'viewport', value: Record<string, unknown>): void
  }
  legendItems: Ref<string[]>
  pointOpacity: Ref<number>
  traceVisibility: Ref<(boolean | string)[]>
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
  exporting,
  fresh,
  image,
  emit,
  legendItems,
  pointOpacity,
  traceVisibility,
}: RenderOptions) {
  let plotly: (typeof import('plotly.js-dist-min'))['default'] | undefined
  let observer: ResizeObserver | undefined
  let active = true
  let generation = 0
  let figureRevision = 0
  let chain: Promise<unknown> = Promise.resolve()
  async function draw() {
    const token = ++generation
    try {
      plotly ??= (await import('plotly.js-dist-min')).default
      if (!active || !element.value || token !== generation) return
      const copy = orderedFigure()
      applyViewport(copy, viewport.value)
      const selectedPosition = position.value
      const outside = selectedPosition === 'right'
      const narrow = chartWidth.value < 680
      const inside = !outside
      const below = outside && narrow
      const originalTitle = copy.layout.title as { text?: string } | string | undefined
      const title = (typeof originalTitle === 'string' ? originalTitle : originalTitle?.text) ?? ''
      const wrap = Math.max(12, Math.floor((chartWidth.value - 35) / 18))
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
          family: 'Inter, Microsoft YaHei, system-ui, sans-serif',
          size: 14,
          color: '#21304a',
        },
        title: {
          ...(typeof copy.layout.title === 'object'
            ? (copy.layout.title as object)
            : { text: copy.layout.title }),
          text: titleText,
          font: { size: 20 },
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
        dragmode: props.selectRange ? 'select' : 'zoom',
        selectdirection: props.selectRange ? 'h' : undefined,
        margin: {
          ...((copy.layout.margin ?? {}) as object),
          l: 80,
          r: inside || below ? 35 : Math.min(260, Math.max(120, chartWidth.value * 0.24)),
          t: narrow && titleText?.includes('<br>') ? 100 : 75,
          b: below ? 130 : 70,
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
            modeBarButtonsToAdd: props.compact
              ? []
              : [
                  {
                    name: '下载论文 SVG',
                    icon: {
                      width: 24,
                      height: 24,
                      path: 'M3 3H21V21H3ZM7 7V17H17V7ZM11 8H13V13H15L12 16L9 13H11Z',
                    },
                    click: () => {
                      if (!exporting.value && !store.busy && fresh.value) void image('svg')
                    },
                  },
                ],
            locale: 'zh-CN',
            scrollZoom: true,
            toImageButtonOptions: {
              format: 'svg',
              filename: props.name,
              width: chartWidth.value,
              height: chartHeight.value,
            },
          })
          const graph = element.value as HTMLElement & {
            on?: (
              name: string,
              callback: (data: {
                points?: { customdata?: string[] }[]
                range?: { x?: [number, number] }
              }) => void,
            ) => void
            removeAllListeners?: (name: string) => void
          }
          graph.removeAllListeners?.('plotly_relayout')
          graph.on?.('plotly_relayout', () => {
            const layout = (graph as unknown as { layout?: Record<string, unknown> }).layout
            if (layout) {
              viewport.value = readViewport(layout)
              emit('viewport', viewport.value)
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
            const id = data.points?.[0]?.customdata?.[0]
            if (id) {
              const meta = props.figure.layout.meta as Record<string, unknown> | undefined
              if (meta?.point_kind === 'cell' && fresh.value) store.selectCell(id)
              else emit('select', id)
            }
          })
          graph.removeAllListeners?.('plotly_selected')
          graph.on?.('plotly_selected', (data) => {
            if (props.selectRange && data?.range?.x) emit('range', data.range.x)
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
