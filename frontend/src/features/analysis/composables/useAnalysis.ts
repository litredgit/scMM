import { useReadScope } from '../../../api/readScope'
import { useViewState, restoringViews } from '../../../api/viewState'
import { ref, computed, watch, nextTick, onActivated, onDeactivated } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import type { AnalysisInfo, Figure, DataTable } from '../../../api/types'
import { useAnalysisSettings } from './useAnalysisSettings'
import { operations, resultPlots } from '../results'
import type { AnalysisTransport, AnalysisOperation, PlotKind, ResultName } from '../types'
export function useAnalysis() {
  const store = useWorkspace(),
    info = ref<AnalysisInfo>()
  const tab = ref('embedding')
  const active = ref(true)
  onActivated(() => {
    active.value = true
  })
  onDeactivated(() => {
    active.value = false
  })
  const {
    plotScope,
    projection,
    reduction,
    usePca,
    cluster,
    diff,
    network,
    scatter,
    featureEmbedding,
    stability,
    timeAnalysis,
    train,
    logistic,
    lda,
    plsda,
    forest,
    shapView,
    ldaSolver,
    validation,
    latentKey,
    shap,
    embedding,
    colorSource,
    color,
    search,
    sort,
    descending,
    featureOptions,
    featureTotal,
    featureOffset,
    selectedFeatures,
    hideZero,
    volcano,
    legend,
    settings,
    resetSettings,
    restoreSettings,
  } = useAnalysisSettings()
  const figures = ref<Record<string, Figure>>({}),
    tables = ref<Record<string, DataTable>>({}),
    modelReport = ref<Record<string, unknown>>()
  let generation = 0,
    featureGeneration = 0,
    initializedPath = '',
    hydrating = false,
    requestedEmbedding = ''
  const pendingInvalidations = new Set<string>()
  const context = () =>
    JSON.stringify([store.current?.workspace_id, store.project?.path, store.project?.dataset?.id])
  const dataContext = () => JSON.stringify([context(), store.project?.dataset?.revision])
  const infoReads = useReadScope(dataContext, () => void refresh())
  const observed = computed(() => Object.keys(info.value?.observations ?? {}))
  const groups = computed(() => info.value?.observations[diff.group_key] ?? [])
  const colors = computed(() =>
    colorSource.value === 'annotation'
      ? observed.value
          .filter((c) => c.toLowerCase().includes(search.value.toLowerCase()))
          .map((c) => ({ value: `obs:${c}`, label: c }))
      : colorSource.value === 'feature'
        ? featureOptions.value.map((c) => ({ value: `feature:${c.value}`, label: c.label }))
        : [],
  )
  watch(
    [settings, legend],
    () => {
      if (store.project && initializedPath === store.project.path && !hydrating)
        store.analysisDraft = {
          path: store.project.path,
          analysis: settings.value,
          legend: legend.value,
        }
    },
    { deep: true },
  )
  function has(name: string) {
    return info.value?.results.includes(name) ?? false
  }
  function help(name: string) {
    return store.configuration?.analysis.find((p) => p.name === name)?.help ?? ''
  }
  async function refresh(api: AnalysisTransport = store) {
    if (api === store && (!active.value || store.busy)) return
    const identity = dataContext()
    const token = ++generation
    const ticket = infoReads.begin()
    const accept = () =>
      token === generation &&
      identity === dataContext() &&
      (api === store ? ticket() : api.isCurrent?.() !== false)
    if (!store.project?.dataset) {
      info.value = undefined
      requestedEmbedding = ''
      figures.value = {}
      tables.value = {}
      return
    }
    const value =
      api === store
        ? await store.read<AnalysisInfo>('/analysis', undefined, accept)
        : await api.read<AnalysisInfo>('/analysis')
    if (!value || !accept()) return
    hydrating = true
    info.value = value
    if (initializedPath !== store.project.path) {
      resetSettings()
      initializedPath = store.project!.path
      const defaults = Object.fromEntries(
        (store.configuration?.analysis ?? []).map((p) => [p.name, p.default]),
      )
      const saved =
        store.analysisDraft?.path === store.project?.path
          ? store.analysisDraft.analysis
          : value.settings
      restoreSettings(saved, defaults)
      legend.value =
        store.analysisDraft?.path === store.project?.path
          ? store.analysisDraft.legend
          : value.legend
    }
    if (!observed.value.includes(diff.group_key))
      diff.group_key =
        ['group', 'sample', 'clusters'].find((k) => observed.value.includes(k)) ??
        observed.value[0] ??
        ''
    if (!observed.value.includes(train.label_key)) train.label_key = diff.group_key
    if (!train.group_key || !observed.value.includes(train.group_key))
      train.group_key = observed.value.includes('subject')
        ? 'subject'
        : observed.value.includes('sample')
          ? 'sample'
          : null
    if (!value.embeddings.includes(embedding.value)) embedding.value = value.embeddings[0] ?? ''
    if (reduction.use_rep !== 'X' && !value.embeddings.includes(reduction.use_rep))
      reduction.use_rep = 'X'
    if (!color.value && colorSource.value === 'annotation') color.value = `obs:${diff.group_key}`
    for (const name of Object.keys(tables.value)) {
      if (!has(name)) delete tables.value[name]
    }
    for (const [name, kinds] of Object.entries(resultPlots)) {
      if (!has(name)) for (const kind of kinds) delete figures.value[kind]
    }
    if (!has('supervised')) modelReport.value = undefined
    if (!value.embeddings.length) delete figures.value.embedding
    await Promise.resolve()
    hydrating = false
    void autoDrawEmbedding()
    void loadFeatures()
  }
  watch(
    [context, () => store.project?.dataset?.revision],
    ([identity], previous) => {
      ++generation
      ++featureGeneration
      requestedEmbedding = ''
      delete figures.value.embedding
      if (identity !== previous?.[0]) {
        plotScope.value = { group_key: 'group', groups: null, sample_key: 'sample', samples: null }
        initializedPath = ''
        tab.value = 'embedding'
        hydrating = true
        resetSettings()
        figures.value = {}
        tables.value = {}
        modelReport.value = undefined
        info.value = undefined
        pendingInvalidations.clear()
        hydrating = false
      }
      if (!store.busy) void refresh()
    },
    { immediate: true, flush: 'post' },
  )
  watch(
    () => diff.group_key,
    () => {
      if (!groups.value.includes(diff.group_a)) diff.group_a = groups.value[0] ?? ''
      if (!groups.value.includes(diff.group_b) || diff.group_a === diff.group_b)
        diff.group_b = groups.value.find((g) => g !== diff.group_a) ?? groups.value[0] ?? ''
    },
  )
  watch(
    () => reduction.method,
    (method) => {
      if (!hydrating) reduction.store_key = `X_${method}`
    },
  )

  let invalidationScheduled = false
  async function flushInvalidations() {
    if (store.busy || invalidationScheduled || !pendingInvalidations.size) return
    invalidationScheduled = true
    await nextTick()
    invalidationScheduled = false
    if (store.busy || !pendingInvalidations.size) return
    const names = [...pendingInvalidations]
    pendingInvalidations.clear()
    await store.analysisTransaction(async (api) => {
      await api.mutate('/analysis/invalidate', { names })
      await refresh(api)
    })
  }
  function invalidate(names: string[]) {
    if (restoringViews || hydrating || !info.value) return
    for (const n of names.filter(has)) {
      pendingInvalidations.add(n)
    }
    void flushInvalidations()
  }
  watch(
    () => store.busy,
    (busy) => {
      if (!busy) {
        if (
          store.project?.dataset &&
          (!info.value ||
            initializedPath !== store.project.path ||
            info.value.token[1] !== store.project.dataset.revision)
        )
          void refresh()
        void flushInvalidations()
      }
    },
  )
  watch(
    () => store.project?.path,
    () => pendingInvalidations.clear(),
    { flush: 'sync' },
  )
  watch(
    () => JSON.stringify([diff.group_key, diff.method, diff.layer]),
    () => {
      if (!hydrating) void invalidate(['differential', 'markers'])
    },
  )
  watch(
    () => JSON.stringify([diff.group_a, diff.group_b]),
    () => invalidate(['differential']),
  )
  watch(
    () => JSON.stringify(network),
    () => {
      if (!hydrating) void invalidate(['network'])
    },
  )
  watch(
    () => JSON.stringify([train, logistic, lda, plsda, forest, validation.value, ldaSolver.value]),
    () => {
      if (!hydrating) void invalidate(['supervised', 'shap'])
    },
  )
  watch(
    () => JSON.stringify(shap),
    () => {
      if (!hydrating) void invalidate(['shap'])
    },
  )
  const featureReads = useReadScope(
    () => [
      dataContext(),
      search.value,
      sort.value,
      descending.value,
      featureOffset.value,
      colorSource.value,
    ],
    () => void loadFeatures(),
  )
  async function loadFeatures() {
    if (!store.project?.dataset || !featureReads.isActive()) return
    const identity = dataContext()
    const token = ++featureGeneration
    const ticket = featureReads.begin()
    const accept = () => ticket() && token === featureGeneration && identity === dataContext()
    const query = new URLSearchParams({
      query: search.value,
      sort: sort.value,
      descending: String(descending.value),
      offset: String(featureOffset.value),
      limit: '200',
    })
    const result = await store.read<{ rows: { value: string; label: string }[]; total: number }>(
      `/analysis/features?${query}`,
      undefined,
      accept,
    )
    if (result && accept()) {
      featureOptions.value = result.rows
      featureTotal.value = result.total
    }
  }
  watch([search, sort, descending], () => {
    featureOffset.value = 0
    void loadFeatures()
  })
  watch(colorSource, () => {
    if (hydrating) return
    search.value = ''
    const prefix = colorSource.value === 'annotation' ? 'obs:' : 'feature:'
    if (!color.value.startsWith(prefix))
      color.value = colorSource.value === 'annotation' ? `obs:${diff.group_key}` : ''
    featureOffset.value = 0
    void loadFeatures()
  })
  const embeddingSignature = computed(() =>
    JSON.stringify([
      store.project?.path,
      store.project?.dataset?.id,
      store.project?.dataset?.revision,
      embedding.value,
      projection,
      colorSource.value === 'none' ? null : color.value || null,
    ]),
  )
  async function autoDrawEmbedding() {
    await nextTick()
    if (
      !active.value ||
      !['embedding', 'clustering'].includes(tab.value) ||
      hydrating ||
      store.busy ||
      !embedding.value ||
      !info.value?.embeddings.includes(embedding.value)
    )
      return
    if (requestedEmbedding === embeddingSignature.value) return
    await draw('embedding')
  }
  watch([embeddingSignature, () => store.busy], () => void autoDrawEmbedding())
  async function execute(operation: AnalysisOperation, options: Record<string, unknown>) {
    await store.analysisTransaction(async (api) => {
      await api.mutate('/analysis/operation', { operation, options })
      const entry = operations[operation]
      if (entry.result) {
        delete tables.value[entry.result]
        for (const kind of resultPlots[entry.result]) delete figures.value[kind]
      }
      if (operation === 'train') {
        modelReport.value = undefined
        delete tables.value.shap
        delete figures.value.shap_plot
      }
      if (operation === 'reduce' || operation === 'cluster') delete figures.value.embedding
      try {
        await refresh(api)
        if (operation === 'reduce') embedding.value = String(options.store_key)
        if (operation === 'cluster') {
          colorSource.value = 'annotation'
          color.value = `obs:${options.key}`
        }
        if (entry.result) await loadResult(entry.result, 0, api)
        for (const kind of entry.plots) {
          if (kind !== 'embedding' || embedding.value) await draw(kind, api)
        }
      } catch (cause) {
        if (api.isCurrent?.() === false) return
        requestedEmbedding = embeddingSignature.value
        store.error = `计算已完成，结果已保留；读取报告或绘图失败，可使用读取报告或更新图形按钮重试。${cause instanceof Error ? cause.message : String(cause)}`
      }
    })
  }
  function reduce() {
    const options = {
      ...reduction,
      pca_components: reduction.method === 'umap' && usePca.value ? reduction.pca_components : null,
      learning_rate: reduction.learning_rate === 'auto' ? 'auto' : Number(reduction.learning_rate),
    }
    void execute('reduce', options)
  }
  function trainModel() {
    void execute('train', {
      ...train,
      group_key: validation.value === 'grouped' ? train.group_key : null,
      model_params:
        train.model === 'lda'
          ? {
              ...lda,
              solver: ldaSolver.value,
              shrinkage:
                lda.shrinkage === ''
                  ? null
                  : lda.shrinkage === 'auto'
                    ? 'auto'
                    : Number.isFinite(Number(lda.shrinkage))
                      ? Number(lda.shrinkage)
                      : lda.shrinkage,
            }
          : train.model === 'logistic'
            ? { ...logistic }
            : train.model === 'plsda'
              ? { ...plsda }
              : {
                  ...forest,
                  max_features: forest.max_features === '' ? null : forest.max_features,
                  max_samples: forest.max_samples === '' ? null : forest.max_samples,
                },
      random_state: train.random_state,
    })
  }
  async function loadResult(
    name: ResultName,
    offset = 0,
    api?: AnalysisTransport,
  ): Promise<unknown> {
    if (!api) return store.analysisTransaction((transport) => loadResult(name, offset, transport))
    const identity = dataContext()
    const result = await api.read<{ table?: DataTable; diagnostics?: Record<string, unknown> }>(
      `/analysis/results/${name}?offset=${offset}`,
    )
    if (identity !== dataContext() || !has(name)) return
    if (result?.table) tables.value[name] = result.table
    if (result?.diagnostics) modelReport.value = result.diagnostics
  }
  async function draw(kind: PlotKind, api?: AnalysisTransport): Promise<unknown> {
    if (!api) return store.analysisTransaction((transport) => draw(kind, transport))
    const identity = dataContext()
    const options =
      kind === 'embedding'
        ? {
            key: embedding.value,
            color: colorSource.value === 'none' ? null : color.value || null,
            scope: plotScope.value,
            dimensions: projection.threeD
              ? [projection.x, projection.y, projection.z]
              : [projection.x, projection.y],
          }
        : kind === 'volcano'
          ? { ...volcano }
          : kind === 'violin'
            ? {
                features: selectedFeatures.value,
                hide_zero: hideZero.value,
                scope: plotScope.value,
                columns: Math.max(1, Math.min(3, Math.floor(window.innerWidth / 400))),
              }
            : {}
    const signature = embeddingSignature.value
    if (kind === 'embedding') requestedEmbedding = signature
    const value = await api.command<Figure>('/analysis/plot', { kind, options })
    if (
      value &&
      identity === dataContext() &&
      (kind !== 'embedding' || signature === embeddingSignature.value)
    ) {
      if (kind === 'violin')
        value.layout.meta = {
          ...(value.layout.meta as object),
          selection_signature: JSON.stringify([
            (options as { features: string[] }).features,
            (options as { hide_zero: boolean }).hide_zero,
            plotScope.value,
          ]),
        }
      figures.value[kind] = value
    }
  }
  function toggleFeature(id: string) {
    const current = [...selectedFeatures.value]
    if (current.includes(id)) selectedFeatures.value = current.filter((x) => x !== id)
    else if (current.length < 12) selectedFeatures.value = [...current, id]
    else store.error = '最多选择 12 个特征。'
  }
  function pageFeatures(delta: number) {
    featureOffset.value += delta
    void loadFeatures()
  }
  async function loadWithPlot(name: ResultName, kind: PlotKind) {
    await store.analysisTransaction(async (api) => {
      await loadResult(name, 0, api)
      await draw(kind, api)
    })
  }
  async function reloadAnalysis() {
    await store.analysisTransaction((api) => refresh(api))
  }
  async function saveSettings() {
    await store.mutate(
      '/analysis/settings',
      { analysis: settings.value, legend: legend.value },
      'PUT',
      '视图与分析参数已记入当前项目；请主动保存项目。',
    )
  }

  useViewState('analysis', {
    plotScope,
    tab,
    figures,
    tables,
    modelReport,
    embedding,
    colorSource,
    color,
    search,
    sort,
    descending,
    selectedFeatures,
    hideZero,
    legend,
  })
  return {
    plotScope,
    projection,
    reduction,
    usePca,
    cluster,
    diff,
    network,
    scatter,
    featureEmbedding,
    stability,
    timeAnalysis,
    train,
    logistic,
    lda,
    plsda,
    forest,
    shapView,
    ldaSolver,
    validation,
    latentKey,
    shap,
    embedding,
    colorSource,
    color,
    search,
    sort,
    descending,
    featureOptions,
    featureTotal,
    featureOffset,
    selectedFeatures,
    hideZero,
    volcano,
    legend,
    store,
    info,
    tab,
    observed,
    groups,
    colors,
    figures,
    tables,
    modelReport,
    has,
    help,
    execute,
    reduce,
    trainModel,
    loadResult,
    draw,
    toggleFeature,
    pageFeatures,
    loadWithPlot,
    saveSettings,
    reloadAnalysis,
    refreshAnalysis: refresh,
  }
}
