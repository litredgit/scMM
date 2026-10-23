import { useLipidRules } from './useLipidRules'
import { useViewState } from '../../api/viewState'
import { useReadScope } from '../../api/readScope'
import type { Figure } from '../../api/types'
import { computed, reactive, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { useAuth } from '../../stores/auth'
import { workspaceBlob, saveBlob } from '../../api/workspaceDownload'
import type { LipidInfo, LipidResults, LipidRules } from './lipids'

export function useLipidPanel() {
  const store = useWorkspace()
  const auth = useAuth()
  const info = ref<LipidInfo>()
  const limit = 50
  const {
    rules,
    imported,
    preset,
    presetName,
    ruleOffset,
    rulesTable,
    importFile,
    choosePreset,
    savePreset,
    applyRules,
    template,
  } = useLipidRules(
    store,
    info,
    () => version.value,
    () => loadResults(),
    limit,
  )
  const results = ref<LipidResults>()
  const isotopeFigure = ref<Figure>()
  async function viewIsotope(id: string) {
    const result = await store.command<Figure>('/lipids/isotope-spectrum', {
      version: version.value,
      relation_id: id,
    })
    if (result) isotopeFigure.value = result
  }
  const version = ref('')
  const label = ref('')
  const feature = ref('')
  const selection = ref<string[]>([])
  const offset = ref(0)
  const relationOffset = ref(0)
  const candidateSort = ref('recommended'),
    candidateDescending = ref(false)
  const relationSort = ref('recommended'),
    relationDescending = ref(false)
  const candidateSortOptions = {
    recommended: '规则推荐顺序',
    query_mz: '实测 m/z',
    theoretical_mz: '理论 m/z',
    name: '物质名',
    CATEGORY: '类别',
    MAIN_CLASS: '主类',
    SUB_CLASS: '子类',
    database_id: '数据库 ID',
    adduct: '加合物',
    abs_ppm_error: '绝对 ppm 误差',
    ppm_error: '带符号 ppm 误差',
    ppm_band: 'ppm 档',
    network_level: '网络支持',
    class_score: '类别分',
    adduct_score: '加合物分',
    rule_score: '规则分',
  }
  const relationSortOptions = {
    recommended: '原始证据顺序',
    parent_mz: '母峰 m/z',
    isotope_mz: '子峰 m/z',
    order: '同位素阶数',
    sample: '样本',
    abs_ppm_error: '绝对 ppm 误差',
    ppm_error: '带符号 ppm 误差',
    theoretical_ratio: '理论比例',
    observed_ratio: '实测比例',
    valid_cells: '有效细胞数',
    matched: '自动命中',
    review: '人工状态',
  }
  const sorting = computed(() => ({
    candidate_sort: candidateSort.value,
    candidate_descending: candidateDescending.value,
    relation_sort: relationSort.value,
    relation_descending: relationDescending.value,
  }))
  watch(
    [candidateSort, candidateDescending, relationSort, relationDescending],
    () => void loadResults(true),
  )
  const options = reactive({
    database: '',
    polarity: 'pos',
    adducts: ['[M+H]+', '[M+Na]+', '[M+K]+', '[M+NH4]+'],
    annotation_ppm: 10,
    isotope_ppm: 10,
    max_isotope_order: 3,
    isotope_tolerance: 0.2,
    min_valid_cells: 20,
    intensity_layer: '',
    resolution: 35000,
    network: {
      method: 'spearman',
      support_all: 0.8,
      support_joint: 0.7,
      min_joint_cells: 30,
      plot_threshold: 0.7,
      consensus_fraction: 2 / 3,
      min_support_samples: 2,
      condition_field: '',
      samples: [] as string[],
      conditions: [] as string[],
      molecule_layer: 'total',
    },
  })
  const filters = reactive({
    query: '',
    category: '',
    main_class: '',
    sub_class: '',
    candidates: 'all',
    isotopes: 'all',
    review: 'all',
    adduct_mode: 'all',
    adducts: [] as string[],
    include_unannotated: true,
  })
  watch(
    () => filters.category,
    () => {
      filters.main_class = ''
      filters.sub_class = ''
    },
  )
  watch(
    () => filters.main_class,
    () => {
      filters.sub_class = ''
    },
  )
  function classificationChoices(field: string) {
    const tree = results.value?.classification_tree ?? []
    return [
      ...new Set(
        tree
          .filter(
            (row) =>
              (field === 'CATEGORY' || !filters.category || row.CATEGORY === filters.category) &&
              (field !== 'SUB_CLASS' ||
                !filters.main_class ||
                row.MAIN_CLASS === filters.main_class),
          )
          .map((row) => row[field]!)
          .filter(Boolean),
      ),
    ].sort()
  }
  const featureIndex = computed(
    () => results.value?.features.findIndex((f) => f.id === feature.value) ?? -1,
  )
  const validVersion = computed(
    () => info.value?.versions.find((v) => v.id === version.value)?.valid ?? false,
  )
  const infoReads = useReadScope(
    () => [
      store.current?.workspace_id,
      store.project?.path,
      store.project?.dataset?.id,
      store.project?.dataset?.revision,
    ],
    () => void refresh(),
  )
  let generation = 0
  let queryGeneration = 0
  let restoredVersion = ''

  async function refresh(reset = false) {
    const token = ++generation
    const ticket = infoReads.begin()
    const accept = () => ticket() && token === generation
    const workspace = store.current?.workspace_id
    const value = await store.read<LipidInfo>('/lipids', undefined, accept)
    if (!value || !accept() || workspace !== store.current?.workspace_id) return
    info.value = value
    if (reset) {
      version.value = value.active
      options.intensity_layer = value.default_layer
      options.resolution = value.resolution ?? 35000
      options.database = value.database.files[0]?.filename ?? ''
      imported.value = false
      rules.value = { schema_version: 1, name: '', rules: [] }
      results.value = undefined
      restoredVersion = ''
      feature.value = ''
    }
  }
  watch(
    [
      () => store.project?.path,
      () => store.project?.dataset?.id,
      () => store.project?.dataset?.revision,
    ],
    async () => {
      results.value = undefined
      version.value = ''
      await refresh(true)
      if (version.value && validVersion.value) {
        const notice = store.notice
        if (await loadResults(true)) store.notice = notice
      }
    },
    { immediate: true },
  )
  watch(
    () => options.polarity,
    () => {
      options.adducts = Object.entries(info.value?.adducts ?? {})
        .filter(([, spec]) => options.polarity === 'both' || spec.polarity === options.polarity)
        .map(([name]) => name)
    },
  )

  async function prepare() {
    const value = await store.command('/lipids/database')
    if (!value) return
    await refresh()
    options.database = info.value?.database.files[0]?.filename ?? ''
    if (!store.error) store.notice = '本地脂质数据库已校验。'
  }
  async function loadResults(reset = false): Promise<boolean> {
    if (!version.value || !validVersion.value || store.busy) return false
    if (reset) {
      offset.value = 0
      relationOffset.value = 0
    }
    const token = ++queryGeneration
    const workspace = store.current?.workspace_id
    const selectedVersion = version.value
    const value = await store.inspect<LipidResults>('/lipids/query', {
      version: selectedVersion,
      filters: { ...filters, adducts: filters.adduct_mode === 'specified' ? filters.adducts : [] },
      feature_id: feature.value,
      offset: offset.value,
      relation_offset: relationOffset.value,
      sorting: sorting.value,
      limit,
    })
    if (
      !value ||
      token !== queryGeneration ||
      workspace !== store.current?.workspace_id ||
      selectedVersion !== version.value
    )
      return false
    if (restoredVersion !== selectedVersion) {
      restoredVersion = selectedVersion
      if (value.chart_filters && Object.keys(value.chart_filters).length) {
        Object.assign(filters, value.chart_filters)
        return await loadResults(true)
      }
    }
    results.value = value
    if (!imported.value) rules.value = value.rules
    selection.value =
      feature.value in value.selected ? [...value.selected[feature.value]!] : [...value.suggested]
    if (feature.value && !value.features.some((f) => f.id === feature.value)) {
      feature.value = ''
      return await loadResults(true)
    }
    return true
  }
  async function run() {
    const result = await store.mutate(
      '/lipids/run',
      { options, rules: rules.value, label: label.value },
      'POST',
      '',
    )
    if (!result) return
    await refresh()
    version.value = info.value?.active ?? ''
    feature.value = ''
    imported.value = false
    if (await loadResults(true)) store.notice = '注释与同位素版本已生成；矩阵强度和特征保留。'
  }
  async function activate() {
    const value = await store.mutate('/lipids/activate', { version: version.value }, 'POST', '')
    if (value) {
      await refresh()
      if (version.value) {
        if (await loadResults(true)) store.notice = '已切换注释版本。'
      } else {
        results.value = undefined
        if (!store.error) store.notice = '已切回未注释状态。'
      }
    }
  }
  async function selectFeature(id: string) {
    feature.value = id
    await loadResults(true)
  }
  async function changeVersion() {
    results.value = undefined
    imported.value = false
    feature.value = ''
    await loadResults(true)
  }
  async function applyFilters() {
    feature.value = ''
    await loadResults(true)
  }
  async function moveFeature(step: number) {
    const next = results.value?.features[featureIndex.value + step]
    if (next) await selectFeature(next.id)
  }
  async function saveSelection(auto = false) {
    const value = await store.mutate(
      '/lipids/review',
      {
        version: version.value,
        feature_id: feature.value,
        candidate_ids: auto ? null : selection.value,
      },
      'POST',
      '',
    )
    if (value && (await loadResults()))
      store.notice = auto ? '已恢复规则推荐。' : '人工指定已保存。'
  }
  async function reviewRelation(id: unknown, review: string) {
    const value = await store.mutate('/lipids/review', {
      version: version.value,
      relation_id: id,
      review,
    })
    if (value) {
      await refresh()
      if (await loadResults()) store.notice = '同位素核对已保存。'
    }
  }
  async function pageCandidates(step: number) {
    offset.value = Math.max(0, offset.value + step * limit)
    await loadResults()
  }
  async function pageRelations(step: number) {
    relationOffset.value = Math.max(0, relationOffset.value + step * limit)
    await loadResults()
  }

  async function download(kind: string) {
    if (!store.current || !version.value) return
    const workspace = store.current.workspace_id
    const revision = store.current.revision
    await store.run(
      async (scope) => {
        const blob = await workspaceBlob('/lipids/export', {
          workspace,
          method: 'POST',
          body: {
            revision,
            version: version.value,
            filters: {
              ...filters,
              adducts: filters.adduct_mode === 'specified' ? filters.adducts : [],
            },
            kind,
            sorting: sorting.value,
          },
          isCurrent: () =>
            scope.isCurrent() &&
            store.current?.workspace_id === workspace &&
            store.current?.revision === revision,
        })
        saveBlob(blob, `lipid-${kind}.${kind === 'rules' ? 'json' : 'csv'}`)
      },
      '',
      { label: '导出脂质分析结果', phase: 'downloading' },
    )
  }
  function number(value: unknown) {
    return typeof value === 'number' ? value.toPrecision(6) : '—'
  }
  useViewState('lipids', {
    version,
    label,
    feature,
    selection,
    offset,
    relationOffset,
    isotopeFigure,
    candidateSort,
    candidateDescending,
    relationSort,
    relationDescending,
  })

  return {
    store,
    auth,
    info,
    results,
    isotopeFigure,
    rules,
    imported,
    preset,
    presetName,
    version,
    label,
    feature,
    selection,
    offset,
    relationOffset,
    ruleOffset,
    candidateSort,
    relationSort,
    candidateSortOptions,
    relationSortOptions,
    sorting,
    limit,
    options,
    filters,
    rulesTable,
    featureIndex,
    validVersion,
    viewIsotope,
    classificationChoices,
    prepare,
    loadResults,
    run,
    importFile,
    choosePreset,
    savePreset,
    applyRules,
    activate,
    selectFeature,
    changeVersion,
    applyFilters,
    moveFeature,
    saveSelection,
    reviewRelation,
    pageCandidates,
    pageRelations,
    download,
    template,
    number,
    candidateDescending,
    relationDescending,
  }
}
