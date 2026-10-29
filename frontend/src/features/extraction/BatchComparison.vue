<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { useReadScope } from '../../api/readScope'
import { useViewState } from '../../api/viewState'
import { saveBlob } from '../../components/plotExport'
import { displayName } from '../../help/labels'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
import type { Batch, Figure } from '../../api/types'
const props = defineProps<{ batches: Batch[]; selected: string }>()
const store = useWorkspace()
const a = ref(''),
  b = ref(''),
  sample = ref('')
const differencesOnly = ref(true),
  linked = ref(true)
const linkedViewport = ref<Record<string, unknown>>({})
const signalA = ref<Figure>(),
  signalB = ref<Figure>()
type Comparison = {
  batch_A: string
  batch_B: string
  parameters: { scope: string; parameter: string; A: unknown; B: unknown; changed: boolean }[]
  samples: {
    sample_id: string
    name_A: string
    name_B: string
    input: string
    status_A: string
    status_B: string
    cells_A: number
    cells_B: number
    features_A: number
    features_B: number
    cell_difference: number | null
  }[]
  figures: Figure[]
  warnings: string[]
  export_tables: Record<string, string>
}
const result = ref<Comparison>()
const reads = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  a.value,
  b.value,
])
const signals = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  a.value,
  b.value,
  sample.value,
])
const ended = computed(() =>
  props.batches.filter((batch) => !['queued', 'running'].includes(batch.status)),
)
watch(
  () => ended.value.map((batch) => batch.path).join('|'),
  () => {
    if (!ended.value.some((batch) => batch.path === a.value))
      a.value =
        ended.value.find((batch) => batch.path === props.selected)?.path ??
        ended.value[0]?.path ??
        ''
    if (!ended.value.some((batch) => batch.path === b.value) || b.value === a.value)
      b.value = ended.value.find((batch) => batch.path !== a.value)?.path ?? ''
  },
  { immediate: true },
)
watch([a, b], () => {
  result.value = undefined
  sample.value = ''
  signalA.value = undefined
  signalB.value = undefined
  linkedViewport.value = {}
})
watch(sample, () => {
  signalA.value = undefined
  signalB.value = undefined
  linkedViewport.value = {}
})
const inputs: Record<string, string> = {
  same: '相同输入身份',
  changed: '输入身份不同',
  unknown: '输入身份无法核实',
  only_A: '仅 A 有此样本',
  only_B: '仅 B 有此样本',
}
const parameterTable = computed(() => {
  const rows = (result.value?.parameters ?? [])
    .filter((row) => !differencesOnly.value || row.changed)
    .map((row) => ({
      ...row,
      scope:
        row.scope === 'project'
          ? '项目默认'
          : (result.value?.samples.find((sample) => sample.sample_id === row.scope)?.name_A ??
            result.value?.samples.find((sample) => sample.sample_id === row.scope)?.name_B ??
            row.scope),
      parameter: displayName(row.parameter),
      changed: row.changed ? '不同' : '相同',
      A: JSON.stringify(row.A) ?? '—',
      B: JSON.stringify(row.B) ?? '—',
    }))
  return { columns: ['scope', 'parameter', 'A', 'B', 'changed'], rows, total: rows.length }
})
const sampleTable = computed(() => ({
  columns: [
    'name_A',
    'name_B',
    'input',
    'status_A',
    'status_B',
    'cells_A',
    'cells_B',
    'cell_difference',
    'features_A',
    'features_B',
  ],
  rows: (result.value?.samples ?? []).map((row) => ({
    ...row,
    input: inputs[row.input] ?? row.input,
    status_A: status(row.status_A),
    status_B: status(row.status_B),
  })),
  total: result.value?.samples.length ?? 0,
}))
function status(value: string) {
  return (
    (
      {
        succeeded: '成功',
        failed: '失败',
        missing: '无记录',
        skipped: '跳过',
        waiting: '未处理',
      } as Record<string, string>
    )[value] ?? value
  )
}
const detailsTable = computed(() => ({
  columns: ['sample_id', 'path_A', 'path_B', 'error_A', 'error_B'],
  rows: result.value?.samples ?? [],
  total: result.value?.samples.length ?? 0,
}))
const common = computed(
  () =>
    result.value?.samples.filter(
      (row) => row.status_A === 'succeeded' && row.status_B === 'succeeded',
    ) ?? [],
)
async function compare() {
  const accept = reads.begin()
  const value = await store.inspect<Comparison>(
    '/extraction/compare',
    { path_a: a.value, path_b: b.value },
    accept,
  )
  if (value && accept()) {
    result.value = value
    signalA.value = undefined
    signalB.value = undefined
    sample.value = common.value[0]?.sample_id ?? ''
  }
}
async function signal() {
  const accept = signals.begin()
  const values: Figure[] = []
  for (const path of [a.value, b.value]) {
    const response = await store.inspect<{ value: { figure: Figure } }>(
      '/extraction/signal',
      { path, sample_id: sample.value },
      accept,
    )
    if (!response || !accept()) return
    values.push(response.value.figure)
  }
  if (accept()) {
    signalA.value = values[0]
    signalB.value = values[1]
  }
}
function sync(viewport: Record<string, unknown>) {
  if (linked.value)
    linkedViewport.value = Object.fromEntries(
      Object.entries(viewport).filter(([key]) => /^xaxis\d*\./.test(key)),
    )
}
function download(name: string) {
  const table = result.value?.export_tables[name]
  if (table !== undefined)
    saveBlob(new Blob([table], { type: 'text/csv;charset=utf-8' }), `batch-comparison-${name}.csv`)
}
useViewState('batch-comparison', { a, b, differencesOnly, linked })
</script>
<template>
  <details class="card batch-comparison">
    <summary>比较两个处理批次</summary>
    <p>
      读取已有结果，按稳定样本 ID
      对照；比较不重新提取、不建立或替换当前数据。特征轴可能不同，数量增加不代表质量提高。
    </p>
    <div class="field-grid">
      <label
        >批次 A<select v-model="a" aria-label="对比批次 A" :disabled="store.busy">
          <option value="">请选择</option>
          <option v-for="batch in ended" :key="batch.path" :value="batch.path">
            {{ batch.path.split('/').at(-2) }}
          </option>
        </select></label
      >
      <label
        >批次 B<select v-model="b" aria-label="对比批次 B" :disabled="store.busy">
          <option value="">请选择</option>
          <option
            v-for="batch in ended"
            :key="batch.path"
            :value="batch.path"
            :disabled="batch.path === a"
          >
            {{ batch.path.split('/').at(-2) }}
          </option>
        </select></label
      >
    </div>
    <button class="preview" :disabled="store.busy || !a || !b || a === b" @click="compare">
      比较两个批次
    </button>
    <p v-if="ended.length < 2" class="muted">需要两个已结束的批次。</p>
    <template v-if="result">
      <p v-for="warning in result.warnings" :key="warning" class="state-note">{{ warning }}</p>
      <h3>输入与处理结果</h3>
      <DataTableView :table="sampleTable" />
      <details>
        <summary>输入路径与失败详情</summary>
        <DataTableView :table="detailsTable" />
      </details>
      <p class="muted">
        细胞差值为 B − A，仅在输入身份一致且两侧有计数时提供。缺少旧版身份记录时不推断为同一输入。
      </p>
      <h3>参数对照</h3>
      <label class="inline-check"
        ><input type="checkbox" v-model="differencesOnly" />只看差异参数</label
      >
      <DataTableView :table="parameterTable" />
      <h3>逐样本 QC</h3>
      <PlotView
        v-for="(figure, i) in result.figures"
        :key="i"
        :figure="figure"
        :name="`batch-comparison-qc-${i}`"
      />
      <h3>同一样本信号</h3>
      <div class="actions">
        <label
          >信号对照样本<select
            v-model="sample"
            aria-label="批次对比信号样本"
            :disabled="store.busy"
          >
            <option value="">请选择</option>
            <option v-for="row in common" :key="row.sample_id" :value="row.sample_id">
              {{ row.name_A }} · {{ inputs[row.input] }}
            </option>
          </select></label
        >
        <button class="preview" :disabled="store.busy || !sample" @click="signal">
          并排查看两批信号
        </button>
        <label class="inline-check"><input type="checkbox" v-model="linked" />联动时间轴</label>
      </div>
      <p class="muted">缺少完整检测记录时无法重建旧信号，会显示原因；不自动重新提取。</p>
      <div v-if="signalA && signalB" class="comparison-signals">
        <section>
          <h4>批次 A</h4>
          <PlotView
            :figure="signalA"
            name="batch-comparison-signal-A"
            :linked-viewport="linked ? linkedViewport : undefined"
            @viewport="sync"
          />
        </section>
        <section>
          <h4>批次 B</h4>
          <PlotView
            :figure="signalB"
            name="batch-comparison-signal-B"
            :linked-viewport="linked ? linkedViewport : undefined"
            @viewport="sync"
          />
        </section>
      </div>
      <div class="actions">
        <button
          v-for="(label, key) in { parameters: '参数', samples: '样本结果', cells: '完整细胞 QC' }"
          :key="key"
          class="save"
          @click="download(key)"
        >
          下载{{ label }}对比 CSV
        </button>
      </div>
    </template>
  </details>
</template>
