<script setup lang="ts">
import { ref, shallowRef, watch, computed } from 'vue'
import { usePlotRenderer } from './usePlotRenderer'
import LegendOrder from './LegendOrder.vue'
import ImageExportDialog from './ImageExportDialog.vue'
import resultContract from '../features/analysis/results.contract.json'
import { useLegendOrder } from './useLegendOrder'
import { useViewState, restoringViews } from '../api/viewState'
import { applyViewport } from './plotViewport'
import { applyLegend, copyFigure, plotChartKey, plotHeight } from './plotPresentation'
import { isMassSpectrum, spectrumPresentation, type SpectrumSettings } from './spectrumPresentation'
import { systemPlotText } from './systemPlotText'
import { useWorkspace } from '../stores/workspace'
import type { Figure } from '../api/types'
import { openCsvExport } from '../api/csvExport'
import { workspaceBlob } from '../api/workspaceDownload'
import { pngWithDpi, type ImageFormat } from './plotExport'
const props = withDefaults(
  defineProps<{
    figure: Figure
    legend?: string
    name?: string
    viewKey?: string
    selectRange?: boolean
    compact?: boolean
    readonly?: boolean
    linkedViewport?: Record<string, unknown>
  }>(),
  {
    legend: 'right',
    name: 'scmm',
  },
)
const store = useWorkspace()
const spectrum = computed(() => isMassSpectrum(props.figure))
const intensityMissing = computed(
  () =>
    (props.figure.layout.meta as Record<string, unknown> | undefined)?.intensity_missing === true,
)
const relativeIntensityAllowed = computed(
  () =>
    !intensityMissing.value &&
    (props.figure.layout.meta as Record<string, unknown> | undefined)
      ?.relative_intensity_allowed !== false,
)
const spectrumSettings = ref<SpectrumSettings>({
  relative: false,
  labels: true,
  decimals: 4,
  threshold: 1,
  interaction: 'zoom',
})
const intensityMode = computed({
  get: () => (relativeIntensityAllowed.value ? spectrumSettings.value.relative : false),
  set: (relative: boolean) => {
    spectrumSettings.value.relative = relative
  },
})
const spectrumHistory = ref<Record<string, unknown>[]>([])
const spectrumDescription = computed(() => {
  const meta = (props.figure.layout.meta ?? {}) as Record<string, unknown>
  const detail = (meta.detail ?? {}) as Record<string, unknown>
  const parts: string[] = []
  if (detail.native_id) parts.push(String(detail.native_id))
  if (detail.rt_seconds !== undefined) parts.push(`RT ${Number(detail.rt_seconds).toFixed(3)} s`)
  if (detail.ms_level !== undefined) parts.push(`MS${detail.ms_level}`)
  parts.push(
    intensityMissing.value
      ? 'Feature positions · intensity not supplied'
      : meta.source === 'matrix_feature_stems_not_raw_profile' ||
          meta.source === 'feature_sticks' ||
          meta.spectrum_kind === 'feature_sticks'
        ? 'Feature spectrum'
        : 'Mass spectrum',
  )
  return parts.join(' · ')
})
const chartKey = computed(() => plotChartKey(props.name, props.viewKey))
const labeledFigure = computed(() => systemPlotText(copyFigure(props.figure), chartKey.value))
const legendNames = computed(() =>
  (labeledFigure.value.data as { name?: string; showlegend?: boolean }[])
    .filter((t) => t.showlegend !== false && t.name)
    .map((t) => t.name!),
)
const {
  items: legendItems,
  move: moveLegend,
  reset: resetLegend,
} = useLegendOrder(chartKey, legendNames, () => !!props.readonly)
function orderedFigure(view: Record<string, unknown> = {}, full = false): Figure {
  const copy = copyFigure(labeledFigure.value)
  if (full && (copy.layout.meta as Record<string, unknown> | undefined)?.spectrum_local) {
    const xaxis = copy.layout.xaxis as Record<string, unknown>
    delete xaxis.range
    xaxis.autorange = true
  }
  for (const [index, trace] of (copy.data as Record<string, unknown>[]).entries()) {
    if (traceVisibility.value[index] !== undefined) trace.visible = traceVisibility.value[index]
    if (typeof trace.name === 'string') trace.legendrank = legendItems.value.indexOf(trace.name)
    if (
      ['scatter', 'scattergl', 'scatter3d'].includes(String(trace.type)) &&
      String(trace.mode ?? 'markers').includes('markers')
    ) {
      trace.marker = { ...(trace.marker as object), opacity: pointOpacity.value }
    }
  }
  copy.layout.legend = { ...(copy.layout.legend as object), traceorder: 'normal' }
  return spectrumPresentation(
    copy,
    spectrumSettings.value,
    chartWidth.value,
    chartHeight.value,
    position.value,
    view,
  )
}
const chartWidth = ref(900)
const chartKind = computed(() =>
  chartKey.value.includes('embedding')
    ? 'embedding'
    : props.name.replace(/^raw-/, '').replace(/_plot$/, ''),
)
const chartHeight = computed(() =>
  plotHeight(props.figure, props.name, chartKind.value, chartWidth.value, spectrum.value),
)
const localPosition = ref(props.legend)
const position = computed(() =>
  props.readonly || !store.project
    ? localPosition.value
    : (store.project.presentation[chartKey.value] ?? props.legend),
)
function changeLegend(event: Event) {
  const next = (event.target as HTMLSelectElement).value
  if (next === position.value) return
  if (props.readonly || !store.project) {
    localPosition.value = next
    return
  }
  void store.mutate('/presentation', { key: chartKey.value, position: next }, 'PUT')
}
const emit = defineEmits<{
  selection: [cells: string[]]
  select: [feature: string]
  range: [range: [number, number]]
  viewport: [value: Record<string, unknown>]
  'point-click': [
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
  ]
}>()
const element = ref<HTMLElement>()
const failure = ref('')
const filename = ref(props.name)
const widthMm = ref(89),
  heightMm = ref(65),
  dpi = ref(300),
  fontPt = ref(7)
const viewport = ref<Record<string, unknown>>({})
const spectrumViewports = new Map<string, Record<string, unknown>>()
const traceVisibility = ref<(boolean | string)[]>([])
const fresh = computed(() => {
  const meta = props.figure.layout.meta as
    | { dataset_token?: unknown[]; result_identity?: string; result_identity_valid?: boolean }
    | undefined
  const resultKinds = Object.values(resultContract.resultPlots).flat()
  const kind = chartKey.value.split('.').at(-1) ?? props.name
  if (
    meta?.result_identity_valid === false ||
    (resultKinds.includes(kind) && !meta?.result_identity)
  )
    return false
  const token = meta?.dataset_token
  return (
    !token ||
    JSON.stringify(token) ===
      JSON.stringify([store.project?.dataset?.id, store.project?.dataset?.revision])
  )
})
const imageDialog = ref<InstanceType<typeof ImageExportDialog>>()
const preset = ref('nature-single')
const pointOpacity = ref(1)
const artwork = ref('color')
const includeTitle = ref(true)
const fontFamily = ref('Arial, Helvetica, Microsoft YaHei, sans-serif')
const lineWidth = ref(0.7)
const transparent = ref(false)
const exportRange = ref('current')
const exportTitle = ref(''),
  exportX = ref(''),
  exportY = ref('')
useViewState(`plot:${chartKey.value}`, {
  filename,
  widthMm,
  heightMm,
  dpi,
  fontPt,
  preset,
  localPosition,
  viewport,
  traceVisibility,
  exportRange,
  exportTitle,
  exportX,
  exportY,
  pointOpacity,
  artwork,
  includeTitle,
  fontFamily,
  lineWidth,
  transparent,
  spectrumSettings,
})
function changeSpectrum() {
  if (!restoringViews) {
    const next = { ...viewport.value }
    delete next['yaxis.range']
    next['yaxis.autorange'] = true
    viewport.value = next
  }
  void renderer.retry()
}
function focusMz(mz: number) {
  const width = Math.max(mz * 0.001, 0.05)
  spectrumHistory.value.push({ ...viewport.value })
  viewport.value = {
    'xaxis.range': [mz - width, mz + width],
    'xaxis.autorange': false,
    'yaxis.autorange': true,
  }
  void renderer.retry()
}
defineExpose({ focusMz })

function spectrumView(action: 'reset' | 'back' | 'y-in' | 'y-out') {
  if (action === 'back') {
    const previous = spectrumHistory.value.pop()
    viewport.value =
      previous && Object.keys(previous).length
        ? previous
        : { 'xaxis.autorange': true, 'yaxis.autorange': true }
  } else if (action === 'reset') {
    spectrumHistory.value.push({ ...viewport.value })
    viewport.value = { 'xaxis.autorange': true, 'yaxis.autorange': true }
  } else {
    const current = renderer.currentViewport()
    const range = current['yaxis.range'] as number[] | undefined
    if (!range || range.length !== 2) return
    spectrumHistory.value.push({ ...current })
    const factor = action === 'y-in' ? 0.5 : 2
    viewport.value = {
      ...current,
      'yaxis.range': [range[0], Number(range[0]) + (Number(range[1]) - Number(range[0])) * factor],
      'yaxis.autorange': false,
    }
  }
  void renderer.retry()
}
function paperPreset() {
  const values: Record<string, [number, number]> = {
    'nature-single': [89, 65],
    'nature-double': [183, 120],
    'cell-single': [85, 65],
    'cell-onehalf': [114, 85],
    'cell-double': [174, 120],
  }
  const size = values[preset.value]
  if (size) [widthMm.value, heightMm.value] = size
  if (preset.value.startsWith('cell-')) {
    fontPt.value = 7
    includeTitle.value = false
    dpi.value = artwork.value === 'line' ? 1000 : artwork.value === 'bw' ? 500 : 300
  }
}
watch(preset, (value) => {
  if (value.startsWith('acs-')) {
    preset.value = 'nature-single'
    paperPreset()
  }
})
watch(artwork, () => {
  dpi.value = artwork.value === 'line' ? 1000 : artwork.value === 'bw' ? 500 : 300
})
watch(
  () => props.figure,
  (figure, previous) => {
    if (!restoringViews) {
      const meta = figure.layout.meta as Record<string, unknown> | undefined
      const before = previous?.layout.meta as Record<string, unknown> | undefined
      if (typeof meta?.spectrum_context === 'string') {
        if (meta.spectrum_input !== before?.spectrum_input) spectrumViewports.clear()
        else if (typeof before?.spectrum_context === 'string') {
          spectrumViewports.set(before.spectrum_context, viewport.value)
          if (spectrumViewports.size > 20) {
            const oldest = [...spectrumViewports.keys()].find((key) => key !== 'full')
            if (oldest) spectrumViewports.delete(oldest)
          }
        }
        if (
          meta.spectrum_context !== before?.spectrum_context ||
          meta.spectrum_input !== before?.spectrum_input
        ) {
          viewport.value = spectrumViewports.get(meta.spectrum_context) ?? {}
          spectrumHistory.value = []
        }
        traceVisibility.value = []
        return
      }
      const sameAnnotationInput =
        meta?.scmm_spectrum === true &&
        meta.lipid_version &&
        meta.lipid_version === before?.lipid_version &&
        JSON.stringify(meta.dataset_token) === JSON.stringify(before?.dataset_token)
      if (!sameAnnotationInput) {
        viewport.value = {}
        spectrumHistory.value = []
      }
      traceVisibility.value = []
    }
  },
)
watch(
  () => props.name,
  (name) => (filename.value = name),
)
const renderer = usePlotRenderer({
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
})
watch(
  () => props.linkedViewport,
  (value) => {
    if (!value || !Object.keys(value).length) return
    const next = { ...viewport.value, ...value }
    if (JSON.stringify(next) !== JSON.stringify(viewport.value)) {
      viewport.value = next
      void renderer.retry()
    }
  },
)
function captureSource() {
  const workspace = store.current?.workspace_id ?? ''
  const path = store.project?.path
  const figure = props.figure
  return {
    workspace,
    isCurrent: () =>
      workspace === (store.current?.workspace_id ?? '') &&
      path === store.project?.path &&
      figure === props.figure &&
      fresh.value,
  }
}
const imageSource = shallowRef<ReturnType<typeof captureSource>>()
const exportViewport = shallowRef<Record<string, unknown>>({})
const exportVisibility = shallowRef<(boolean | string)[]>([])
const imageSettings = computed(() =>
  JSON.stringify([
    preset.value,
    widthMm.value,
    heightMm.value,
    dpi.value,
    fontPt.value,
    fontFamily.value,
    lineWidth.value,
    transparent.value,
    pointOpacity.value,
    exportRange.value,
    includeTitle.value,
    exportTitle.value,
    exportX.value,
    exportY.value,
    position.value,
    legendItems.value,
  ]),
)
function figureIdentity(figure: Figure) {
  const metadata = (figure.layout.meta ?? {}) as Record<string, unknown>
  const keys = [
    'dataset_token',
    'result_name',
    'result_identity',
    'result_identity_valid',
    'sample_id',
    'input_identity',
    'annotation_source',
    'annotation_source_identity',
    'annotation_catalog_revision',
    'annotation_grouping_version',
    'lipid_version',
    'lipid_review_revision',
    'time_result_key',
    'time_result_identity',
    'time_plot_inputs',
    'method_result',
    'method_result_identity',
    'batch_spectrum',
  ]
  return Object.fromEntries(
    keys.filter((key) => Object.hasOwn(metadata, key)).map((key) => [key, metadata[key]]),
  )
}
function exportRequest(
  path: string,
  body: Record<string, unknown>,
  source: ReturnType<typeof captureSource>,
  signal?: AbortSignal,
) {
  return workspaceBlob('/figures/' + path, { ...source, method: 'POST', body, signal })
}
function plotData() {
  const source = captureSource()
  const figure = orderedFigure()
  const identity = figureIdentity(figure)
  figure.layout.meta = {
    ...(figure.layout.meta as object),
    publication: {
      width_mm: widthMm.value,
      height_mm: heightMm.value,
      dpi: dpi.value,
      font_pt: fontPt.value,
      font_family: fontFamily.value,
      line_width_pt: lineWidth.value,
      transparent_background: transparent.value,
      language: 'en',
      range: exportRange.value,
      title: exportTitle.value,
      x_label: exportX.value,
      y_label: exportY.value,
      legend: position.value,
      legend_order: [...legendItems.value],
      viewport: renderer.currentViewport(),
      preset: preset.value,
      point_opacity: pointOpacity.value,
      include_title: includeTitle.value,
    },
  }
  openCsvExport({
    filename: (filename.value || props.name) + '-data.zip',
    archive: true,
    isCurrent: source.isCurrent,
    load: (_, signal) => exportRequest('data', { figure }, source, signal),
    verify: () => exportRequest('check', { metadata: identity }, source),
  })
}
function openImage() {
  imageSource.value = captureSource()
  exportViewport.value = renderer.currentViewport()
  exportVisibility.value = renderer.visibility()
  imageDialog.value?.open()
}
function currentImage() {
  return imageSource.value?.isCurrent() === true
}
async function image(format: ImageFormat, signal: AbortSignal) {
  const plotly = renderer.plotly()
  const requestSource = imageSource.value
  if (!plotly || !requestSource) throw new Error('图形尚未渲染完成。')
  const temporary = document.createElement('div')
  temporary.style.cssText = 'position:absolute;left:-100000px;top:0'
  document.body.appendChild(temporary)
  try {
    if (
      ![
        widthMm.value,
        heightMm.value,
        dpi.value,
        fontPt.value,
        pointOpacity.value,
        lineWidth.value,
      ].every(Number.isFinite) ||
      lineWidth.value < 0.2 ||
      lineWidth.value > 5 ||
      pointOpacity.value < 0.1 ||
      pointOpacity.value > 1 ||
      widthMm.value < 20 ||
      widthMm.value > 600 ||
      heightMm.value < 20 ||
      heightMm.value > 600 ||
      dpi.value < 72 ||
      dpi.value > 2400 ||
      fontPt.value < 4.5 ||
      fontPt.value > 24
    )
      throw new Error('请检查成图尺寸、字号和 DPI。')
    const width = (widthMm.value * 96) / 25.4,
      height = (heightMm.value * 96) / 25.4
    if (format === 'png' && width * height * (dpi.value / 96) ** 2 > 60_000_000)
      throw new Error('成图像素过多，请减小尺寸或 DPI。')
    const copy = orderedFigure({}, exportRange.value === 'full')
    const identity = figureIdentity(copy)
    if (exportRange.value === 'current') applyViewport(copy, exportViewport.value, true)
    for (const [i, trace] of (copy.data as Record<string, unknown>[]).entries())
      if (exportVisibility.value[i] !== undefined) trace.visible = exportVisibility.value[i]
    for (const trace of copy.data as Record<string, unknown>[])
      if (trace.type === 'scattergl') trace.type = 'scatter'
    const font = {
      family: preset.value.startsWith('cell-') ? 'Arial' : fontFamily.value,
      size: (fontPt.value * 96) / 72,
      color: '#111111',
    }
    const background = transparent.value && format !== 'pdf' ? 'rgba(0,0,0,0)' : 'white'
    copy.layout = {
      ...copy.layout,
      width,
      height,
      autosize: false,
      paper_bgcolor: background,
      plot_bgcolor: background,
      font,
      margin: { l: 50, r: 25, t: 30, b: 45 },
      legend: { font },
      title: {
        text:
          typeof copy.layout.title === 'string'
            ? copy.layout.title
            : (copy.layout.title as { text?: string })?.text,
        font,
      },
    }
    for (const [name, value] of Object.entries(copy.layout))
      if (/^[xy]axis\d*$/.test(name) && value && typeof value === 'object') {
        const axis = value as Record<string, unknown>
        axis.tickfont = font
        const original = (axis.title as { text?: string })?.text
        axis.title = {
          ...(axis.title as object),
          text: (name.startsWith('x') ? exportX.value : exportY.value) || String(original ?? ''),
          font,
        }
        Object.assign(axis, {
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
          linewidth: (lineWidth.value * 96) / 72,
          ticks: 'outside',
          tickwidth: (lineWidth.value * 96) / 72,
        })
        axis.automargin = true
      }
    const titleText = (copy.layout.title as { text?: string })?.text
    copy.layout.title = {
      ...(copy.layout.title as object),
      text: includeTitle.value ? exportTitle.value || String(titleText ?? '') : '',
    }
    applyLegend(copy, position.value)
    const scene = copy.layout.scene as Record<string, unknown> | undefined
    if (scene)
      for (const name of ['xaxis', 'yaxis', 'zaxis']) {
        const axis = (scene[name] ??= {}) as Record<string, unknown>
        axis.tickfont = font
        axis.title = { ...(axis.title as object), font }
      }
    for (const name of Object.keys(copy.layout))
      if (/^coloraxis\d*$/.test(name)) {
        const axis = copy.layout[name] as Record<string, unknown>
        axis.showscale = position.value !== 'hidden'
        axis.colorbar = {
          ...(axis.colorbar as object),
          tickfont: font,
          title: { ...((axis.colorbar as { title?: object })?.title ?? {}), font },
        }
      }
    for (const trace of copy.data as Record<string, unknown>[]) {
      const bar = trace.colorbar as Record<string, unknown> | undefined
      if (bar)
        trace.colorbar = {
          ...bar,
          tickfont: font,
          title: {
            ...(bar.title as object),
            text: (bar.title as { text?: string })?.text ?? '',
            font,
          },
        }
    }
    for (const annotation of (copy.layout.annotations ?? []) as Record<string, unknown>[])
      annotation.font = font
    for (const trace of copy.data as Record<string, unknown>[]) {
      const marker = trace.marker as Record<string, unknown> | undefined
      if (marker?.colorbar) {
        const bar = marker.colorbar as Record<string, unknown>
        marker.colorbar = { ...bar, tickfont: font, title: { ...(bar.title as object), font } }
      }
    }
    signal.throwIfAborted()
    await plotly.newPlot(temporary, copy.data as never, copy.layout as never, {
      staticPlot: true,
      displayModeBar: false,
    })
    signal.throwIfAborted()
    const url = await plotly.toImage(temporary, {
      format: format === 'png' ? 'png' : 'svg',
      width,
      height,
      scale: format === 'png' ? dpi.value / 96 : 1,
    })
    const rendered = await (await fetch(url)).blob()
    const blob =
      format === 'pdf'
        ? await exportRequest(
            'pdf',
            {
              svg: await rendered.text(),
              width_mm: widthMm.value,
              height_mm: heightMm.value,
              identity,
              font_family: preset.value.startsWith('cell-') ? 'Arial' : null,
            },
            requestSource,
            signal,
          )
        : format === 'png'
          ? await pngWithDpi(rendered, dpi.value)
          : rendered
    const verify = () => exportRequest('check', { metadata: identity }, requestSource, signal)
    if (format !== 'pdf') await verify()
    if (preset.value.startsWith('cell-') && blob.size > 20 * 1024 * 1024)
      throw new Error('Cell 单图文件应不超过 20 MB，请调整尺寸或分辨率。')
    return { file: blob, preview: format === 'pdf' ? rendered : blob, verify }
  } finally {
    plotly.purge(temporary)
    temporary.remove()
  }
}
</script>
<template>
  <div class="plot-shell" :class="{ 'mass-spectrum-shell': spectrum }">
    <div v-if="spectrum" class="spectrum-toolbar" aria-label="质谱浏览工具">
      <div class="spectrum-caption">{{ spectrumDescription }}</div>
      <div class="spectrum-tools">
        <label
          >强度<select
            v-model="intensityMode"
            :disabled="!relativeIntensityAllowed"
            aria-label="谱图强度显示"
            @change="changeSpectrum"
          >
            <option :value="false">
              {{
                intensityMissing
                  ? '未提供实测强度'
                  : relativeIntensityAllowed
                    ? '绝对强度'
                    : '当前矩阵值'
              }}
            </option>
            <option :value="true">相对丰度（基峰 100%）</option>
          </select></label
        >
        <label
          >操作<select
            v-model="spectrumSettings.interaction"
            aria-label="谱图鼠标操作"
            @change="renderer.retry()"
          >
            <option value="zoom">拖拽放大</option>
            <option value="pan">平移</option>
          </select></label
        >
        <button @click="spectrumView('back')" :disabled="!spectrumHistory.length">上一视图</button>
        <button @click="spectrumView('reset')">恢复全谱</button>
        <button @click="spectrumView('y-in')" aria-label="纵轴放大">Y × 2</button>
        <button @click="spectrumView('y-out')" aria-label="纵轴缩小">Y ÷ 2</button>
        <details class="spectrum-label-settings">
          <summary>峰标签</summary>
          <div class="spectrum-label-fields">
            <label class="inline-check"
              ><input
                v-model="spectrumSettings.labels"
                type="checkbox"
                @change="renderer.retry()"
              />显示标签</label
            >
            <label>m/z 小数位<span>4</span> </label>
            <label
              >标签阈值（基峰 %）<input
                v-model.number="spectrumSettings.threshold"
                type="number"
                min="0"
                max="100"
                step=".1"
                aria-label="谱图标签阈值"
                @change="renderer.retry()"
            /></label>
          </div>
        </details>
      </div>
    </div>
    <div
      ref="element"
      class="plot"
      :style="{ height: `${chartHeight}px` }"
      aria-label="交互图表"
    ></div>
    <div v-if="!compact" class="plot-actions">
      <button class="save" :disabled="store.busy || !fresh" @click="openImage">图片导出</button>
      <button class="save" :disabled="store.busy || !fresh" @click="plotData">作图数据导出</button>
    </div>
    <ImageExportDialog
      v-if="!compact"
      ref="imageDialog"
      v-model="filename"
      :settings="imageSettings"
      :render="image"
      :is-current="currentImage"
      :filename-label="'图文件名：' + name"
      :disabled="store.busy"
    >
      <template #default="{ format }">
        <div class="field-grid">
          <label
            >导出范围
            <select v-model="exportRange" aria-label="导出范围">
              <option value="current">当前视图</option>
              <option value="full">完整范围</option>
            </select>
          </label>
          <label
            >论文规格
            <select v-model="preset" aria-label="论文规格" @change="paperPreset">
              <option value="nature-single">Nature 单栏</option>
              <option value="nature-double">Nature 双栏</option>
              <option value="cell-single">Cell 单栏（85 mm）</option>
              <option value="cell-onehalf">Cell 一栏半（114 mm）</option>
              <option value="cell-double">Cell 双栏（174 mm）</option>
              <option value="custom">自定义</option>
            </select>
          </label>
          <label
            >宽度（mm）<input v-model.number="widthMm" type="number" min="20" max="600"
          /></label>
          <label
            >高度（mm）<input v-model.number="heightMm" type="number" min="20" max="600"
          /></label>
          <label
            >字号（pt）<input v-model.number="fontPt" type="number" min="4.5" max="24" step="0.5"
          /></label>
          <label
            >轴线宽（pt）<input
              v-model.number="lineWidth"
              type="number"
              min="0.2"
              max="5"
              step="0.1"
          /></label>
          <label v-if="format === 'png'"
            >位图 DPI<input v-model.number="dpi" type="number" min="72" max="2400" step="1"
          /></label>
          <label v-if="format === 'png'"
            >图形内容（设置 DPI）
            <select v-model="artwork">
              <option value="color">彩色或灰度</option>
              <option value="bw">黑白</option>
              <option value="line">线图</option>
            </select>
          </label>
          <label v-if="!preset.startsWith('cell-')"
            >字体
            <select v-model="fontFamily">
              <option value="Arial, Helvetica, Microsoft YaHei, sans-serif">无衬线</option>
              <option value="Times New Roman, Noto Serif, serif">衬线</option>
              <option value="DejaVu Sans Mono, monospace">等宽</option>
            </select>
          </label>
          <label class="inline-check" v-if="format !== 'pdf'"
            ><input v-model="transparent" type="checkbox" />透明背景</label
          >
        </div>
        <p v-if="preset.startsWith('cell-')" class="muted">
          Cell 使用 Arial，PDF 需要服务器安装该字体。
        </p>
        <details>
          <summary>图例与点样式</summary>
          <div class="field-grid">
            <label
              >图例位置
              <select :value="position" :aria-label="'图例位置：' + name" @change="changeLegend">
                <option value="right">图右侧</option>
                <option value="top_left">图内左上</option>
                <option value="top_right">图内右上</option>
                <option value="bottom_left">图内左下</option>
                <option value="bottom_right">图内右下</option>
                <option value="hidden">隐藏</option>
              </select>
            </label>
            <label
              >点不透明度<input
                v-model.number="pointOpacity"
                type="number"
                min="0.1"
                max="1"
                step="0.1"
            /></label>
          </div>
          <LegendOrder
            :items="legendItems"
            :disabled="store.busy"
            @move="moveLegend"
            @reset="resetLegend"
          />
        </details>
        <details>
          <summary>图中文字</summary>
          <label class="inline-check"
            ><input v-model="includeTitle" type="checkbox" />图内显示标题</label
          >
          <label>导出标题<input v-model="exportTitle" placeholder="沿用图标题" /></label>
          <label>导出横轴标签<input v-model="exportX" placeholder="沿用图标签" /></label>
          <label>导出纵轴标签<input v-model="exportY" placeholder="沿用图标签" /></label>
        </details>
      </template>
    </ImageExportDialog>
    <p v-if="!fresh" role="status">该图对应的数据已改变，请重新绘图后下载或选择细胞。</p>
    <div v-if="failure" role="alert" class="state-note">
      {{ failure
      }}<button class="preview" :disabled="store.busy" @click="renderer.retry()">
        仅重试图形渲染
      </button>
    </div>
  </div>
</template>

<style scoped>
.plot-shell,
.plot {
  min-width: 0;
  max-width: 100%;
}
.plot-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  align-items: end;
}
.plot-actions label {
  flex: 1 1 130px;
  min-width: 0;
  max-width: 100%;
}
.plot-actions input,
.plot-actions select {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.mass-spectrum-shell {
  border: 1px solid #d8dee7;
  background: #fff;
  border-radius: 4px;
}
.spectrum-toolbar {
  padding: 0.7rem 0.9rem;
  border-bottom: 1px solid #dde2e8;
  background: #f7f8fa;
}
.spectrum-caption {
  font-family: Arial, sans-serif;
  font-size: 0.8rem;
  color: #333;
  margin-bottom: 0.5rem;
}
.spectrum-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: end;
}
.spectrum-tools label {
  font-size: 0.75rem;
  gap: 0.2rem;
}
.spectrum-tools button,
.spectrum-tools select {
  min-height: 30px;
  padding: 4px 8px;
  font-size: 0.78rem;
}
.spectrum-label-settings {
  position: relative;
  font-size: 0.78rem;
}
.spectrum-label-fields {
  position: absolute;
  right: 0;
  top: 2rem;
  background: white;
  border: 1px solid #d8dee7;
  padding: 1rem;
  min-width: 210px;
  box-shadow: 0 3px 12px #0002;
  z-index: 10;
}
.mass-spectrum-shell > .plot-actions {
  margin: 0.75rem;
}
</style>
