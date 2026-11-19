<script setup lang="ts">
import ScientificInput from '../../components/ScientificInput.vue'
import MatrixDownload from '../../components/MatrixDownload.vue'
import { formatTime } from '../../help/time'
import { useViewState } from '../../api/viewState'
import { serialPolling } from '../../api/polling'
import { useReadScope } from '../../api/readScope'
import { ref, computed, watch, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import type { Batch, Figure, DataTable } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'
import PlotView from '../../components/PlotView.vue'
import TrashAction from '../../components/TrashAction.vue'
import BatchComparison from './BatchComparison.vue'
const store = useWorkspace()
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
  signalFigure = ref<Figure>()
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
  figures = ref<Figure[]>([])
const signalScope = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  path.value,
  signalSample.value,
])
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
    checked.value = undefined
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
const parameterPage = ref(0)
const preflightStale = ref(false)
const parameterRows = computed(() =>
  Object.entries(parameterDrafts.value).slice(
    parameterPage.value * 25,
    (parameterPage.value + 1) * 25,
  ),
)
const sampleNames = computed(() =>
  Object.fromEntries((store.project?.manifest.samples ?? []).map((row) => [row.id, row.name])),
)
watch(
  checked,
  (value) => {
    parameterPage.value = 0
    preflightStale.value = false
    parameterDrafts.value = Object.fromEntries(
      ((value?.samples ?? []) as Record<string, unknown>[]).map((row) => [
        String(row.id ?? row.sample_id ?? ''),
        JSON.parse(JSON.stringify(row.parameters ?? {})) as Record<string, unknown>,
      ]),
    )
  },
  { flush: 'sync' },
)
function editParameter(id: string, key: string, event: Event) {
  const text = (event.target as HTMLInputElement).value
  try {
    parameterDrafts.value[id]![key] = JSON.parse(text)
  } catch {
    parameterDrafts.value[id]![key] = text
  }
}
function editParameterRange(id: string, key: string, index: number, value: number | null) {
  const range = [...((parameterDrafts.value[id]![key] as number[] | null) ?? [0, 0])]
  range[index] = value ?? 0
  parameterDrafts.value[id]![key] = value === null ? null : range
}
function showSignal(id: string) {
  signalSample.value = id
  void loadSignal()
}
async function saveParameters(id?: string) {
  const edits = id ? { [id]: parameterDrafts.value[id] } : parameterDrafts.value
  const applied = await store.mutate(
    '/parameters/rows',
    { edits },
    'PUT',
    '逐样本参数已应用，请重新预检。',
  )
  if (applied) preflightStale.value = true
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
const parameterTable = computed<DataTable>(() => {
  const rows = (checked.value?.samples ?? []) as Record<string, unknown>[]
  return {
    columns: ['name', 'parameter_source', ...Object.keys((rows[0]?.parameters ?? {}) as object)],
    rows: rows.map((s) => ({
      name: s.name,
      parameter_source: s.parameter_source,
      ...(s.parameters as object),
    })),
    total: rows.length,
  }
})
useViewState('extraction', {
  path,
  included,
  checked,
  parameterDrafts,
  preflightStale,
  figures,
  signalSample,
  signalFigure,
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
        <button @click="polling.refresh()" :disabled="store.busy" class="preview">刷新批次</button
        ><label class="field"
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
        ><MatrixDownload
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
        <p class="task-note">批次 ID：{{ selected.path.split('/').at(-2) }}</p>

        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>样本</th>
                <th>状态</th>
                <th>细胞</th>
                <th>特征</th>
                <th>错误</th>
                <th>信号</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="s in selected.samples" :key="s.id"
                ><tr>
                  <td>{{ s.name }}</td>
                  <td>{{ label(s.status) }}</td>
                  <td>{{ s.cells ?? '—' }}</td>
                  <td>{{ s.features ?? '—' }}</td>
                  <td>{{ s.error || '—' }}</td>
                  <td>
                    <button
                      class="preview"
                      :disabled="store.busy || s.status !== 'succeeded'"
                      @click="showSignal(s.id)"
                    >
                      查看信号
                    </button>
                  </td>
                </tr>
                <tr v-if="signalSample === s.id && signalFigure">
                  <td colspan="6"><PlotView :figure="signalFigure" name="extraction-signal" /></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>

      <p v-else class="muted">尚无处理批次。可先前往原始谱页面检查信号与参数。</p>
    </div>
    <section v-if="selected" class="card batch-review" aria-label="样本审核">
      <h3>审核纳入样本</h3>
      <p class="page-note">
        先查看信号与
        QC，再选择样本建立当前数据集。成功样本默认选中，检查后点击建立当前数据集才会纳入。
      </p>

      <div class="actions">
        <p>已选择 {{ included.length }} / {{ counts.success }} 个成功样本</p>
        <button class="preview" :disabled="store.busy || active" @click="selectAllSuccesses">
          全选成功样本
        </button>
        <button :disabled="store.busy || active || !included.length" @click="clearSelection">
          清空选择
        </button>
      </div>
      <p v-if="reviewPhase" role="status">{{ reviewPhase }}</p>
      <div class="check-list">
        <label v-for="s in selected.samples.filter((s) => s.status === 'succeeded')" :key="s.id"
          ><input
            v-model="included"
            @change="rememberSelection"
            :aria-label="`${s.name} · ${s.cells} 细胞`"
            type="checkbox"
            :value="s.id"
            :disabled="store.busy || ['queued', 'running'].includes(selected.status)" />{{
            s.name
          }}
          · {{ s.cells }} 细胞
          <HelpTip
            label="审核纳入"
            text="只选择经人工审核可纳入的成功样本。比较 QC 不建立当前数据；点击建立当前数据集后才合并所选样本。"
        /></label>
      </div>
      <div class="actions">
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
      <PlotView v-for="(figure, i) in figures" :key="i" :figure="figure" :name="`batch-qc-${i}`" />
    </section>
    <BatchComparison :batches="batchList" :selected="path" />
    <details class="card extraction-preparation" :open="!selected">
      <summary>处理准备 · 新建或重试批次</summary>
      <p>
        {{ store.project.manifest.samples.length }} 个样本 ·
        {{
          store.project.manifest.feature_strategy === 'shared' ? '全项目共同特征' : '独立特征合并'
        }}
      </p>
      <div class="actions">
        <button
          class="preview"
          :disabled="store.busy || !store.project.manifest.samples.length"
          @click="preflight"
        >
          检查参数与输入</button
        ><button
          class="primary"
          :disabled="store.busy || active || !store.project.manifest.samples.length"
          @click="start()"
        >
          开始提取</button
        ><button class="primary" :disabled="store.busy || active || !path" @click="start(true)">
          重试失败批次
        </button>
      </div>
      <p class="page-note">
        开始或重试先预检并完整保存项目：已有当前矩阵时也会生成新快照，再将逐样本结果写入 processing
        批次目录。停止仅阻止后续样本；审核建立的数据仍需主动保存。
      </p>
      <template v-if="checked"
        ><h3>逐样本完整参数</h3>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>样本</th>
                <th v-for="key in parameterTable.columns.slice(2)" :key="key">
                  <FieldLabel :name="key" />
                </th>
                <th>应用</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="[id, values] in parameterRows" :key="id">
                <td>{{ sampleNames[id] || id }}</td>
                <td v-for="key in parameterTable.columns.slice(2)" :key="key">
                  <span v-if="key === 'rt_range' || key === 'frame_range'" class="parameter-pair"
                    ><ScientificInput
                      v-for="i in [0, 1]"
                      :key="i"
                      :model-value="(values[key] as number[] | null)?.[i]"
                      :decimals="key === 'rt_range' ? 1 : 0"
                      :disabled="active || store.busy"
                      :aria-label="`${id} ${key} ${i}`"
                      @update:model-value="(value) => editParameterRange(id, key, i, value)"
                  /></span>
                  <ScientificInput
                    v-else-if="typeof values[key] === 'number'"
                    v-model="values[key]"
                    :scientific="/snr|signal/.test(key)"
                    :decimals="/^(ref_mz|mz_min|mz_max)$/.test(key) ? 4 : undefined"
                    :aria-label="`${id} ${key}`"
                    :disabled="active || store.busy"
                  /><select
                    v-else-if="typeof values[key] === 'boolean'"
                    :value="String(values[key])"
                    :disabled="active || store.busy"
                    @change="editParameter(String(id), key, $event)"
                  >
                    <option value="true">是</option>
                    <option value="false">否</option></select
                  ><input
                    v-else
                    :aria-label="`${id} ${key}`"
                    :value="
                      typeof values[key] === 'string' ? values[key] : JSON.stringify(values[key])
                    "
                    :disabled="active || store.busy"
                    @change="editParameter(String(id), key, $event)"
                  />
                </td>
                <td>
                  <button :disabled="active || store.busy" @click="saveParameters(String(id))">
                    应用本行</button
                  ><button :disabled="active || store.busy" @click="copyParameters(String(id))">
                    复制到全部样本
                  </button>
                  <details>
                    <summary>按字段复制</summary>
                    <button
                      v-for="field in parameterTable.columns.slice(2)"
                      :key="field"
                      :disabled="active || store.busy"
                      @click="copyParameters(id, field)"
                    >
                      {{ field }}
                    </button>
                  </details>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="actions">
          <button :disabled="parameterPage === 0" @click="parameterPage--">上一页参数</button
          ><span
            >{{ parameterPage + 1 }} /
            {{ Math.max(1, Math.ceil(Object.keys(parameterDrafts).length / 25)) }} ·
            {{ Object.keys(parameterDrafts).length }} 个样本</span
          ><button
            :disabled="(parameterPage + 1) * 25 >= Object.keys(parameterDrafts).length"
            @click="parameterPage++"
          >
            下一页参数
          </button>
        </div>
        <button class="primary" :disabled="active || store.busy" @click="saveParameters()">
          应用全部样本参数
        </button>
        <p v-if="preflightStale" class="state-note">参数已变更，请重新检查参数与输入。</p>
        <button class="save" :disabled="preflightStale" @click="downloadPreflight">
          下载预检 JSON
        </button>
        <details>
          <summary>预检 JSON</summary>
          <pre class="code-block">{{ JSON.stringify(checked, null, 2) }}</pre>
        </details></template
      >
    </details>
  </section>
  <div v-else class="card empty-state">
    <h1>请先打开项目</h1>
    <RouterLink to="/projects">前往项目首页 →</RouterLink>
  </div>
</template>
<style scoped>
.batch-task-panel > .section-heading,
.batch-review > h3 {
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.batch-task-panel h2,
.batch-review > h3 {
  color: #284b55;
  font-size: 17px;
}
.batch-task-panel > .field {
  max-width: 620px;
}
.batch-task-panel :deep(.matrix-download) {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px 12px;
  margin: 12px 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--panel-soft);
}
.batch-task-panel :deep(.matrix-download > p) {
  margin: 0;
  font-size: 12px;
}
.batch-task-panel :deep(.matrix-download > details) {
  grid-column: 1 / -1;
}
.batch-progress {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--panel-soft);
}
.batch-progress .metric-strip {
  margin-bottom: 10px;
}
.batch-progress .metric-strip > div {
  padding: 0 12px;
  background: transparent;
}
.batch-progress .metric-strip strong {
  font-size: 20px;
}
.batch-progress .metric-strip span {
  font-size: 12px;
}
.batch-progress > p {
  margin: 8px 0 0;
}
.batch-review {
  margin-top: 16px;
}
.batch-review > .page-note {
  margin-bottom: 12px;
  font-size: 12px;
}
.review-signal {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--panel-soft);
}
.review-signal > h3 {
  margin-bottom: 10px;
  font-size: 14px;
}
.extraction-preparation > summary {
  color: #284b55;
  font-size: 16px;
  font-weight: 600;
}
@media (max-width: 600px) {
  .batch-task-panel :deep(.matrix-download) {
    grid-template-columns: minmax(0, 1fr);
  }
  .batch-progress .metric-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
