<script setup lang="ts">
import { ref, watch, onBeforeUnmount, computed } from 'vue'
import { usePlotRenderer } from './usePlotRenderer'
import LegendOrder from './LegendOrder.vue'
import resultContract from '../features/analysis/results.contract.json'
import { useLegendOrder } from './useLegendOrder'
import { useViewState } from '../api/viewState'
import { useWorkspace } from '../stores/workspace'
import type { Figure } from '../api/types'
import { authenticatedFetch } from '../api/client'
import { saveBlob, pngWithDpi } from './plotExport'
const props = withDefaults(
  defineProps<{
    figure: Figure
    legend?: string
    name?: string
    viewKey?: string
    selectRange?: boolean
    readonly?: boolean
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
      } as Record<string, string>
    )[props.name] ??
    props.name,
)
const legendNames = computed(() =>
  (props.figure.data as { name?: string; showlegend?: boolean }[])
    .filter((t) => t.showlegend !== false && t.name)
    .map((t) => t.name!),
)
const {
  items: legendItems,
  move: moveLegend,
  reset: resetLegend,
} = useLegendOrder(chartKey, legendNames, () => !!props.readonly)
function orderedFigure(): Figure {
  const copy = JSON.parse(JSON.stringify(props.figure)) as Figure
  for (const trace of copy.data as Record<string, unknown>[]) {
    if (typeof trace.name === 'string') trace.legendrank = legendItems.value.indexOf(trace.name)
    if (
      ['scatter', 'scattergl', 'scatter3d'].includes(String(trace.type)) &&
      String(trace.mode ?? 'markers').includes('markers')
    ) {
      trace.marker = { ...(trace.marker as object), opacity: pointOpacity.value }
    }
  }
  copy.layout.legend = { ...(copy.layout.legend as object), traceorder: 'normal' }
  return copy
}
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
const localPosition = ref(props.legend)
const position = computed(() =>
  props.readonly || !store.project
    ? localPosition.value
    : (store.project.presentation[chartKey.value] ?? props.legend),
)
function changeLegend(event: Event) {
  if (props.readonly || !store.project) {
    localPosition.value = (event.target as HTMLSelectElement).value
    return
  }
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
const widthMm = ref(89),
  heightMm = ref(65),
  dpi = ref(300),
  fontPt = ref(7)
const viewport = ref<Record<string, unknown>>({})
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
const exporting = ref(false)
const preset = ref('nature-single')
const pointOpacity = ref(1)
const artwork = ref('color')
const includeTitle = ref(true)
const previewImage = ref('')
const exportLanguage = ref('en'),
  exportTitle = ref(''),
  exportX = ref(''),
  exportY = ref('')
function paperText(value: unknown) {
  const text = String(value ?? '')
  if (exportLanguage.value === 'zh') return text
  const labels: Record<string, string> = {
    强度: 'Intensity',
    总强度: 'Total intensity',
    检出特征数: 'Detected features',
    '每细胞 QC · 当前矩阵': 'Cell quality control',
    细胞质谱对比: 'Cell mass spectra',
    归一化强度: 'Normalized intensity',
    样本: 'Sample',
    特征: 'Feature',
    分组: 'Group',
    细胞: 'Cell',
    特征热图: 'Feature heatmap',
    行标准分: 'Row z-score',
    维度: 'Dimension',
    '平均绝对 SHAP': 'Mean absolute SHAP',
    预测类别: 'Predicted class',
    真实类别: 'True class',
    留出测试集混淆矩阵: 'Held-out confusion matrix',
    召回率: 'Recall',
    精确率: 'Precision',
    '假阳性率（FPR）': 'False positive rate',
    '真阳性率（TPR）': 'True positive rate',
    'RT（秒）': 'Time (s)',
  }
  return labels[text] ?? text
}
useViewState(`plot:${chartKey.value}`, {
  filename,
  widthMm,
  heightMm,
  dpi,
  fontPt,
  preset,
  localPosition,
  viewport,
  exportLanguage,
  exportTitle,
  exportX,
  exportY,
  pointOpacity,
  artwork,
  includeTitle,
})
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
  exporting,
  fresh,
  image,
  emit,
  legendItems,
  pointOpacity,
})
onBeforeUnmount(() => {
  if (previewImage.value) URL.revokeObjectURL(previewImage.value)
})
async function exportRequest(path: string, body: unknown) {
  const response = await authenticatedFetch(`/api/v1/workspace/figures/${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-SCMM-Workspace': store.current?.workspace_id ?? '',
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    throw new Error(value.error?.message ?? '导出失败，请重试。')
  }
  return response.blob()
}
async function plotData() {
  exporting.value = true
  failure.value = ''
  try {
    saveBlob(
      await exportRequest('data', {
        figure: {
          ...orderedFigure(),
          layout: {
            ...orderedFigure().layout,
            meta: {
              ...(props.figure.layout.meta as object),
              publication: {
                width_mm: widthMm.value,
                height_mm: heightMm.value,
                dpi: dpi.value,
                font_pt: fontPt.value,
                language: exportLanguage.value,
                title: exportTitle.value,
                x_label: exportX.value,
                y_label: exportY.value,
                legend: position.value,
                legend_order: legendItems.value,
                viewport: viewport.value,
                preset: preset.value,
                point_opacity: pointOpacity.value,
                include_title: includeTitle.value,
              },
            },
          },
        },
      }),
      `${filename.value || props.name}-data.zip`,
    )
  } catch (cause) {
    failure.value = String(cause)
  } finally {
    exporting.value = false
  }
}
async function image(format: string, preview = false) {
  const plotly = renderer.plotly()
  if (!plotly) return
  failure.value = ''
  exporting.value = true
  const temporary = document.createElement('div')
  temporary.style.cssText = 'position:absolute;left:-100000px;top:0'
  document.body.appendChild(temporary)
  try {
    if (
      ![widthMm.value, heightMm.value, dpi.value, fontPt.value, pointOpacity.value].every(
        Number.isFinite,
      ) ||
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
    const copy = orderedFigure()
    const source = (copy.layout.meta ?? {}) as Record<string, unknown>
    const identity = Object.fromEntries(
      [
        'dataset_token',
        'result_name',
        'result_identity',
        'result_identity_valid',
        'sample_id',
        'input_identity',
      ]
        .filter((key) => Object.hasOwn(source, key))
        .map((key) => [key, source[key]]),
    )
    for (const [key, value] of Object.entries(viewport.value)) {
      const match = /^([xy]axis\d*)\.(range)(?:\[(\d)\])?$/.exec(key)
      if (match) {
        const axis = (copy.layout[match[1]!] ??= {}) as Record<string, unknown>
        if (match[3] !== undefined) {
          const range = (axis.range ??= []) as unknown[]
          range[Number(match[3])] = value
        } else axis.range = value
      } else if (key.endsWith('.autorange')) {
        const name = key.split('.')[0]!
        copy.layout[name] ??= {}
        ;(copy.layout[name] as Record<string, unknown>).autorange = value
      } else if (key === 'scene.camera')
        copy.layout.scene = { ...(copy.layout.scene as object), camera: value }
    }
    for (const trace of copy.data as Record<string, unknown>[])
      if (trace.type === 'scattergl') trace.type = 'scatter'
    const font = {
      family: preset.value.startsWith('cell-')
        ? 'Arial'
        : 'Arial, Helvetica, Microsoft YaHei, sans-serif',
      size: (fontPt.value * 96) / 72,
      color: '#111111',
    }
    copy.layout = {
      ...copy.layout,
      width,
      height,
      autosize: false,
      paper_bgcolor: 'white',
      plot_bgcolor: 'white',
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
          text: (name.startsWith('x') ? exportX.value : exportY.value) || paperText(original),
          font,
        }
        Object.assign(axis, {
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
          linewidth: (0.7 * 96) / 72,
          ticks: 'outside',
          tickwidth: (0.7 * 96) / 72,
        })
        axis.automargin = true
      }
    const titleText = (copy.layout.title as { text?: string })?.text
    copy.layout.title = {
      ...(copy.layout.title as object),
      text: includeTitle.value ? exportTitle.value || paperText(titleText) : '',
    }
    copy.layout.showlegend = position.value !== 'hidden'
    const inside = position.value !== 'right',
      right = position.value.endsWith('right'),
      bottom = position.value.startsWith('bottom')
    copy.layout.legend = {
      traceorder: 'normal',
      font,
      x: inside ? (right ? 0.99 : 0.01) : 1.02,
      y: bottom ? 0.01 : 0.99,
      xanchor: inside && right ? 'right' : 'left',
      yanchor: bottom ? 'bottom' : 'top',
    }
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
            text: paperText((bar.title as { text?: string })?.text ?? ''),
            font,
          },
        }
    }
    await plotly.newPlot(temporary, copy.data as never, copy.layout as never, {
      staticPlot: true,
      displayModeBar: false,
    })
    const url = await plotly.toImage(temporary, {
      format: format === 'png' ? 'png' : 'svg',
      width,
      height,
      scale: format === 'png' ? dpi.value / 96 : 1,
    })
    const rendered = await (await fetch(url)).blob()
    const blob =
      format === 'pdf'
        ? await exportRequest('pdf', {
            svg: await rendered.text(),
            width_mm: widthMm.value,
            height_mm: heightMm.value,
            identity,
            font_family: preset.value.startsWith('cell-') ? 'Arial' : null,
          })
        : format === 'png'
          ? await pngWithDpi(rendered, dpi.value)
          : rendered
    if (format !== 'pdf') await exportRequest('check', { metadata: identity })
    if (preset.value.startsWith('cell-') && blob.size > 20 * 1024 * 1024)
      throw new Error('Cell 单图文件应不超过 20 MB，请调整尺寸或分辨率。')
    if (preview) {
      if (previewImage.value) URL.revokeObjectURL(previewImage.value)
      previewImage.value = URL.createObjectURL(blob)
    } else saveBlob(blob, `${filename.value || props.name}.${format}`)
  } catch (cause) {
    failure.value = String(cause)
  } finally {
    plotly.purge(temporary)
    temporary.remove()
    exporting.value = false
  }
}
</script>
<template>
  <div class="plot-shell">
    <div
      ref="element"
      class="plot"
      :style="{ height: `${chartHeight}px` }"
      aria-label="交互图表"
    ></div>
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
      <label
        >点不透明度<input
          v-model.number="pointOpacity"
          aria-label="点不透明度"
          type="number"
          min="0.1"
          max="1"
          step="0.1"
      /></label>
      <button
        class="preview"
        :disabled="exporting || store.busy || !fresh"
        @click="image('svg', true)"
      >
        预览导出效果
      </button>
      <button class="save" :disabled="exporting || store.busy || !fresh" @click="image('svg')">
        下载 SVG
      </button>
      <button class="save" :disabled="exporting || store.busy || !fresh" @click="image('pdf')">
        下载 PDF
      </button>
      <button class="save" :disabled="exporting || store.busy || !fresh" @click="image('png')">
        下载 PNG
      </button>
      <button class="save" :disabled="exporting || store.busy || !fresh" @click="plotData">
        下载作图数据
      </button>
    </div>
    <details class="plot-settings">
      <summary>论文导出设置 · 尺寸、字号与 DPI</summary>
      <div class="field-grid">
        <label
          >论文规格<select v-model="preset" aria-label="论文规格" @change="paperPreset">
            <option value="nature-single">Nature 单栏</option>
            <option value="nature-double">Nature 双栏</option>
            <option value="cell-single">Cell 单栏（85 mm）</option>
            <option value="cell-onehalf">Cell 一栏半（114 mm）</option>
            <option value="cell-double">Cell 双栏（174 mm）</option>
            <option value="custom">自定义</option>
          </select></label
        >
        <label
          >宽度（mm）<input
            aria-label="宽度（mm）"
            v-model.number="widthMm"
            type="number"
            min="20"
            max="600"
        /></label>
        <label
          >高度（mm）<input
            aria-label="高度（mm）"
            v-model.number="heightMm"
            type="number"
            min="20"
            max="600"
        /></label>
        <label
          >字号（pt）<input
            aria-label="字号（pt）"
            v-model.number="fontPt"
            type="number"
            min="4.5"
            max="24"
            step="0.5"
        /></label>
        <label
          >位图 DPI<input
            v-model.number="dpi"
            type="number"
            min="72"
            max="2400"
            step="1"
            :list="`${name}-dpi`"
        /></label>
        <datalist :id="`${name}-dpi`">
          <option value="300" />
          <option value="500" />
          <option value="600" />
          <option value="1000" />
          <option value="1200" />
        </datalist>
      </div>
      <label class="inline-check"
        ><input v-model="includeTitle" type="checkbox" />图内显示标题</label
      >
      <label
        >图形内容（设置 DPI）<select v-model="artwork">
          <option value="color">彩色或灰度（至少 300 DPI）</option>
          <option value="bw">黑白（至少 500 DPI）</option>
          <option value="line">线图（至少 1000 DPI）</option>
        </select></label
      >
      <p v-if="preset.startsWith('cell-')" class="muted">
        Cell：Arial，正文约 6–8 pt，线宽 0.5–1.5 pt；推荐高度不超过 200 mm。主标题与图注另附，PDF
        优先用于生产。PDF 检查服务器真实 Arial 字体；SVG 和 PNG 需在装有 Arial
        的环境核对。此预设不代替最终投稿检查。
      </p>
    </details>
    <div v-if="previewImage" class="export-preview">
      <button @click="previewImage = ''">关闭导出预览</button
      ><img :src="previewImage" alt="按论文设置生成的导出预览" style="max-width: 100%" />
    </div>
    <LegendOrder
      :items="legendItems"
      :disabled="store.busy"
      @move="moveLegend"
      @reset="resetLegend"
    />
    <details>
      <summary>导出标题与语言</summary>
      <div class="field-grid">
        <label
          >导出标签<select v-model="exportLanguage">
            <option value="en">英文通用标签</option>
            <option value="zh">中文</option>
          </select></label
        ><label>导出标题<input v-model="exportTitle" placeholder="留空沿用图标题" /></label
        ><label>导出横轴标签<input v-model="exportX" placeholder="留空沿用图标签" /></label
        ><label>导出纵轴标签<input v-model="exportY" placeholder="留空沿用图标签" /></label>
      </div>
    </details>
    <p v-if="!fresh" role="status">该图对应的数据已改变，请重新绘图后下载或选择细胞。</p>
    <div v-if="failure" role="alert" class="state-note">
      {{ failure
      }}<button class="preview" :disabled="store.busy || exporting" @click="renderer.retry()">
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
</style>
