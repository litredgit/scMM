<script setup lang="ts">
import {
  ref,
  watch,
  onMounted,
  onBeforeUnmount,
  onActivated,
  onDeactivated,
  nextTick,
  computed,
} from 'vue'
import { useWorkspace } from '../stores/workspace'
import type { Figure } from '../api/types'
const props = withDefaults(
  defineProps<{
    figure: Figure
    legend?: string
    name?: string
    viewKey?: string
    selectRange?: boolean
  }>(),
  {
    legend: 'right',
    name: 'scmm',
  },
)
const store = useWorkspace()
const chartKey = computed(
  () =>
    props.viewKey ??
    (
      {
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
      } as Record<string, string>
    )[props.name] ??
    props.name,
)
const chartWidth = ref(900)
const chartKind = computed(() =>
  chartKey.value.includes('embedding')
    ? 'embedding'
    : props.name.replace(/^raw-/, '').replace(/_plot$/, ''),
)
const chartHeight = computed(() => {
  const width = chartWidth.value
  if (['tic', 'eic', 'sum', 'single', 'cells'].includes(chartKind.value))
    return Math.max(320, Math.min(600, width / 2.2))
  if (['roc', 'pr', 'calibration'].includes(chartKind.value))
    return Math.max(360, Math.min(820, width * 0.9))
  if (chartKind.value === 'violin') return Math.max(380, Number(props.figure.layout.height) || 380)
  if (chartKind.value === 'shap') {
    const traces = props.figure.data as { y?: unknown[] }[]
    return Math.max(
      400,
      Math.min(1200, 140 + 28 * Math.max(0, ...traces.map((t) => t.y?.length ?? 0))),
    )
  }
  return Math.max(360, Math.min(800, width * (chartKind.value === 'network' ? 0.9 : 0.7)))
})
const position = computed(() => store.project?.presentation[chartKey.value] ?? props.legend)
function changeLegend(event: Event) {
  void store.mutate(
    '/presentation',
    { key: chartKey.value, position: (event.target as HTMLSelectElement).value },
    'PUT',
  )
}
const emit = defineEmits<{ select: [feature: string]; range: [range: [number, number]] }>()
const element = ref<HTMLElement>()
const failure = ref('')
const filename = ref(props.name)
watch(
  () => props.name,
  (name) => (filename.value = name),
)
let plotly: (typeof import('plotly.js-dist-min'))['default'] | undefined
let observer: ResizeObserver | undefined
let active = true
let generation = 0
let chain: Promise<unknown> = Promise.resolve()
async function draw() {
  const token = ++generation
  try {
    plotly ??= (await import('plotly.js-dist-min')).default
    if (!active || !element.value || token !== generation) return
    const copy = JSON.parse(JSON.stringify(props.figure)) as Figure
    const selectedPosition = position.value
    const outside = selectedPosition === 'right'
    const narrow = chartWidth.value < 680
    const inside = !outside
    const below = outside && narrow
    const right = selectedPosition.endsWith('right'),
      bottom = selectedPosition.startsWith('bottom')
    const legend = inside
      ? {
          x: right ? 0.99 : 0.01,
          y: bottom ? 0.01 : 0.99,
          xanchor: right ? 'right' : 'left',
          yanchor: bottom ? 'bottom' : 'top',
          bgcolor: 'rgba(255,255,255,0.8)',
        }
      : below
        ? { x: 0, y: -0.22, xanchor: 'left', yanchor: 'top', orientation: 'h' }
        : { x: 1.02, y: 1, xanchor: 'left', yanchor: 'top' }
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
      font: { family: 'Inter, Microsoft YaHei, system-ui, sans-serif', size: 14, color: '#21304a' },
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
        ...legend,
        title: { text: '' },
        font: { size: 14 },
        itemwidth: 30,
        maxheight: below ? 0.3 : 1,
      },
      uirevision: props.name,
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
      const matches = fileNames.filter((n) => n.replace(/\\/g, '/').split('/').at(-1) === basename)
      displayNames.set(
        original,
        matches.length > 1 ? `${basename}（${matches.indexOf(original) + 1}）` : basename,
      )
    }
    for (const trace of copy.data as Record<string, unknown>[]) {
      if (typeof trace.name === 'string' && displayNames.has(trace.name))
        trace.name = displayNames.get(trace.name)

      const marker = trace.marker as Record<string, unknown> | undefined
      if (marker && 'colorbar' in marker) marker.showscale = selectedPosition !== 'hidden'
      if (marker && 'colorbar' in marker)
        marker.colorbar = {
          ...(marker.colorbar as object),
          x: inside ? (right ? 0.98 : 0.02) : 1.02,
          xanchor: inside && right ? 'right' : 'left',
          len: inside ? 0.65 : 1,
        }
    }
    const axes = copy.layout.coloraxis as Record<string, unknown> | undefined
    if (axes) {
      axes.showscale = selectedPosition !== 'hidden'
      axes.colorbar = {
        ...(axes.colorbar as object),
        x: inside ? (right ? 0.98 : 0.02) : 1.02,
        xanchor: inside && right ? 'right' : 'left',
        len: inside ? 0.65 : 1,
      }
    }
    chain = chain
      .catch(() => undefined)
      .then(async () => {
        if (!active || !element.value || token !== generation) return
        failure.value = ''
        await plotly!.react(element.value, copy.data, copy.layout, {
          responsive: true,
          displaylogo: false,
          modeBarButtonsToRemove: [
            'sendDataToCloud',
            'editInChartStudio',
            'share',
            'sendChartToCloud',
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
        graph.removeAllListeners?.('plotly_click')
        graph.on?.('plotly_click', (data) => {
          const id = data.points?.[0]?.customdata?.[0]
          if (id) emit('select', id)
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
  () => [props.figure, position.value, props.selectRange, chartHeight.value],
  () => void draw(),
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
function image(format: string) {
  if (element.value)
    void plotly?.downloadImage(element.value, {
      format,
      filename: filename.value || props.name,
      width: chartWidth.value,
      height: chartHeight.value,
      scale: format === 'png' ? 2 : 1,
    })
}
</script>
<template>
  <div class="plot-shell">
    <div class="plot-actions">
      <label class="field"
        ><FieldLabel name="图例位置" /><select
          :value="position"
          :disabled="store.busy"
          :aria-label="`图例位置：${name}`"
          @change="changeLegend"
        >
          <option value="right">图右侧</option>
          <option value="top_left">图内左上</option>
          <option value="top_right">图内右上</option>
          <option value="bottom_left">图内左下</option>
          <option value="bottom_right">图内右下</option>
          <option value="hidden">隐藏</option>
        </select></label
      >
      <label
        ><FieldLabel name="图文件名" /><input v-model="filename" :aria-label="`图文件名：${name}`"
      /></label>
      <button class="save" @click="image('svg')">下载 SVG</button
      ><button class="save" @click="image('png')">下载 PNG</button>
    </div>
    <p v-if="failure" role="alert">{{ failure }}</p>
    <div
      ref="element"
      class="plot"
      :style="{ height: `${chartHeight}px` }"
      aria-label="交互图表"
    ></div>
  </div>
</template>
