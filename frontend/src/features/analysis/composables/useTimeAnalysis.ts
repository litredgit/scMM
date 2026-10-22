import { ref, computed, watch, onActivated } from 'vue'
import { request } from '../../../api/client'
import { useViewState } from '../../../api/viewState'
import type { Figure, DataTable } from '../../../api/types'
import { useAnalysisContext } from './useAnalysisContext'

type TimeResult = { key: string; kind: string; valid: boolean; parameters: Record<string, unknown> }
type TimeInfo = {
  results: TimeResult[]
  observations: string[]
  embeddings: string[]
  probability_keys: string[]
  feature_columns: string[]
  layers: string[]
  cells: string[]
  total_cells: number
  saved_plot_key?: string
}
type ResultView = {
  key: string
  kind: string
  parameters: Record<string, unknown>
  tables: Record<string, DataTable>
}

export function useTimeAnalysis() {
  const { store, timeAnalysis: form, refreshAnalysis, selectedFeatures } = useAnalysisContext()
  const info = ref<TimeInfo>()
  const result = ref<ResultView>()
  const figure = ref<Figure>()
  const search = ref('')
  const readError = ref('')
  let generation = 0
  const context = () =>
    JSON.stringify([store.current?.workspace_id, store.project?.path, store.project?.dataset?.id])
  const selected = computed(() =>
    info.value?.results.find((row) => row.key === form.selected_result),
  )
  const figureMeta = computed(
    () => (figure.value?.layout.meta ?? {}) as { notes?: string[]; time_result_key?: string },
  )
  async function load() {
    if (!store.current || !store.project?.dataset) return
    const version = `${context()}|${store.project.dataset.revision}`
    const token = ++generation
    try {
      const value = await request<TimeInfo>(
        `/workspace/analysis/time?query=${encodeURIComponent(search.value)}`,
        { workspace: store.current.workspace_id },
      )
      if (token !== generation || version !== `${context()}|${store.project?.dataset?.revision}`)
        return
      info.value = value
      readError.value = ''
      if (!value.results.some((row) => row.key === form.selected_result && row.valid)) {
        result.value = undefined
        figure.value = undefined
      }
    } catch (cause) {
      if (token === generation && version === `${context()}|${store.project?.dataset?.revision}`)
        readError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }
  watch(
    context,
    () => {
      generation++
      info.value = undefined
      result.value = undefined
      figure.value = undefined
      readError.value = ''
      void load()
    },
    { immediate: true },
  )
  watch(
    () => store.project?.dataset?.revision,
    () => {
      figure.value = undefined
      result.value = undefined
      if (!store.busy) void load()
    },
  )
  watch(
    () => store.busy,
    (busy) => {
      if (!busy) void load()
    },
  )
  watch(
    () => form.selected_result,
    () => {
      result.value = undefined
      figure.value = undefined
    },
  )
  watch(
    () => form.time_kind,
    (kind) => {
      if (kind === 'acquisition_seconds') form.unit = 's'
      else if (kind === 'normalized_time' || kind === 'pseudotime') form.unit = 'unitless'
      else form.unit = ''
    },
  )
  onActivated(() => void load())
  function options() {
    if (form.mode === 'palantir')
      return {
        key: form.key,
        root_cell_id: form.root_cell_id,
        input_representation: form.input_representation,
        terminal_cell_ids:
          form.terminal_cell_ids === '' ? null : form.terminal_cell_ids.split('\n').filter(Boolean),
        layer: form.input_representation === 'X' ? form.layer : null,
        n_diff_components: form.n_diff_components,
        knn: form.knn,
        num_waypoints: form.num_waypoints,
        scale_components: form.scale_components,
        max_iterations: form.max_iterations,
        seed: form.seed,
        use_early_cell_as_start: form.use_early_cell_as_start,
      }
    if (form.mode === 'trends')
      return {
        key: form.key,
        time_key: form.time_key,
        time_kind: form.time_kind,
        unit: form.unit,
        layer: form.layer,
        window_size: form.window_size,
        step_size: form.step_size,
        features: form.features,
        feature_name_key: form.feature_name_key,
        kernel_stat: form.kernel_stat,
      }
    if (form.mode === 'velocity')
      return {
        key: form.key,
        time_key: form.time_key,
        time_kind: form.time_kind,
        unit: form.unit,
        layer: form.layer,
        window_size: form.window_size,
        step_size: form.step_size,
      }
    return {
      key: form.key,
      coordinate_key: form.coordinate_key,
      time_key: form.time_key,
      time_kind: form.time_kind,
      unit: form.unit,
      branch_probability_key: form.branch_probability_key,
      window_size: form.window_size,
      step_size: form.step_size,
      min_cells_per_window: form.min_cells_per_window,
    }
  }
  async function calculate() {
    let committed = false
    await store.analysisTransaction(async (api) => {
      try {
        const value = await api.command<{ key: string }>('/analysis/time', {
          operation: form.mode,
          options: options(),
        })
        if (!value) return
        committed = true
        form.selected_result = value.key
        const view = await api.read<ResultView>(
          `/analysis/time/result?key=${encodeURIComponent(value.key)}`,
        )
        if (api.isCurrent?.() === false) return
        result.value = view
        await refreshAnalysis(api)
        store.notice = '时间结果已计算并应用；绘图与主动保存分别执行。'
      } catch (cause) {
        if (committed)
          throw new Error(
            `计算已完成并保留，展示读取失败；可重新读取结果：${cause instanceof Error ? cause.message : String(cause)}`,
          )
        throw cause
      }
    })
  }
  async function readResult() {
    const key = form.selected_result
    await store.analysisTransaction(async (api) => {
      const value = await api.read<ResultView>(
        `/analysis/time/result?key=${encodeURIComponent(key)}`,
      )
      if (api.isCurrent?.() !== false && key === form.selected_result) result.value = value
    })
  }
  async function draw(saved = false) {
    const key = form.selected_result
    await store.analysisTransaction(async (api) => {
      const value = saved
        ? await api.read<Figure>('/analysis/figures/time_plot')
        : await api.command<Figure>('/analysis/plot', {
            kind: 'time_plot',
            options: {
              key,
              coordinate_key: selected.value?.kind === 'palantir' ? form.plot_coordinate_key : null,
              ...(selected.value?.kind === 'trends'
                ? { plot_top_n: form.plot_top_n, display_standardize: form.display_standardize }
                : {}),
            },
          })
      if (value && api.isCurrent?.() !== false && key === form.selected_result) {
        figure.value = value
        await refreshAnalysis(api)
      }
    })
  }
  async function download() {
    const key = form.selected_result
    await store.download('time_result', 'scmm-time-result.zip', key)
  }
  useViewState('time_analysis', { figure, result, search })
  return {
    store,
    selectedFeatures,
    form,
    info,
    result,
    figure,
    search,
    readError,
    selected,
    figureMeta,
    load,
    calculate,
    readResult,
    draw,
    download,
  }
}
