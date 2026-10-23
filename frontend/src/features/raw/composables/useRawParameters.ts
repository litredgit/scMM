import { ref, computed, watch, onMounted, nextTick, type Ref } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import { request } from '../../../api/client'
import type { AnalysisTransport } from '../../analysis/types'

type Binding = {
  reset(): void
  edited(): void
  assigned(value: Record<string, unknown>): void
}
export function useRawParameters(sample: Ref<string>) {
  const store = useWorkspace()
  let binding: Binding | undefined
  function edited() {
    binding?.edited()
  }
  const parameters = ref<Record<string, unknown>>({})
  const effectiveParameters = ref<Record<string, unknown>>({})
  const applicationScope = ref('project')
  function parameterSignature(value: Record<string, unknown>) {
    return JSON.stringify(
      Object.keys(value)
        .sort()
        .map((key) => [key, value[key]]),
    )
  }
  const differsFromCurrent = computed(
    () => parameterSignature(valueParams()) !== parameterSignature(effectiveParameters.value),
  )
  const unapplied = computed(() => {
    const target =
      applicationScope.value === 'sample'
        ? effectiveParameters.value
        : (store.project?.manifest.parameters ?? {})
    return (
      parameterSignature(valueParams()) !== parameterSignature(target) ||
      strategy.value !== store.project?.manifest.feature_strategy ||
      mergePpm.value !== Number(store.project?.manifest.feature_merge_ppm ?? 10) ||
      autoRanges.value !== Boolean(store.project?.manifest.auto_ranges ?? true)
    )
  })
  const preferences = ref<{ presets: Record<string, number>; selected: string }>(),
    preset = ref(''),
    presetText = ref('')
  const strategy = ref('shared'),
    mergePpm = ref(10),
    autoRanges = ref(true)
  let parameterGeneration = 0
  const legacyParameters = computed(() => {
    const item = samples.value.find((s) => s.id === sample.value)
    return (item?.parameters ?? store.project?.manifest.parameters)?.extraction_method === 'legacy'
  })
  const samples = computed(() => store.project?.manifest.samples ?? [])
  const basic = [
    'ref_mz',
    'mz_min',
    'mz_max',
    'cell_snr',
    'cell_min_signal',
    'feature_snr_threshold',
    'max_zero_frac',
  ]
  const expanded = ref(false)
  const parameterCategory = ref('reference')
  const categories = [
    {
      key: 'reference',
      label: '参考与范围',
      fields: ['reference_mz', 'reference_mode', 'reference_ppm_tol'],
    },
    { key: 'noise', label: '细胞与噪声', fields: ['baseline_filter_size', 'noise_window'] },
    {
      key: 'spectrum',
      label: '合谱与对齐',
      fields: ['ppm_tol', 'resolution', 'resample_points_per_fwhm', 'ms_peak_snr_threshold'],
    },
    { key: 'merge', label: '样本合并', fields: [] },
    { key: 'resources', label: '计算资源', fields: ['n_jobs', 'feature_block_size'] },
    { key: 'presets', label: '参考预设', fields: [] },
  ]
  const category = computed(() => categories.find((item) => item.key === parameterCategory.value)!)
  function navigateCategory(event: KeyboardEvent) {
    const index = categories.findIndex((item) => item.key === parameterCategory.value)
    const target =
      event.key === 'ArrowRight'
        ? (index + 1) % categories.length
        : event.key === 'ArrowLeft'
          ? (index + categories.length - 1) % categories.length
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? categories.length - 1
              : -1
    if (target < 0) return
    event.preventDefault()
    parameterCategory.value = categories[target]!.key
    void nextTick(() =>
      document.getElementById(`parameter-tab-${parameterCategory.value}`)?.focus(),
    )
  }
  function valueParams() {
    const result = { ...parameters.value }
    result.reference_mz =
      typeof result.reference_mz === 'string'
        ? String(result.reference_mz)
            .split(/[,，\s]+/)
            .filter(Boolean)
            .map(Number)
        : result.reference_mz
    return result
  }
  function assignParams(value: Record<string, unknown>) {
    effectiveParameters.value = { ...value }
    parameters.value = {
      ...value,
      extraction_method: 'snr_v1',
      reference_mz: Array.isArray(value.reference_mz)
        ? value.reference_mz.join(', ')
        : value.reference_mz,
    }
    binding?.assigned(parameters.value)
  }
  async function loadParameters(api: AnalysisTransport = store) {
    const token = ++parameterGeneration
    binding?.reset()
    if (!store.project) return
    const data = await api.read<Record<string, unknown>>(
      `/parameters${sample.value ? `?sample_id=${sample.value}` : ''}`,
    )
    if (data && token === parameterGeneration) assignParams(data)
  }
  async function apply() {
    await store.analysisTransaction(async (api) => {
      await api.mutate(
        '/parameters',
        {
          parameters: valueParams(),
          sample_id: applicationScope.value === 'sample' ? sample.value : null,
          strategy: strategy.value,
          merge_ppm: mergePpm.value,
          auto_ranges: autoRanges.value,
          cell_type: preset.value || null,
        },
        'PUT',
      )
      try {
        const current = await api.read<Record<string, unknown>>(
          `/parameters${sample.value ? `?sample_id=${sample.value}` : ''}`,
        )
        if (current) effectiveParameters.value = current
        edited()
        store.notice = '提取参数已应用；旧提取结果不会自动更新。'
      } catch (cause) {
        if (api.isCurrent?.() !== false)
          store.error = `参数已应用；读取生效值失败，请刷新核对。${cause instanceof Error ? cause.message : String(cause)}`
      }
    })
  }
  async function clearParameters() {
    await store.analysisTransaction(async (api) => {
      await api.mutate('/parameters/clear', { sample_id: sample.value })
      await loadParameters(api)
    })
  }
  onMounted(async () => {
    preferences.value = await request('/preferences')
    preset.value = String(store.project?.manifest.cell_type ?? preferences.value?.selected ?? '')
    presetText.value = JSON.stringify(preferences.value?.presets, null, 2)
  })
  function usePreset() {
    const mass = preferences.value?.presets[preset.value]
    if (mass) {
      parameters.value.ref_mz = mass
      edited()
    }
  }
  async function savePresets() {
    await store.run(
      async () => {
        preferences.value = await request('/preferences', {
          method: 'PUT',
          body: { presets: JSON.parse(presetText.value), selected: preset.value },
        })
      },
      '全局预设已保存；已有项目参数由明确应用决定。',
      { label: '保存参考预设', phase: 'submitting' },
    )
  }
  function connect(value: Binding) {
    binding = value
    watch(
      () => store.project?.path,
      () => {
        expanded.value = false
        parameterCategory.value = 'reference'
        sample.value = samples.value[0]?.id ?? ''
        strategy.value = store.project?.manifest.feature_strategy ?? 'shared'
        mergePpm.value = Number(store.project?.manifest.feature_merge_ppm ?? 10)
        autoRanges.value = Boolean(store.project?.manifest.auto_ranges ?? true)
        void loadParameters()
      },
      { immediate: true },
    )
    watch(sample, () => void loadParameters())
  }

  return {
    parameters,
    effectiveParameters,
    applicationScope,
    differsFromCurrent,
    unapplied,
    preferences,
    preset,
    presetText,
    strategy,
    mergePpm,
    autoRanges,
    legacyParameters,
    samples,
    basic,
    expanded,
    parameterCategory,
    categories,
    category,
    navigateCategory,
    valueParams,
    assignParams,
    apply,
    clearParameters,
    edited,
    usePreset,
    savePresets,
    connect,
  }
}
