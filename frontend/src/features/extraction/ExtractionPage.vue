<script setup lang="ts">
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
import DataTableView from '../../components/DataTable.vue'
const store = useWorkspace()
const now = ref(Date.now()),
  reviewPhase = ref('')
const stages: Record<string, string> = {
  preparing: '准备特征',
  shared: '共同特征合谱',
  reading: '读取原始谱 / 复用预览',
  aligning: '扫描峰对齐',
  extracting: '提取细胞特征',
  saving: '保存产物',
  sample_completed: '样本处理结束',
  completed: '完成',
  review: '等待人工审核',
}
const counts = computed(() => {
  const samples = selected.value?.samples ?? []
  return {
    total: samples.length || store.project?.manifest.samples.length || 0,
    success: samples.filter((s) => s.status === 'succeeded').length,
    failed: samples.filter((s) => s.status === 'failed').length,
    waiting: samples.filter((s) => s.status === 'waiting' || s.status === 'queued').length,
  }
})
const elapsed = computed(() => {
  const batch = selected.value
  if (!batch?.started_at) return '—'
  const end = batch.finished_at ? Date.parse(batch.finished_at) : now.value
  const seconds = Math.max(0, Math.floor((end - Date.parse(batch.started_at)) / 1000))
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
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
const selected = computed(() => batchList.value.find((b) => b.path === path.value))
const active = computed(() => batchList.value.some((b) => ['queued', 'running'].includes(b.status)))
const table = computed<DataTable>(() => ({
  columns: ['name', 'status', '阶段', '阶段进度', 'cells', 'features', '来源', 'error'],
  rows: (selected.value?.samples ?? []).map((s) => ({
    ...s,
    status: label(s.status),
    阶段: stages[s.stage ?? ''] ?? '—',
    阶段进度: s.progress == null ? '—' : `${Math.round(s.progress * 100)}%`,
    来源: s.reused_preview ? '复用预览' : '本批处理',
  })),
  total: selected.value?.samples.length ?? 0,
}))
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
  now.value = Date.now()
  if (!store.project) return
  const result = await store.refreshBatches()
  if (result && isCurrent()) {
    batchList.value = result
    const running = result.find((b) => ['queued', 'running'].includes(b.status))
    if (running) store.task = `提取：${running.message}`
    else if (store.task.startsWith('提取：')) store.task = '提取已结束，等待人工审核'
    if (!result.some((b) => b.path === path.value)) path.value = result[0]?.path ?? ''
    included.value = included.value.filter((id) =>
      selected.value?.samples.some((s) => s.id === id && s.status === 'succeeded'),
    )
  }
}
const polling = serialPolling(refresh, 2000, (cause) => {
  store.error = cause instanceof Error ? cause.message : String(cause)
})
watch(
  () => store.project?.path,
  () => {
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
  included.value = []
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
useViewState('extraction', { path, included, checked, figures, signalSample, signalFigure })
</script>
<template>
  <section v-if="store.project" class="extraction-workspace" :class="{ 'has-batch': selected }">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 03 / 提取</p>
        <h1>提取与审核</h1>
        <p>检查完整参数，启动后台批次；结束后人工选择纳入样本。</p>
      </div>
      <span class="step-badge">03 / 06</span>
    </div>
    <div class="card">
      <div class="section-heading">
        <h2>项目任务</h2>
        <button @click="polling.refresh()" :disabled="store.busy" class="preview">刷新批次</button>
      </div>
      <label class="field"
        ><FieldLabel name="处理批次" /><select
          aria-label="处理批次"
          v-model="path"
          :disabled="store.busy"
        >
          <option value="" disabled>暂无批次</option>
          <option v-for="b in batchList" :key="b.path" :value="b.path">
            {{ formatTime(b.created_at) }} · {{ label(b.status) }} · {{ b.path.split('/').at(-2) }}
          </option>
        </select></label
      ><template v-if="selected"
        ><p role="status">{{ label(selected.status) }} · {{ selected.message }}</p>
        <div class="batch-progress" aria-label="提取进度">
          <div class="metric-strip">
            <div>
              <strong>{{ counts.success + counts.failed }} / {{ counts.total }}</strong
              ><span>已处理样本</span>
            </div>
            <div>
              <strong>{{ counts.success }}</strong
              ><span>成功</span>
            </div>
            <div>
              <strong>{{ counts.failed }}</strong
              ><span>失败</span>
            </div>
            <div>
              <strong>{{ counts.waiting }}</strong
              ><span>等待</span>
            </div>
          </div>
          <label class="field"
            >样本处理进度<progress
              :value="counts.success + counts.failed"
              :max="Math.max(counts.total, 1)"
          /></label>
          <p>
            当前阶段：{{ stages[selected.stage ?? ''] ?? label(selected.status)
            }}<span v-if="selected.current_sample"> · {{ selected.current_sample }}</span>
          </p>
          <label v-if="selected.status === 'running'" class="field"
            >{{
              selected.stage_progress == null
                ? '当前阶段运行中（无可用百分比）'
                : `当前阶段 ${Math.round(selected.stage_progress * 100)}%`
            }}<progress :value="selected.stage_progress ?? undefined" max="1"
          /></label>
          <p class="task-note">
            已耗时 {{ elapsed }} · 最近更新
            {{
              selected.updated_at ? formatTime(selected.updated_at) : '暂无阶段信息'
            }}。阶段进度不代表剩余时间。
          </p>
        </div>
        <p class="task-note">批次 ID：{{ selected.path.split('/').at(-2) }}</p>
        <TrashAction
          :path="selected.path.slice(0, -'/state.json'.length)"
          scope="batches"
          :disabled="active"
          @changed="polling.refresh()" />
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
        <DataTableView :table="table" />
        <section class="batch-review" aria-label="样本审核">
          <h3>审核纳入样本</h3>
          <p class="page-note">先查看信号与 QC，再选择样本建立当前数据集。提取成功不等于已纳入。</p>
          <div class="review-signal" v-if="counts.success">
            <h3>细胞提取信号</h3>
            <select aria-label="审核信号样本" v-model="signalSample" :disabled="store.busy">
              <option value="">选择已完成样本</option>
              <option
                v-for="sample in selected.samples.filter((s) => s.status === 'succeeded')"
                :key="sample.id"
                :value="sample.id"
              >
                {{ sample.name }}
              </option></select
            ><button class="preview" :disabled="store.busy || !signalSample" @click="loadSignal">
              查看完整信号</button
            ><PlotView v-if="signalFigure" :figure="signalFigure" name="extraction-signal" />
          </div>

          <p>已选择 {{ included.length }} / {{ counts.success }} 个成功样本</p>
          <p v-if="reviewPhase" role="status">{{ reviewPhase }}</p>
          <div class="check-list">
            <label v-for="s in selected.samples.filter((s) => s.status === 'succeeded')" :key="s.id"
              ><input
                v-model="included"
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
          <PlotView
            v-for="(figure, i) in figures"
            :key="i"
            :figure="figure"
            :name="`batch-qc-${i}`"
          /></section
      ></template>
      <p v-else class="muted">尚无处理批次。可先前往原始谱页面检查信号与参数。</p>
    </div>
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
        <DataTableView :table="parameterTable" />
        <button class="save" @click="downloadPreflight">下载预检 JSON</button>
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
