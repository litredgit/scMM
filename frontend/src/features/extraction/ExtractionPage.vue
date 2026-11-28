<script setup lang="ts">
import ProcessingFields from '../raw/ProcessingFields.vue'
import MatrixDownload from '../../components/MatrixDownload.vue'
import { formatTime } from '../../help/time'
import { displayName } from '../../help/labels'
import { useViewState } from '../../api/viewState'
import { serialPolling } from '../../api/polling'
import { useReadScope } from '../../api/readScope'
import {
  ref,
  shallowRef,
  computed,
  watch,
  onMounted,
  onUnmounted,
  onActivated,
  onDeactivated,
} from 'vue'
import type { Batch, Figure } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'
import PlotView from '../../components/PlotView.vue'
import TrashAction from '../../components/TrashAction.vue'
import BatchComparison from './BatchComparison.vue'
import BatchSpectrum from './BatchSpectrum.vue'
import FeatureSource from './FeatureSource.vue'
import PreflightSamples from './PreflightSamples.vue'
const store = useWorkspace()
const featureSourcePending = ref(false)
const reviewPhase = ref('')
const counts = computed(() => {
  const samples = selected.value?.samples ?? []
  return {
    total: samples.length || store.project?.manifest.samples.length || 0,
    success: samples.filter((s) => s.status === 'succeeded').length,
    failed: samples.filter((s) => s.status === 'failed').length,
    waiting: samples.filter((s) => s.status === 'waiting' || s.status === 'queued').length,
  }
})
const signalSample = ref(''),
  signalFigure = shallowRef<Figure>()
async function loadSignal() {
  const accept = signalScope.begin()
  const result = await store.inspect<{ value: { figure: Figure } }>(
    '/extraction/signal',
    {
      path: path.value,
      sample_id: signalSample.value,
    },
    accept,
  )
  if (accept() && result) signalFigure.value = result.value.figure
}

const batchList = ref<Batch[]>([]),
  path = ref(''),
  included = ref<string[]>([]),
  checked = ref<Record<string, unknown>>(),
  figures = shallowRef<Figure[]>([])
const signalScope = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  path.value,
  signalSample.value,
])
const checkedSamples = computed(
  () =>
    (checked.value?.samples ?? []) as {
      id: string
      name: string
      parameter_source: string
      parameters: { mz_min: number; mz_max: number; ref_mz: number }
    }[],
)
watch(
  signalSample,
  () => {
    signalFigure.value = undefined
  },
  { flush: 'sync' },
)
const selections = ref<Record<string, { ids: string[]; initialized: boolean }>>({})
function rememberSelection() {
  if (path.value) selections.value[path.value] = { ids: [...included.value], initialized: true }
}
function selectAllSuccesses() {
  included.value = (selected.value?.samples ?? [])
    .filter((s) => s.status === 'succeeded')
    .map((s) => s.id)
  rememberSelection()
}
function clearSelection() {
  included.value = []
  rememberSelection()
}
const selected = computed(() => batchList.value.find((b) => b.path === path.value))
const active = computed(() => batchList.value.some((b) => ['queued', 'running'].includes(b.status)))
function label(status: string) {
  return (
    (
      {
        completed: '处理结束，请审核',
        queued: '排队',
        running: '处理中',
        succeeded: '成功',
        failed: '失败',
        stopped: '已停止',
        interrupted: '已中断',
        waiting: '等待',
        skipped: '已跳过',
      } as Record<string, string>
    )[status] ?? status
  )
}
async function refresh(isCurrent: () => boolean) {
  if (!store.project) return
  const result = await store.refreshBatches()
  if (result && isCurrent()) {
    batchList.value = result
    const running = result.find((b) => ['queued', 'running'].includes(b.status))
    if (running) store.task = `提取：${running.message}`
    else if (store.task.startsWith('提取：')) store.task = '提取已结束，等待人工审核'
    if (!result.some((b) => b.path === path.value)) path.value = result[0]?.path ?? ''
    const batch = selected.value
    if (
      batch &&
      !['queued', 'running'].includes(batch.status) &&
      !selections.value[path.value]?.initialized
    ) {
      included.value = batch.samples.filter((s) => s.status === 'succeeded').map((s) => s.id)
      rememberSelection()
    } else
      included.value = included.value.filter((id) =>
        batch?.samples.some((s) => s.id === id && s.status === 'succeeded'),
      )
  }
}
const polling = serialPolling(refresh, 2000, (cause) => {
  store.error = cause instanceof Error ? cause.message : String(cause)
})
watch(
  () => store.project?.path,
  () => {
    selections.value = {}
    path.value = ''
    included.value = []
    checked.value = undefined
    figures.value = []
    batchList.value = []
    void polling.refresh()
  },
  { immediate: true },
)
watch(path, () => {
  signalFigure.value = undefined
  signalSample.value = ''
  included.value = [...(selections.value[path.value]?.ids ?? [])]
  const batch = selected.value
  if (
    batch &&
    !['queued', 'running'].includes(batch.status) &&
    !selections.value[path.value]?.initialized
  ) {
    included.value = batch.samples.filter((s) => s.status === 'succeeded').map((s) => s.id)
    rememberSelection()
  }
  figures.value = []
})
watch(
  () => store.current?.revision,
  () => {
    if (!applyingParameters.value) checked.value = undefined
    figures.value = []
  },
)
onMounted(() => polling.start())
onActivated(() => polling.start())
onDeactivated(polling.stop)
onUnmounted(polling.stop)
async function preflight() {
  checked.value = await store.inspect('/extraction/preflight')
}
function downloadPreflight() {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(checked.value, null, 2)], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = 'preflight.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function start(retry = false) {
  if (Object.keys(pendingParameters.value).length) return
  await submitExtraction(retry)
}
async function submitExtraction(retry = false) {
  const result = await store.command<{ path: string }>('/extraction/start', {
    retry_path: retry ? path.value : null,
  })
  if (result) {
    await polling.refresh()
    path.value = result.path
  }
}
async function review(compare = false) {
  await store.analysisTransaction(async (api) => {
    reviewPhase.value = compare
      ? '正在读取所选样本并生成 QC 对比…'
      : '正在合并所选样本并建立当前数据集…'
    try {
      const value = await api.command<{ figures: Figure[] } | null>('/extraction/review', {
        path: path.value,
        ids: included.value,
        compare,
      })
      if (compare && value) figures.value = value.figures
      else if (!compare) store.notice = '当前数据集已建立，可进入预处理。项目仍需主动保存。'
    } finally {
      reviewPhase.value = ''
    }
  })
}
const parameterDrafts = ref<Record<string, Record<string, unknown>>>({})
const parameterSample = ref('')
const appliedParameters = ref<Record<string, string>>({})
const pendingParameters = computed(() =>
  Object.fromEntries(
    Object.entries(parameterDrafts.value).filter(
      ([id, values]) => JSON.stringify(values) !== appliedParameters.value[id],
    ),
  ),
)
const pendingCount = computed(() => Object.keys(pendingParameters.value).length)
watch(pendingCount, (count) => {
  store.drafts['逐样本提取参数'] = count > 0
})
async function applyAndStart() {
  await store.analysisTransaction(async (api) => {
    const edits = pendingParameters.value
    if (!Object.keys(edits).length) return
    applyingParameters.value = true
    try {
      await api.mutate('/parameters/rows', { edits }, 'PUT')
      markApplied(edits)
      preflightStale.value = true
      const result = await api.command<{ path: string }>('/extraction/start', { retry_path: null })
      if (result) path.value = result.path
    } finally {
      applyingParameters.value = false
    }
  })
  if (path.value) await polling.refresh()
}
function markApplied(edits: Record<string, unknown>) {
  for (const [key, values] of Object.entries(edits))
    appliedParameters.value[key] = JSON.stringify(values)
}
const comparisonPage = ref(0)
const compareParameters = ref(false)
const parameterSections = [
  { title: '参考与提取范围', fields: ['ref_mz', 'mz_min', 'mz_max', 'rt_range', 'frame_range'] },
  {
    title: '细胞识别与噪声',
    fields: ['cell_snr', 'cell_min_signal', 'baseline_filter_size', 'noise_window'],
  },
  { title: '特征保留', fields: ['feature_snr_threshold', 'max_zero_frac'] },
  { title: '多参考离子', fields: ['reference_mz', 'reference_mode', 'reference_ppm_tol'] },
  {
    title: '合谱与对齐',
    fields: ['ppm_tol', 'resolution', 'resample_points_per_fwhm', 'ms_peak_snr_threshold'],
  },
  { title: '计算资源', fields: ['n_jobs', 'feature_block_size'] },
]
const comparisonSection = ref(parameterSections[0]!.title)
const comparisonFields = computed(
  () =>
    parameterSections.find((section) => section.title === comparisonSection.value)?.fields ?? [],
)
const parameterIds = computed(() => Object.keys(parameterDrafts.value))
const parameterKeys = computed(() => parameterSections.flatMap((section) => section.fields))
const copyField = ref('')
const applyingParameters = ref(false)
function editSampleParameters(id: string) {
  parameterSample.value = id
  compareParameters.value = false
}
function displayParameter(value: unknown): string {
  if (value == null) return '—'
  if (Array.isArray(value)) return value.length ? value.map(displayParameter).join(' / ') : '空'
  if (typeof value === 'number') {
    return value.toLocaleString('en-US', { useGrouping: false, maximumSignificantDigits: 21 })
  }
  if (value === 'union') return '任一'
  if (value === 'intersection') return '全部'
  return String(value)
}
const preflightStale = ref(false)
const parameterRows = computed(() =>
  Object.entries(parameterDrafts.value).slice(
    comparisonPage.value * 25,
    (comparisonPage.value + 1) * 25,
  ),
)
const sampleNames = computed(() =>
  Object.fromEntries((store.project?.manifest.samples ?? []).map((row) => [row.id, row.name])),
)
watch(
  checked,
  (value) => {
    comparisonPage.value = 0
    preflightStale.value = false
    parameterDrafts.value = Object.fromEntries(
      ((value?.samples ?? []) as Record<string, unknown>[]).map((row) => [
        String(row.id ?? row.sample_id ?? ''),
        JSON.parse(JSON.stringify(row.parameters ?? {})) as Record<string, unknown>,
      ]),
    )
    appliedParameters.value = {}
    markApplied(parameterDrafts.value)
    if (!parameterIds.value.includes(parameterSample.value))
      parameterSample.value = parameterIds.value[0] ?? ''
  },
  { flush: 'sync' },
)
function showSignal(id: string) {
  signalSample.value = signalSample.value === id ? '' : id
  if (signalSample.value) void loadSignal()
}
async function saveParameters(id?: string) {
  const edits = id ? { [id]: parameterDrafts.value[id] } : parameterDrafts.value
  applyingParameters.value = true
  try {
    if (
      await store.mutate('/parameters/rows', { edits }, 'PUT', '逐样本参数已应用，请重新预检。')
    ) {
      markApplied(edits)
      preflightStale.value = true
    }
  } finally {
    applyingParameters.value = false
  }
}
function copyParameters(id: string, field?: string) {
  for (const key of Object.keys(parameterDrafts.value)) {
    if (field)
      parameterDrafts.value[key]![field] = JSON.parse(
        JSON.stringify(parameterDrafts.value[id]![field]),
      )
    else parameterDrafts.value[key] = JSON.parse(JSON.stringify(parameterDrafts.value[id]!))
  }
}
useViewState('extraction', {
  path,
  included,
  checked,
  parameterDrafts,
  appliedParameters,
  parameterSample,
  comparisonSection,
  comparisonPage,
  copyField,
  compareParameters,
  preflightStale,
  signalSample,
  selections,
})
</script>
<template>
  <section v-if="store.project" class="extraction-workspace" :class="{ 'has-batch': selected }">
    <div class="page-title">
      <div>
        <h1>提取</h1>
        <p>检查完整参数，启动后台批次；结束后人工选择纳入样本。</p>
      </div>
    </div>
    <div class="card batch-task-panel">
      <div class="section-heading">
        <h2>项目任务</h2>
      </div>
      <div class="batch-toolbar">
        <label class="field"
          ><FieldLabel name="处理批次" /><select
            aria-label="处理批次"
            v-model="path"
            :disabled="store.busy"
          >
            <option value="" disabled>暂无批次</option>
            <option v-for="b in batchList" :key="b.path" :value="b.path">
              {{ formatTime(b.created_at) }} · {{ label(b.status) }} ·
              {{ b.path.split('/').at(-2) }}
            </option>
          </select></label
        >
        <button @click="polling.refresh()" :disabled="store.busy" class="preview">刷新批次</button>
        <MatrixDownload
          v-if="selected"
          :key="`${path}:${selected.status}`"
          source="extracted"
          compact
          :batch-path="path"
          embedded
        />
        <template v-if="selected">
          <TrashAction
            :path="selected.path.slice(0, -'/state.json'.length)"
            scope="batches"
            :disabled="active"
            @changed="polling.refresh()"
          />
          <div class="actions">
            <button
              class="restore"
              :disabled="store.busy || !['queued', 'running'].includes(selected.status)"
              @click="store.mutate('/extraction/stop', { path })"
            >
              完成当前样本后停止</button
            ><button
              class="save"
              :disabled="store.busy"
              @click="store.download('batch_log', 'worker.log', path)"
            >
              下载完整任务日志
            </button>
          </div>
        </template>
      </div>
      <template v-if="selected"
        ><p role="status">{{ label(selected.status) }} · {{ selected.message }}</p>
        <section class="batch-review" aria-label="样本审核">
          <h3>审核纳入样本</h3>
          <p class="muted">先核对信号和 QC。点击「建立当前数据集」纳入已选样本。</p>
          <div class="actions batch-review-selection">
            <p>已选择 {{ included.length }} / {{ counts.success }} 个成功样本</p>
            <button class="preview" :disabled="store.busy || active" @click="selectAllSuccesses">
              全选成功样本
            </button>
            <button :disabled="store.busy || active || !included.length" @click="clearSelection">
              清空选择
            </button>
          </div>
          <div class="table-scroll batch-sample-table" :class="{ 'signal-expanded': signalSample }">
            <table>
              <thead>
                <tr>
                  <th scope="col" class="batch-include">纳入</th>
                  <th scope="col">样本</th>
                  <th scope="col">状态</th>
                  <th scope="col" class="batch-count">细胞</th>
                  <th scope="col" class="batch-count">特征</th>
                  <th scope="col">错误</th>
                  <th scope="col">信号</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="s in selected.samples" :key="s.id"
                  ><tr>
                    <td class="batch-include">
                      <input
                        v-if="s.status === 'succeeded'"
                        v-model="included"
                        :aria-label="`${s.name} · ${s.cells} 细胞`"
                        type="checkbox"
                        :value="s.id"
                        :disabled="store.busy || ['queued', 'running'].includes(selected.status)"
                        @change="rememberSelection"
                      />
                      <span v-else aria-hidden="true">—</span>
                    </td>
                    <td>{{ s.name }}</td>
                    <td>
                      <span class="batch-row-state" :data-status="s.status">{{
                        label(s.status)
                      }}</span>
                    </td>
                    <td class="batch-count">{{ s.cells ?? '—' }}</td>
                    <td class="batch-count">{{ s.features ?? '—' }}</td>
                    <td>{{ s.error || '—' }}</td>
                    <td>
                      <button
                        class="preview"
                        :disabled="store.busy || s.status !== 'succeeded'"
                        :aria-expanded="signalSample === s.id"
                        @click="showSignal(s.id)"
                      >
                        {{ signalSample === s.id ? '收起信号' : '查看信号' }}
                      </button>
                    </td>
                  </tr>
                  <tr v-if="signalSample === s.id && signalFigure">
                    <td colspan="7">
                      <div class="actions">
                        <RouterLink :to="{ path: '/raw', query: { sample: s.id, panel: 'signal' } }"
                          >在预览中查看 TIC、EIC 与单扫描 →</RouterLink
                        >
                      </div>
                      <PlotView :figure="signalFigure" name="extraction-signal" />
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <p v-if="reviewPhase" role="status">{{ reviewPhase }}</p>
          <div class="actions batch-review-actions">
            <button
              class="preview"
              :disabled="
                store.busy || !included.length || ['queued', 'running'].includes(selected.status)
              "
              @click="review(true)"
            >
              比较所选成功样本的 QC</button
            ><button
              class="primary"
              :disabled="
                store.busy || !included.length || ['queued', 'running'].includes(selected.status)
              "
              @click="review()"
            >
              建立当前数据集
            </button>
          </div>
          <BatchSpectrum
            v-if="!['queued', 'running'].includes(selected.status)"
            :key="selected.path"
            :batch="selected"
          />
          <PlotView
            v-for="(figure, i) in figures"
            :key="i"
            :figure="figure"
            :name="`batch-qc-${i}`"
          />
        </section>
      </template>

      <p v-else class="muted">尚无处理批次。可先前往原始谱页面检查信号与参数。</p>
    </div>
    <BatchComparison :batches="batchList" :selected="path" />
    <details class="card extraction-preparation" :open="!selected">
      <summary>处理准备 · 新建或重试批次</summary>
      <p>{{ store.project.manifest.samples.length }} 个样本</p>
      <FeatureSource v-model:pending="featureSourcePending" :active="active" />
      <div class="actions">
        <button
          class="preview"
          :disabled="store.busy || featureSourcePending || !store.project.manifest.samples.length"
          @click="preflight"
        >
          检查参数与输入</button
        ><button
          class="primary"
          :disabled="
            store.busy ||
            active ||
            featureSourcePending ||
            !!pendingCount ||
            !store.project.manifest.samples.some((sample) => sample.path)
          "
          @click="start()"
        >
          开始提取</button
        ><button
          class="primary"
          :disabled="store.busy || active || featureSourcePending || !!pendingCount || !path"
          @click="start(true)"
        >
          重试失败批次
        </button>
        <template v-if="pendingCount">
          <span role="status">{{ pendingCount }} 个样本的参数待应用</span>
          <button
            class="primary"
            :disabled="store.busy || active || featureSourcePending"
            @click="applyAndStart"
          >
            应用并开始提取
          </button>
        </template>
      </div>
      <p class="page-note">
        开始或重试先预检并完整保存项目：已有当前矩阵时也会生成新快照，再将逐样本结果写入 processing
        批次目录。停止仅阻止后续样本；审核建立的数据仍需主动保存。
      </p>
      <template v-if="checked"
        ><h3>逐样本完整参数</h3>
        <div class="actions parameter-display">
          <button :aria-pressed="!compareParameters" @click="compareParameters = false">
            逐样本编辑
          </button>
          <button :aria-pressed="compareParameters" @click="compareParameters = true">
            按组对照
          </button>
          <span>{{ parameterIds.length }} 个样本</span>
        </div>
        <div v-if="!compareParameters && parameterSample" class="sample-parameter-editor">
          <aside class="sample-parameter-list" aria-label="参数样本">
            <button
              v-for="id in parameterIds"
              :key="id"
              :aria-pressed="id === parameterSample"
              @click="parameterSample = id"
            >
              {{ sampleNames[id] || id }}
              <small>{{
                store.project.manifest.samples.find((row) => row.id === id)?.parameters
                  ? '样本例外'
                  : '项目默认'
              }}</small>
            </button>
          </aside>
          <div class="sample-parameter-fields" data-scmm-view-state>
            <ProcessingFields
              :key="parameterSample"
              v-model="parameterDrafts[parameterSample]!"
              :fields="parameterKeys"
              :sections="parameterSections"
              :aria-prefix="parameterSample"
              :disabled="active || store.busy"
            />
            <div class="actions parameter-editor-actions">
              <button
                class="primary"
                :disabled="active || store.busy"
                @click="saveParameters(parameterSample)"
              >
                应用当前样本参数
              </button>
              <button
                class="secondary"
                :disabled="active || store.busy || parameterIds.length < 2"
                @click="copyParameters(parameterSample)"
              >
                复制整套到全部草稿
              </button>
              <label
                >复制单项<select v-model="copyField" aria-label="要复制的参数">
                  <option value="">选择参数</option>
                  <optgroup
                    v-for="section in parameterSections"
                    :key="section.title"
                    :label="section.title"
                  >
                    <option v-for="field in section.fields" :key="field" :value="field">
                      {{ displayName(field) }}
                    </option>
                  </optgroup>
                </select></label
              >
              <button
                :disabled="active || store.busy || !copyField || parameterIds.length < 2"
                @click="copyParameters(parameterSample, copyField)"
              >
                复制该项到全部草稿
              </button>
              <button class="save" :disabled="active || store.busy" @click="saveParameters()">
                应用全部样本参数
              </button>
            </div>
          </div>
        </div>
        <template v-else-if="compareParameters">
          <label data-scmm-view-state
            >对照参数组<select v-model="comparisonSection" @change="comparisonPage = 0">
              <option v-for="section in parameterSections" :key="section.title">
                {{ section.title }}
              </option>
            </select></label
          >
          <div class="table-scroll parameter-comparison">
            <table>
              <thead>
                <tr>
                  <th>样本</th>
                  <th v-for="key in comparisonFields" :key="key"><FieldLabel :name="key" /></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="[id, values] in parameterRows" :key="id">
                  <td>
                    <button class="text-button" @click="editSampleParameters(id)">
                      {{ sampleNames[id] || id }}
                    </button>
                  </td>
                  <td v-for="key in comparisonFields" :key="key">
                    {{ displayParameter(values[key]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="parameterIds.length > 25" class="actions">
            <button :disabled="!comparisonPage" @click="comparisonPage--">上一页参数</button>
            <span>{{ comparisonPage + 1 }} / {{ Math.ceil(parameterIds.length / 25) }}</span>
            <button
              :disabled="(comparisonPage + 1) * 25 >= parameterIds.length"
              @click="comparisonPage++"
            >
              下一页参数
            </button>
          </div>
        </template>
        <p v-if="preflightStale" class="state-note">参数已变更，请重新检查参数与输入。</p>
        <button class="save" :disabled="preflightStale" @click="downloadPreflight">
          下载预检 JSON
        </button>
        <PreflightSamples :samples="checkedSamples"
      /></template>
    </details>
  </section>
  <div v-else class="card empty-state">
    <h1>请先打开项目</h1>
    <RouterLink to="/projects">前往项目首页 →</RouterLink>
  </div>
</template>
<style scoped>
.batch-task-panel > .section-heading {
  margin-bottom: 8px;
}
.batch-task-panel > .section-heading h2,
.batch-review > h3 {
  margin: 0;
}
.batch-task-panel > p {
  margin: 8px 0;
}
.batch-review {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.batch-review > .muted {
  margin: 4px 0 8px;
}
.batch-review-selection,
.batch-review-actions {
  margin: 10px 0;
}
.batch-review-selection p {
  margin: 0 4px 0 0;
  font-variant-numeric: tabular-nums;
}
.batch-review-actions {
  justify-content: flex-end;
  margin-bottom: 0;
}
.batch-sample-table {
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
}
.batch-sample-table:not(.signal-expanded) {
  max-height: 410px;
  overflow: auto;
}
.batch-sample-table th {
  position: sticky;
  top: 0;
  z-index: 1;
}
.batch-include {
  width: 50px;
  text-align: center;
}
.batch-include input {
  display: block;
  margin: 0 auto;
}
.batch-count {
  text-align: right;
  min-width: 70px;
}
.batch-row-state[data-status='succeeded'] {
  color: #17684a;
  font-weight: 650;
}
.batch-row-state[data-status='failed'],
.batch-row-state[data-status='interrupted'] {
  color: #a62d3e;
  font-weight: 650;
}
.extraction-preparation > summary {
  color: #284b55;
  font-size: 16px;
  font-weight: 600;
}
.sample-parameter-editor {
  display: grid;
  grid-template-columns: minmax(140px, 200px) minmax(0, 1fr);
  align-items: start;
  gap: 10px;
}
.sample-parameter-list {
  max-height: 410px;
  overflow: auto;
  display: grid;
  gap: 4px;
}
.sample-parameter-list button {
  justify-content: flex-start;
  text-align: left;
  overflow-wrap: anywhere;
}
.sample-parameter-list small {
  display: block;
}
.parameter-display button[aria-pressed='true'],
.sample-parameter-list button[aria-pressed='true'] {
  background: #e4f2f4;
  border-color: var(--teal);
}
.sample-parameter-fields {
  min-width: 0;
}
.sample-parameter-fields :deep(.parameter-sections) {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: start;
  gap: 6px;
}
.sample-parameter-fields :deep(.parameter-section) {
  margin: 0;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
  background: var(--panel-soft);
}
.parameter-editor-actions {
  flex-wrap: wrap;
  align-items: end;
}
.parameter-comparison {
  max-height: 430px;
  overflow: auto;
}
.parameter-comparison th {
  position: sticky;
  top: 0;
  z-index: 1;
  white-space: normal;
}
</style>
