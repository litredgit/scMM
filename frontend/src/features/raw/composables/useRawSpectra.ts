import { ref, computed, watch, type Ref } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import type { AnalysisTransport } from '../../analysis/types'
import type { Figure, DataTable } from '../../../api/types'

type Options = {
  sample: Ref<string>
  parameters(): Record<string, unknown>
  assignParameters(value: Record<string, unknown>): void
}
export function useRawSpectra(options: Options) {
  const store = useWorkspace()
  const opened = ref(''),
    summary = ref<Record<string, unknown>>()
  let loading = false
  const kind = ref('tic'),
    ms = ref(1),
    scan = ref(0),
    rtMin = ref(''),
    rtMax = ref(''),
    mzMin = ref(100),
    mzMax = ref(1000),
    refs = ref(''),
    ppm = ref(10),
    fast = ref(true),
    normalize = ref(false),
    bins = ref(20000)
  const plots = ref<
    Record<string, { figure: Figure; table: DataTable; detail?: Record<string, unknown> }>
  >({})
  const scanCatalog = ref<{ indices: number[]; times: number[] }>({ indices: [], times: [] })
  const scanTime = ref(0)
  const selectRange = ref(false)
  function selectedRange(range: [number, number]) {
    rtMin.value = String(Math.min(...range))
    rtMax.value = String(Math.max(...range))
    store.notice = '合谱显示范围已选择；切换“合并谱”并更新图形。'
  }
  const scanPosition = computed(() => scanCatalog.value.indices.indexOf(scan.value))
  async function scans(api: AnalysisTransport = store) {
    const selected = options.sample.value
    const level = ms.value
    const value = await api.read<{ indices: number[]; times: number[] }>(
      `/raw/scans?sample_id=${selected}&ms_level=${level}`,
    )
    if (value && options.sample.value === selected && ms.value === level) {
      scanCatalog.value = value
      seekScan('index', scan.value)
    }
  }
  function seekScan(mode: 'time' | 'index' | 'step', value: number) {
    const catalog = scanCatalog.value
    if (!catalog.indices.length) return
    let pos = 0
    if (mode === 'step')
      pos = Math.max(0, Math.min(catalog.indices.length - 1, scanPosition.value + value))
    else {
      const values = mode === 'time' ? catalog.times : catalog.indices
      for (let i = 1; i < values.length; i++)
        if (Math.abs(values[i]! - value) < Math.abs(values[pos]! - value)) pos = i
    }
    scan.value = catalog.indices[pos]!
    scanTime.value = catalog.times[pos]!
  }
  watch(ms, () => {
    if (opened.value && !store.busy) {
      plots.value = {}
      void scans()
    }
  })
  const currentPlot = computed(() => plots.value[kind.value])
  async function open() {
    await store.analysisTransaction(async (api) => {
      const selected = options.sample.value
      const value = await api.command<{
        summary: Record<string, unknown>
        parameters: Record<string, unknown>
      }>('/raw/open', { sample_id: options.sample.value })
      if (!value || options.sample.value !== selected) return
      opened.value = options.sample.value
      summary.value = value.summary
      const levels = value.summary.scans_by_ms_level as number[][]
      if (!levels.some((level) => level[0] === ms.value)) ms.value = levels[0]?.[0] ?? 1
      options.assignParameters(value.parameters)
      mzMin.value = Number(value.parameters.mz_min)
      mzMax.value = Number(value.parameters.mz_max)
      scan.value = 0
      plots.value = {}
      await scans(api)
      await plot('tic', api)
      const first = plots.value.tic?.table.rows[0]?.scan_index
      if (typeof first === 'number') scan.value = first
      await plot('single', api)
    })
  }
  async function plot(selected = kind.value, api?: AnalysisTransport): Promise<void> {
    if (!opened.value || loading || (!api && store.busy)) return
    if (!api) {
      await store.analysisTransaction((transport) => plot(selected, transport))
      return
    }
    loading = true
    const capture = opened.value
    const body = {
      sample_id: options.sample.value,
      kind: selected,
      ms_level: ms.value,
      scan_index: scan.value,
      references: refs.value
        .split(/[,，\s]+/)
        .filter(Boolean)
        .map(Number),
      ppm: ppm.value,
      mz_range: [mzMin.value, mzMax.value],
      rt_range:
        rtMin.value !== '' && rtMax.value !== ''
          ? [Number(rtMin.value), Number(rtMax.value)]
          : null,
      fast: fast.value,
      bins: bins.value,
      normalize: normalize.value,
      resolution: Number(options.parameters().resolution),
      points_per_fwhm: Number(options.parameters().resample_points_per_fwhm),
    }
    try {
      const data = await api.read<{
        figure: Figure
        table: DataTable
        detail: Record<string, unknown>
      }>('/raw/plot', body)
      if (data && api.isCurrent?.() !== false && opened.value === capture)
        plots.value[selected] = data
    } finally {
      loading = false
    }
  }

  watch(kind, () => {
    if (kind.value !== 'cells' && opened.value && !plots.value[kind.value]) void plot()
  })
  watch(scan, () => {
    const pos = scanCatalog.value.indices.indexOf(scan.value)
    if (pos < 0 && scanCatalog.value.indices.length) {
      seekScan('index', scan.value)
      return
    }
    if (pos >= 0) scanTime.value = scanCatalog.value.times[pos]!
    if (opened.value && kind.value === 'single') void plot('single')
  })

  function reset() {
    opened.value = ''
    summary.value = undefined
    plots.value = {}
  }
  return {
    opened,
    summary,
    kind,
    ms,
    scan,
    rtMin,
    rtMax,
    mzMin,
    mzMax,
    refs,
    ppm,
    fast,
    normalize,
    bins,
    plots,
    scanCatalog,
    scanTime,
    selectRange,
    selectedRange,
    scanPosition,
    currentPlot,
    seekScan,
    open,
    plot,
    reset,
  }
}
