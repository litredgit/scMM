<script setup lang="ts">
import { useViewState } from '../../api/viewState'
import { displayName } from '../../help/labels'
import { ref, computed, watch } from 'vue'
import { normalizationHelp } from '../../help/fields'
import { useWorkspace } from '../../stores/workspace'
import type { QC, AnalysisInfo, DataTable } from '../../api/types'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
import QCComparison from './QCComparison.vue'
const store = useWorkspace()
const qc = ref<QC>(),
  info = ref<AnalysisInfo>(),
  impact = ref<{ impact: { object: string; before: number; after: number }[]; qc: QC }>()
const operation = ref('filter'),
  method = ref('total'),
  imputation = ref('median'),
  minTotal = ref(0),
  minDetected = ref(0.2),
  fraction = ref(0),
  contamination = ref(0.05),
  layer = ref('')
const signature = computed(() =>
  JSON.stringify([
    operation.value,
    method.value,
    imputation.value,
    minTotal.value,
    minDetected.value,
    fraction.value,
    contamination.value,
    layer.value,
  ]),
)
watch(signature, () => (impact.value = undefined))
let generation = 0
async function refresh() {
  const token = ++generation
  qc.value = undefined
  info.value = undefined
  impact.value = undefined
  if (!store.project?.dataset) return
  const values = await Promise.all([
    store.read<QC>('/analysis/qc'),
    store.read<AnalysisInfo>('/analysis'),
  ])
  if (token !== generation) return
  qc.value = values[0]
  info.value = values[1]
  layer.value = info.value?.layers[0] ?? ''
}
watch(
  [
    () => store.project?.path,
    () => store.project?.dataset?.id,
    () => store.project?.dataset?.revision,
  ],
  () => void refresh(),
  { immediate: true },
)
function options() {
  return operation.value === 'filter'
    ? {
        min_total: minTotal.value,
        min_detected: minDetected.value,
        min_feature_fraction: fraction.value,
      }
    : operation.value === 'normalize'
      ? { method: method.value }
      : operation.value === 'impute'
        ? { method: imputation.value }
        : { contamination: contamination.value, random_state: 42 }
}
async function run(preview: boolean) {
  if (preview)
    impact.value = await store.command('/analysis/operation', {
      operation: operation.value,
      options: options(),
      preview: true,
    })
  else
    await store.mutate(
      '/analysis/operation',
      { operation: operation.value, options: options(), preview: false },
      'POST',
      '预处理已应用，下游分析结果已失效。',
    )
}
const history = computed<DataTable>(() => ({
  columns: ['operation', 'parameters', 'layer', 'revision', 'shape', 'at'],
  rows: info.value?.history ?? [],
  total: info.value?.history.length ?? 0,
}))
const countTables = computed(() => {
  const rows = (impact.value?.impact ?? []).map((row) => ({
    ...row,
    change: row.after - row.before,
  }))
  return {
    totals: {
      columns: ['指标', '操作前', '候选后', '变化'],
      rows: rows
        .slice(0, 2)
        .map((r) => ({ 指标: r.object, 操作前: r.before, 候选后: r.after, 变化: r.change })),
      total: 2,
    },
    samples: {
      columns: ['样本', '操作前细胞数', '候选后细胞数', '细胞数变化'],
      rows: rows.slice(2).map((r) => ({
        样本: r.object,
        操作前细胞数: r.before,
        候选后细胞数: r.after,
        细胞数变化: r.change,
      })),
      total: Math.max(0, rows.length - 2),
    },
  }
})
useViewState('preprocess', {
  operation,
  method,
  imputation,
  minTotal,
  minDetected,
  fraction,
  contamination,
  layer,
  impact,
})
</script>
<template>
  <section v-if="store.project?.dataset">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 04 / 预处理</p>
        <h1>预处理与 QC</h1>
        <p>
          {{ store.project.dataset.cells }} 细胞 × {{ store.project.dataset.features }} 特征 ·
          每步成功后保留历史层。
        </p>
      </div>
      <span class="step-badge">04 / 06</span>
    </div>
    <div class="card">
      <h2>处理当前矩阵</h2>
      <div class="field-grid">
        <label
          ><FieldLabel name="下一项操作" /><select
            aria-label="下一项操作"
            v-model="operation"
            :disabled="store.busy"
          >
            <option value="filter">筛选细胞与特征</option>
            <option value="normalize">归一化 / 数值变换</option>
            <option value="impute">零值插补</option>
            <option value="remove_outliers">异常值处理</option>
          </select></label
        ><template v-if="operation === 'filter'"
          ><label
            ><FieldLabel name="min_total" /><input
              aria-label="min_total"
              v-model.number="minTotal"
              type="number"
              min="0"
              step="any"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="min_detected" /><input
              aria-label="min_detected"
              v-model.number="minDetected"
              type="number"
              min="0"
              max="1"
              step="0.01"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="min_feature_fraction" /><input
              aria-label="min_feature_fraction"
              v-model.number="fraction"
              type="number"
              min="0"
              max="1"
              step="any"
              :disabled="store.busy" /></label></template
        ><label v-if="operation === 'normalize'"
          ><FieldLabel name="normalization" /><select
            aria-label="normalization"
            v-model="method"
            :disabled="store.busy"
          >
            <option
              :value="v"
              v-for="v in ['total', 'max', 'pqn', 'zscore', 'log', 'minmax', 'quantile']"
              :key="v"
            >
              {{ displayName(v) }}
            </option>
          </select></label
        ><label v-if="operation === 'impute'"
          ><FieldLabel name="imputation" /><select
            aria-label="imputation"
            v-model="imputation"
            :disabled="store.busy"
          >
            <option value="median">中位数</option>
            <option value="mean">均值</option>
            <option value="knn">近邻插补</option>
          </select></label
        ><label v-if="operation === 'remove_outliers'"
          ><FieldLabel name="contamination" /><input
            aria-label="contamination"
            v-model.number="contamination"
            type="number"
            min="0.001"
            max="0.5"
            step="0.01"
            :disabled="store.busy"
        /></label>
      </div>
      <div v-if="operation === 'normalize'" class="method-help">
        <p>
          <strong>{{ method }}</strong>
          <HelpTip :text="normalizationHelp[method]!" :label="method" />：{{
            normalizationHelp[method]
          }}
        </p>
        <details>
          <summary>查看全部 normalization 方法</summary>
          <dl class="method-list">
            <div v-for="(text, key) in normalizationHelp" :key="key">
              <dt>{{ key }} <HelpTip :text="text" :label="String(key)" /></dt>
              <dd>{{ text }}</dd>
            </div>
          </dl>
        </details>
      </div>
      <p class="muted">
        建议在标准化和插补前筛选。影响检查只计算候选状态，应用后清除下游嵌入、聚类和分析报告。
      </p>
      <div class="actions">
        <button class="preview" :disabled="store.busy" @click="run(true)">检查影响</button
        ><button class="primary" :disabled="store.busy" @click="run(false)">应用到当前数据</button>
      </div>
    </div>
    <div class="card preprocess-comparison">
      <h2>操作前后对比</h2>
      <template v-if="impact">
        <h3>候选数据（尚未应用）</h3>
        <p class="muted">操作前为当前矩阵，候选后为本次参数的检查结果；变化 = 候选后 − 操作前。</p>
        <h3>数据规模</h3>
        <DataTableView :table="countTables.totals" />
        <template v-if="countTables.samples.rows.length">
          <h3>各样本细胞数</h3>
          <DataTableView :table="countTables.samples" />
        </template>
        <h3>来源文件 QC 指标</h3>
        <QCComparison v-if="qc" :before="qc.files" :after="impact.qc.files" />
      </template>
      <template v-else>
        <p class="muted">
          设置上方参数并点击“检查影响”，在此对比操作前与候选后的数量、QC 指标和分布。
        </p>
        <DataTableView v-if="qc" :table="qc.files" qc />
      </template>
      <div class="qc-plots" :class="{ comparing: impact }">
        <div v-if="qc">
          <h3>操作前 · 当前数据</h3>
          <PlotView :figure="qc.figure" name="current-qc" />
          <p v-for="note in qc.notes" :key="note" class="page-note">{{ note }}</p>
        </div>
        <div v-if="impact">
          <h3>候选后 · 尚未应用</h3>
          <PlotView :figure="impact.qc.figure" name="candidate-qc" />
          <p v-for="note in impact.qc.notes" :key="note" class="page-note">{{ note }}</p>
        </div>
      </div>
    </div>
    <div class="card">
      <h2>历史与恢复</h2>
      <DataTableView :table="history" />
      <div class="field-grid">
        <label
          ><FieldLabel name="历史层" /><select
            aria-label="历史层"
            v-model="layer"
            :disabled="store.busy"
          >
            <option v-for="v in info?.layers" :key="v" :value="v">{{ displayName(v) }}</option>
          </select></label
        >
      </div>
      <div class="actions">
        <button
          class="restore"
          :disabled="store.busy || !layer"
          @click="store.mutate('/analysis/operation', { operation: 'restore', options: { layer } })"
        >
          恢复所选层</button
        ><button
          class="restore"
          :disabled="store.busy"
          @click="
            store.mutate(
              '/analysis/operation',
              { operation: 'reset', options: {} },
              'POST',
              '已恢复完整预处理起点。',
            )
          "
        >
          恢复到预处理起点
        </button>
      </div>
    </div>
  </section>
  <div v-else class="card empty-state">
    <h1>尚未建立当前数据集</h1>
    <p>请先审核提取结果，或导入已有 H5AD。</p>
    <RouterLink to="/extraction">前往提取审核 →</RouterLink>
  </div>
</template>

<style scoped>
.preprocess-comparison :deep(th),
.preprocess-comparison :deep(td) {
  text-align: center;
}
.preprocess-comparison :deep(th .field-label) {
  justify-content: center;
}
.qc-plots {
  display: grid;
  gap: 24px;
}
.qc-plots > div {
  min-width: 0;
}
@media (min-width: 960px) {
  .qc-plots.comparing {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
}
</style>
