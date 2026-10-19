<script setup lang="ts">
import { useViewState } from '../../api/viewState'
import { ref, computed, watch, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import type { Batch, Figure, DataTable } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
const store = useWorkspace()
const signalSample = ref(''),
  signalFigure = ref<Figure>()
async function loadSignal() {
  const result = await store.command<{ figure: Figure }>('/extraction/signal', {
    path: path.value,
    sample_id: signalSample.value,
  })
  if (result) signalFigure.value = result.figure
}

const batchList = ref<Batch[]>([]),
  path = ref(''),
  included = ref<string[]>([]),
  checked = ref<Record<string, unknown>>(),
  figures = ref<Figure[]>([])
let timer: ReturnType<typeof setTimeout> | undefined
const selected = computed(() => batchList.value.find((b) => b.path === path.value))
const active = computed(() => batchList.value.some((b) => ['queued', 'running'].includes(b.status)))
const table = computed<DataTable>(() => ({
  columns: ['name', 'status', 'cells', 'features', '来源', 'error'],
  rows: (selected.value?.samples ?? []).map((s) => ({
    ...s,
    status: label(s.status),
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
async function refresh() {
  if (!store.project) return
  const result = await store.read<Batch[]>('/extraction/batches')
  if (result) {
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
watch(
  () => store.project?.path,
  () => {
    path.value = ''
    included.value = []
    checked.value = undefined
    figures.value = []
    batchList.value = []
    void refresh()
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
onMounted(startPolling)
let pollingActive = false
async function tick() {
  try {
    await refresh()
  } finally {
    if (pollingActive) timer = setTimeout(tick, 2000)
  }
}
function startPolling() {
  if (pollingActive) return
  pollingActive = true
  timer = setTimeout(tick, 2000)
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
    await refresh()
    path.value = result.path
  }
}
async function review(compare = false) {
  const value = await store.command<{ figures: Figure[] } | null>('/extraction/review', {
    path: path.value,
    ids: included.value,
    compare,
  })
  if (compare && value) figures.value = value.figures
  else if (!compare && !store.error)
    store.notice = '当前数据集已建立，可进入预处理。项目仍需主动保存。'
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
  <section v-if="store.project">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 03 / 提取</p>
        <h1>提取与审核</h1>
        <p>检查完整参数，启动后台批次；结束后人工选择纳入样本。</p>
      </div>
      <span class="step-badge">03 / 06</span>
    </div>
    <div class="card" v-if="selected">
      <h2>细胞提取信号</h2>
      <select v-model="signalSample">
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
    <div class="card">
      <h2>处理准备</h2>
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
        开始或重试自动预检并保存输入配置。停止仅阻止后续样本，保留当前样本及已完成产物。
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
    </div>
    <div class="card">
      <div class="section-heading">
        <h2>项目任务</h2>
        <button @click="refresh" :disabled="store.busy" class="preview">刷新批次</button>
      </div>
      <label class="field"
        ><FieldLabel name="处理批次" /><select
          aria-label="处理批次"
          v-model="path"
          :disabled="store.busy"
        >
          <option value="" disabled>暂无批次</option>
          <option v-for="b in batchList" :key="b.path" :value="b.path">
            {{ new Date(b.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }} ·
            {{ label(b.status) }} · {{ b.path.split('/').at(-2) }}
          </option>
        </select></label
      ><template v-if="selected"
        ><p role="status">{{ label(selected.status) }} · {{ selected.message }}</p>
        <p class="task-note">批次 ID：{{ selected.path.split('/').at(-2) }}</p>
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
        <h3>审核纳入样本</h3>
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
        <PlotView v-for="(figure, i) in figures" :key="i" :figure="figure" :name="`batch-qc-${i}`"
      /></template>
      <p v-else class="muted">尚无处理批次。可先前往原始谱页面检查信号与参数。</p>
    </div>
  </section>
  <div v-else class="card empty-state">
    <h1>请先打开项目</h1>
    <RouterLink to="/projects">前往项目首页 →</RouterLink>
  </div>
</template>
