<script setup lang="ts">
import { useViewState } from '../../api/viewState'
import {
  ref,
  computed,
  watch,
  onMounted,
  onUnmounted,
  onActivated,
  onDeactivated,
  nextTick,
} from 'vue'
import { request } from '../../api/client'
import type { Figure, DataTable, Job } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'
import { useAuth } from '../../stores/auth'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
import ProcessingFields from './ProcessingFields.vue'
const store = useWorkspace()
const auth = useAuth()
const sample = ref(''),
  opened = ref(''),
  summary = ref<Record<string, unknown>>()
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
const job = ref<Job>(),
  jobNote = ref(''),
  cellCount = ref<number>()
const preferences = ref<{ presets: Record<string, number>; selected: string }>(),
  preset = ref(''),
  presetText = ref('')
const strategy = ref('shared'),
  mergePpm = ref(10),
  autoRanges = ref(true)
let parameterGeneration = 0
let editGeneration = 0,
  jobGeneration = 0,
  timer: ReturnType<typeof setTimeout> | undefined,
  loading = false
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
  void nextTick(() => document.getElementById(`parameter-tab-${parameterCategory.value}`)?.focus())
}
const scanCatalog = ref<{ indices: number[]; times: number[] }>({ indices: [], times: [] })
const scanTime = ref(0)
const selectRange = ref(false)
function selectedRange(range: [number, number]) {
  rtMin.value = String(Math.min(...range))
  rtMax.value = String(Math.max(...range))
  store.notice = '合谱显示范围已选择；切换“合并谱”并更新图形。'
}
const scanPosition = computed(() => scanCatalog.value.indices.indexOf(scan.value))
async function scans() {
  const selected = sample.value
  const level = ms.value
  const value = await store.read<{ indices: number[]; times: number[] }>(
    `/raw/scans?sample_id=${selected}&ms_level=${level}`,
  )
  if (value && sample.value === selected && ms.value === level) {
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
  if (opened.value) {
    plots.value = {}
    void scans()
  }
})
const currentPlot = computed(() => plots.value[kind.value])
function edited() {
  editGeneration++
  delete plots.value.cells
  cellCount.value = undefined
  if (job.value) jobNote.value = '参数已编辑；运行中的旧预览完成后不会应用。'
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
  refs.value = String(parameters.value.reference_mz || parameters.value.ref_mz || '')
}
async function loadParameters() {
  const token = ++parameterGeneration
  opened.value = ''
  summary.value = undefined
  plots.value = {}
  job.value = undefined
  editGeneration++
  if (!store.project) return
  const data = await store.read<Record<string, unknown>>(
    `/parameters${sample.value ? `?sample_id=${sample.value}` : ''}`,
  )
  if (data && token === parameterGeneration) assignParams(data)
}
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
async function open() {
  const value = await store.command<{
    summary: Record<string, unknown>
    parameters: Record<string, unknown>
  }>('/raw/open', { sample_id: sample.value })
  if (!value) return
  opened.value = sample.value
  summary.value = value.summary
  const levels = value.summary.scans_by_ms_level as number[][]
  if (!levels.some((level) => level[0] === ms.value)) ms.value = levels[0]?.[0] ?? 1
  assignParams(value.parameters)
  mzMin.value = Number(value.parameters.mz_min)
  mzMax.value = Number(value.parameters.mz_max)
  scan.value = 0
  plots.value = {}
  await scans()
  await plot('tic')
  const first = plots.value.tic?.table.rows[0]?.scan_index
  if (typeof first === 'number') scan.value = first
  await plot('single')
}
async function plot(selected = kind.value) {
  if (!opened.value || loading) return
  loading = true
  const capture = opened.value
  const body = {
    sample_id: sample.value,
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
      rtMin.value !== '' && rtMax.value !== '' ? [Number(rtMin.value), Number(rtMax.value)] : null,
    fast: fast.value,
    bins: bins.value,
    normalize: normalize.value,
    resolution: Number(parameters.value.resolution),
    points_per_fwhm: Number(parameters.value.resample_points_per_fwhm),
  }
  await store.run(async () => {
    const data = await request<{
      figure: Figure
      table: DataTable
      detail: Record<string, unknown>
    }>('/workspace/raw/plot', { method: 'POST', workspace: store.current!.workspace_id, body })
    if (opened.value === capture) plots.value[selected] = data
  })
  loading = false
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
async function apply() {
  const result = await store.mutate(
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
    '提取参数已应用；旧提取结果不会自动更新。',
  )
  if (result) {
    const current = await store.read<Record<string, unknown>>(
      `/parameters${sample.value ? `?sample_id=${sample.value}` : ''}`,
    )
    if (current) effectiveParameters.value = current
    edited()
  }
}
async function startPreview() {
  const value = await store.command<Job>('/raw/preview', {
    sample_id: sample.value,
    parameters: valueParams(),
  })
  if (value) {
    job.value = value
    jobGeneration = editGeneration
    jobNote.value = '细胞预览已启动，可继续操作其他步骤。'
  }
}
async function poll() {
  if (!job.value || !store.project) return
  const status = await store.read<Job | null>('/raw/preview')
  if (!status || status.id !== job.value.id) return
  job.value = status
  if (status.status === 'failed') {
    jobNote.value = status.message
    store.task = `细胞预览：${status.message}`
    job.value = undefined
    return
  }
  if (status.status !== 'ready') {
    jobNote.value = status.message
    store.task = `细胞预览：${status.message}`
    return
  }
  if (store.busy) return
  if (jobGeneration !== editGeneration || status.revision !== store.current?.revision) {
    jobNote.value = '样本或参数已改变，旧预览未应用，请重新预览。'
    job.value = undefined
    return
  }
  const value = await store.command<{
    figure: Figure
    table: DataTable
    parameters: Record<string, unknown>
    cell_count: number
    reused: boolean
  }>('/raw/preview/collect', { job_id: status.id })
  job.value = undefined
  if (value) {
    assignParams(value.parameters)
    plots.value.cells = value
    cellCount.value = value.cell_count
    kind.value = 'cells'
    jobNote.value = `预览完成，${value.cell_count} 个细胞${value.reused ? '，已复用有效缓存' : ''}。项目仍需主动保存。`
  }
}
onMounted(async () => {
  preferences.value = await request('/preferences')
  preset.value = String(store.project?.manifest.cell_type ?? preferences.value?.selected ?? '')
  presetText.value = JSON.stringify(preferences.value?.presets, null, 2)
  startPolling()
})
let pollingActive = false
async function tick() {
  try {
    await poll()
  } finally {
    if (pollingActive) timer = setTimeout(tick, 1500)
  }
}
function startPolling() {
  if (pollingActive) return
  pollingActive = true
  timer = setTimeout(tick, 1500)
}
onActivated(startPolling)
onDeactivated(() => {
  pollingActive = false
  clearTimeout(timer)
})
onUnmounted(() => {
  pollingActive = false
  clearTimeout(timer)
})
function usePreset() {
  const mass = preferences.value?.presets[preset.value]
  if (mass) {
    parameters.value.ref_mz = mass
    edited()
  }
}
async function savePresets() {
  await store.run(async () => {
    preferences.value = await request('/preferences', {
      method: 'PUT',
      body: { presets: JSON.parse(presetText.value), selected: preset.value },
    })
  }, '全局预设已保存；已有项目参数由明确应用决定。')
}
useViewState('raw', {
  sample,
  opened,
  summary,
  parameters,
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
  jobNote,
  cellCount,
  effectiveParameters,
  applicationScope,
  strategy,
  mergePpm,
  autoRanges,
  preset,
})
</script>
<template>
  <section v-if="store.project">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 02 / 原始谱</p>
        <h1>原始谱与参数</h1>
        <p>检查采集信号，选择实验参考离子，再预览细胞窗口。</p>
      </div>
      <span class="step-badge">02 / 06</span>
    </div>
    <div class="card raw-sample-toolbar">
      <div class="field-grid">
        <label
          ><FieldLabel name="当前样本" /><select
            aria-label="当前样本"
            v-model="sample"
            :disabled="store.busy"
          >
            <option value="" disabled>选择样本</option>
            <option v-for="s in samples" :key="s.id" :value="s.id">
              {{ s.name }}{{ s.parameters ? ' · 样本例外' : '' }}
            </option>
          </select></label
        >
      </div>
      <div class="actions">
        <button class="primary" :disabled="!sample || store.busy" @click="open">
          打开原始文件
        </button>
      </div>
      <details v-if="summary" class="raw-file-details">
        <summary>
          原始文件详情 · {{ summary.scan_count }} 扫描 · {{ summary.instrument || '仪器未标注' }}
        </summary>
        <dl class="detail-list">
          <div>
            <dt>原始文件</dt>
            <dd>{{ summary.path }}</dd>
          </div>
          <div>
            <dt>扫描 / 仪器</dt>
            <dd>{{ summary.scan_count }} / {{ summary.instrument || '—' }}</dd>
          </div>
          <div>
            <dt>RT / m/z</dt>
            <dd>
              {{ summary.rt_min_seconds }}–{{ summary.rt_max_seconds }} 秒 / {{ summary.mz_min }}–{{
                summary.mz_max
              }}
            </dd>
          </div>
        </dl>
      </details>
    </div>
    <div class="workflow-columns raw-workflow">
      <div class="card raw-parameter-panel">
        <h2>提取参数</h2>
        <p class="muted">参考离子须依据实验明确选择。显示范围单独设置。</p>
        <p class="method-badge">
          <FieldLabel
            name="提取方法：snr"
            text="固定使用 SNR 提取：按参考离子识别细胞窗口，扣除基线并以背景噪声衡量特征信号。内部标识 snr_v1 保留用于旧项目与产物兼容。"
          />
        </p>
        <p v-if="legacyParameters" class="alert">
          此项目或样本仍保存 legacy 参数。当前表单已切换为
          snr，请检查并应用参数后启动新提取；旧产物保留原算法记录。
        </p>
        <div class="reference-preset">
          <label
            ><FieldLabel name="Cell type" /><select
              aria-label="Cell type"
              v-model="preset"
              :disabled="store.busy"
            >
              <option v-for="(mass, name) in preferences?.presets" :key="name" :value="name">
                {{ name }} · {{ mass }}
              </option>
            </select></label
          >

          <button :disabled="store.busy" @click="usePreset">使用所选参考离子</button>
        </div>
        <ProcessingFields
          v-model="parameters"
          :fields="basic"
          :disabled="store.busy"
          @edited="edited"
        />
        <button
          type="button"
          class="parameter-toggle"
          :aria-expanded="expanded"
          aria-controls="extraction-advanced"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起扩展参数' : '展开全部参数' }}
          <span aria-hidden="true">{{ expanded ? '▴' : '▾' }}</span>
        </button>
        <section
          v-if="expanded"
          id="extraction-advanced"
          class="parameter-advanced"
          aria-label="分类提取参数"
        >
          <div class="parameter-categories" role="tablist" aria-label="参数分类">
            <button
              v-for="item in categories"
              :id="`parameter-tab-${item.key}`"
              :key="item.key"
              type="button"
              role="tab"
              :aria-selected="parameterCategory === item.key"
              :tabindex="parameterCategory === item.key ? 0 : -1"
              @keydown="navigateCategory"
              aria-controls="parameter-category-panel"
              :class="{ selected: parameterCategory === item.key }"
              @click="parameterCategory = item.key"
            >
              {{ item.label }}
            </button>
          </div>
          <div
            id="parameter-category-panel"
            role="tabpanel"
            :aria-labelledby="`parameter-tab-${parameterCategory}`"
          >
            <ProcessingFields
              v-model="parameters"
              :fields="category.fields"
              :disabled="store.busy"
              @edited="edited"
            />
            <div v-if="parameterCategory === 'reference'" class="parameter-controls">
              <label class="parameter-field"
                ><FieldLabel name="auto_ranges" /><select
                  aria-label="auto_ranges"
                  v-model="autoRanges"
                  :disabled="store.busy"
                  @change="edited"
                >
                  <option :value="true">启用自动范围</option>
                  <option :value="false">关闭自动范围</option>
                </select></label
              >
            </div>
            <div v-if="parameterCategory === 'merge'" class="parameter-controls">
              <label class="parameter-field"
                ><FieldLabel name="feature_strategy" /><select
                  aria-label="feature_strategy"
                  v-model="strategy"
                  :disabled="store.busy"
                  @change="edited"
                >
                  <option>shared</option>
                  <option>independent</option>
                </select></label
              >
              <label v-if="strategy === 'independent'" class="parameter-field"
                ><FieldLabel name="feature_merge_ppm" /><input
                  aria-label="feature_merge_ppm"
                  v-model.number="mergePpm"
                  type="number"
                  min="0"
                  step="any"
                  :disabled="store.busy"
                  @input="edited"
              /></label>
            </div>
            <template v-if="parameterCategory === 'presets'">
              <label class="field"
                ><FieldLabel name="预设名称与参考 m/z（JSON）" /><textarea
                  aria-label="预设名称与参考 m/z（JSON）"
                  v-model="presetText"
                  rows="5"
                  :disabled="store.busy"
                ></textarea>
              </label>
              <button v-if="auth.admin" class="save" :disabled="store.busy" @click="savePresets">
                保存全局预设
              </button>
            </template>
          </div>
        </section>
        <div class="parameter-state" :class="{ pending: unapplied }" aria-label="参数生效状态">
          <strong>{{ unapplied ? '与所选范围的生效配置不同' : '与所选范围的生效配置一致' }}</strong>
          <p>
            当前样本使用{{
              samples.find((s) => s.id === sample)?.parameters ? '样本例外' : '项目默认及自动范围'
            }}。{{
              differsFromCurrent
                ? '表单与当前样本正式提取参数不同；预览使用表单参数。'
                : '表单与当前样本正式提取参数一致。'
            }}
          </p>
          <p v-if="applicationScope === 'sample'">
            样本合并策略、合并容差及自动范围仍为项目级设置。
          </p>
          <p>应用后仍需保存项目；已完成的提取结果保持原参数记录。</p>
        </div>
        <div class="actions parameter-apply-actions">
          <label class="application-scope"
            >应用范围<select
              aria-label="参数应用范围"
              v-model="applicationScope"
              :disabled="store.busy"
            >
              <option value="project">项目默认（保留样本例外）</option>
              <option value="sample">仅当前样本</option>
            </select></label
          >
          <button
            class="primary"
            :disabled="store.busy || (applicationScope === 'sample' && !sample)"
            @click="apply"
          >
            应用参数</button
          ><button
            class="restore"
            :disabled="!sample || store.busy"
            @click="store.mutate('/parameters/clear', { sample_id: sample }).then(loadParameters)"
          >
            清除样本例外</button
          ><button
            class="preview"
            :disabled="opened !== sample || !!job || store.busy"
            @click="startPreview"
          >
            预览细胞窗口
          </button>
        </div>
        <p v-if="jobNote" role="status">{{ jobNote }}</p>
      </div>
      <div class="card">
        <h2>原始信号</h2>
        <div class="tabs">
          <button
            v-for="(label, value) in {
              tic: 'TIC',
              eic: 'EIC',
              sum: '合并谱',
              single: '单扫描',
              cells: '细胞窗口',
            }"
            :key="value"
            :class="{ selected: kind === value }"
            @click="kind = value"
          >
            {{ label }}
          </button>
        </div>
        <div v-if="kind !== 'cells'" class="field-grid">
          <label
            ><FieldLabel name="MS level" /><input
              aria-label="MS level"
              v-model.number="ms"
              type="number"
              min="1"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="RT min（秒，空值全范围）" /><input
              aria-label="RT min（秒，空值全范围）"
              v-model="rtMin"
              type="number"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="RT max（秒）" /><input
              aria-label="RT max（秒）"
              v-model="rtMax"
              type="number"
              :disabled="store.busy" /></label
          ><template v-if="kind === 'eic'"
            ><label
              ><FieldLabel name="reference m/z" /><input
                aria-label="reference m/z"
                v-model="refs"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="ppm tolerance" /><input
                aria-label="ppm tolerance"
                v-model.number="ppm"
                type="number"
                step="any"
                :disabled="store.busy" /></label></template
          ><template v-if="kind === 'sum'"
            ><label
              ><FieldLabel name="display mz_min" /><input
                aria-label="display mz_min"
                v-model.number="mzMin"
                type="number"
                step="any"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="display mz_max" /><input
                aria-label="display mz_max"
                v-model.number="mzMax"
                type="number"
                step="any"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="合谱方式" /><select
                aria-label="合谱方式"
                v-model="fast"
                :disabled="store.busy"
              >
                <option :value="true">快速固定网格</option>
                <option :value="false">高分辨率合谱</option>
              </select></label
            ><label
              ><FieldLabel name="bins" /><input
                aria-label="bins"
                v-model.number="bins"
                type="number"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="normalize" /><select
                aria-label="normalize"
                v-model="normalize"
                :disabled="store.busy"
              >
                <option :value="false">求和</option>
                <option :value="true">平均</option>
              </select></label
            ></template
          ><label v-if="kind === 'single'"
            ><FieldLabel name="scan_index（从 0 开始）" /><input
              aria-label="scan_index（从 0 开始）"
              v-model.number="scan"
              type="number"
              min="0"
              :max="Number(summary?.scan_count ?? 1) - 1"
              :disabled="store.busy"
          /></label>
        </div>
        <div class="actions">
          <button
            v-if="kind !== 'cells'"
            class="primary"
            :disabled="opened !== sample || store.busy"
            @click="plot()"
          >
            更新图形</button
          ><button
            v-if="kind === 'single'"
            :disabled="scanPosition <= 0 || store.busy"
            @click="seekScan('step', -1)"
          >
            上一帧</button
          ><button
            v-if="kind === 'single'"
            :disabled="scanPosition >= scanCatalog.indices.length - 1 || store.busy"
            @click="seekScan('step', 1)"
          >
            下一帧</button
          ><button
            v-if="currentPlot"
            class="save"
            :disabled="store.busy"
            @click="store.download('raw', `${kind}.csv`, kind)"
          >
            下载完整数据 CSV
          </button>
        </div>
        <div v-if="kind === 'single' && scanCatalog.indices.length" class="field-grid">
          <label
            ><FieldLabel name="scan time（秒）" /><input
              aria-label="scan time（秒）"
              :value="scanTime"
              type="number"
              step="any"
              :disabled="store.busy"
              @change="
                seekScan('time', Number(($event.target as HTMLInputElement).value))
              " /></label
          ><label
            ><FieldLabel name="时间滑块" /><input
              aria-label="时间滑块"
              :value="scanTime"
              type="range"
              :min="scanCatalog.times[0]"
              :max="scanCatalog.times.at(-1)"
              step="any"
              :disabled="store.busy"
              @change="seekScan('time', Number(($event.target as HTMLInputElement).value))"
          /></label>
        </div>
        <p v-if="cellCount !== undefined && kind === 'cells'">
          检出 {{ cellCount }} 个细胞；预览不会直接建立当前数据。
        </p>
        <dl
          v-if="currentPlot?.detail && Object.keys(currentPlot.detail).length"
          class="detail-list"
        >
          <div v-for="(value, key) in currentPlot.detail" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ value }}</dd>
          </div>
        </dl>
        <label v-if="['tic', 'eic', 'cells'].includes(kind)"
          ><FieldLabel name="拖动方式" /><select
            aria-label="拖动方式"
            v-model="selectRange"
            :disabled="store.busy"
          >
            <option :value="false">缩放</option>
            <option :value="true">选择合谱范围</option>
          </select></label
        >
        <PlotView
          v-if="currentPlot"
          :key="kind"
          :figure="currentPlot.figure"
          :name="`raw-${kind}`"
          :select-range="selectRange && ['tic', 'eic', 'cells'].includes(kind)"
          @range="selectedRange"
        />
        <p v-else class="muted">打开样本并生成图形后显示。</p>
      </div>
    </div>
  </section>
  <div v-else class="card empty-state">
    <h1>请先打开项目</h1>
    <RouterLink to="/projects">前往项目首页 →</RouterLink>
  </div>
</template>
