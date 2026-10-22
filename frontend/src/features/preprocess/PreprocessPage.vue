<script setup lang="ts">
import { useViewState } from '../../api/viewState'
import { displayName } from '../../help/labels'
import { ref, computed, watch, nextTick } from 'vue'
import { normalizationHelp } from '../../help/fields'
import { useWorkspace } from '../../stores/workspace'
import type { QC, AnalysisInfo, DataTable } from '../../api/types'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
import QCComparison from './QCComparison.vue'
const store = useWorkspace()
const historyOpen = ref(false)
const historyPanel = ref<HTMLElement>()
async function showHistory() {
  historyOpen.value = true
  await nextTick()
  historyPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
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
const advanced = ref({
  scale: 1,
  axis: null as number | null,
  reference: 'median',
  pseudo: 1e-6,
  n_neighbors: 5,
  weights: 'uniform',
  n_estimators: 100,
  random_state: 42,
  max_samples: 'auto',
  max_features: '1.0',
  bootstrap: false,
})
const subsetCells = ref(''),
  subsetFeatures = ref('')
function ids(value: string) {
  const result = value
    .split(/[\n,;]+/)
    .map((v) => v.trim())
    .filter(Boolean)
  return result.length ? result : null
}
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
    advanced.value,
    subsetCells.value,
    subsetFeatures.value,
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
  if (operation.value === 'subset')
    return { cell_ids: ids(subsetCells.value), feature_ids: ids(subsetFeatures.value) }
  return operation.value === 'filter'
    ? {
        min_total: minTotal.value,
        min_detected: minDetected.value,
        min_feature_fraction: fraction.value,
      }
    : operation.value === 'normalize'
      ? {
          method: method.value,
          scale: advanced.value.scale,
          axis: advanced.value.axis,
          reference: advanced.value.reference,
          pseudo: advanced.value.pseudo,
        }
      : operation.value === 'impute'
        ? {
            method: imputation.value,
            n_neighbors: advanced.value.n_neighbors,
            weights: advanced.value.weights,
          }
        : {
            contamination: contamination.value,
            random_state: advanced.value.random_state,
            n_estimators: advanced.value.n_estimators,
            max_samples: advanced.value.max_samples,
            max_features: advanced.value.max_features,
            bootstrap: advanced.value.bootstrap,
          }
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
  advanced,
  subsetCells,
  subsetFeatures,
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
      <div class="actions">
        <button class="restore" @click="showHistory">历史与恢复</button
        ><span class="step-badge">04 / 06</span>
      </div>
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
            <option value="subset">按稳定 ID 取子集</option>
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
            <option value="most_frequent">众数</option>
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
      <div v-if="operation === 'subset'" class="field-grid">
        <label
          >保留细胞 ID（空白保留全部）<textarea
            aria-label="子集细胞ID"
            v-model="subsetCells"
            rows="4"
            :disabled="store.busy"
          />
        </label>
        <label
          >保留特征 ID（空白保留全部）<textarea
            aria-label="子集特征ID"
            v-model="subsetFeatures"
            rows="4"
            :disabled="store.busy"
          />
        </label>
        <p class="muted">
          换行或逗号分隔，至少填写一类；按所列稳定 ID 及顺序构造子集，不使用显示行号或最近
          m/z。应用会使下游分析失效，完整预处理起点仍可恢复。
        </p>
      </div>
      <details v-if="!['filter', 'subset'].includes(operation)" class="preprocessing-advanced">
        <summary>预处理高级参数</summary>
        <p class="muted">
          仅当前方法使用的字段生效；编辑草稿不计算，生效参数记录在历史中。子采样填整数为数量，带小数点为比例。
        </p>
        <div class="field-grid">
          <template v-if="operation === 'normalize'">
            <label v-if="method === 'total'"
              ><span title="scale：归一化后每个细胞的总量，须大于零">总量尺度</span
              ><input
                aria-label="归一化总量尺度"
                type="number"
                min="0"
                step="any"
                v-model.number="advanced.scale"
                :disabled="store.busy"
            /></label>
            <label v-if="['max', 'zscore', 'minmax'].includes(method)"
              ><span title="axis：0 按特征跨细胞，1 按细胞跨特征；自动沿用该方法默认值"
                >计算方向</span
              ><select aria-label="归一化计算方向" v-model="advanced.axis" :disabled="store.busy">
                <option :value="null">方法默认</option>
                <option :value="0">按特征（跨细胞）</option>
                <option :value="1">按细胞（跨特征）</option>
              </select></label
            >
            <label v-if="method === 'pqn'"
              ><span title="reference：使用全体细胞中位数或均值参考谱；自定义向量使用 Python API"
                >参考谱</span
              ><select aria-label="PQN参考谱" v-model="advanced.reference" :disabled="store.busy">
                <option value="median">中位数</option>
                <option value="mean">均值</option>
              </select></label
            >
            <label v-if="method === 'log'"
              ><span title="pseudo：先加此偏移再 log1p，须非负且变换输入大于 -1">对数偏移</span
              ><input
                aria-label="对数偏移"
                type="number"
                min="0"
                step="any"
                v-model.number="advanced.pseudo"
                :disabled="store.busy"
            /></label>
          </template>
          <template v-if="operation === 'impute' && imputation === 'knn'">
            <label
              ><span title="n_neighbors：正整数；实际邻居数不超过细胞数，距离可用供体可能更少"
                >近邻数</span
              ><input
                aria-label="插补近邻数"
                type="number"
                min="1"
                step="1"
                v-model.number="advanced.n_neighbors"
                :disabled="store.busy"
            /></label>
            <label
              ><span title="weights：uniform 等权，distance 按可用距离倒数加权">近邻权重</span
              ><select aria-label="插补近邻权重" v-model="advanced.weights" :disabled="store.busy">
                <option value="uniform">等权</option>
                <option value="distance">距离加权</option>
              </select></label
            >
          </template>
          <template v-if="operation === 'remove_outliers'">
            <label
              ><span title="n_estimators：IsolationForest 树数量，1 至 10000">树数量</span
              ><input
                aria-label="异常检测树数量"
                type="number"
                min="1"
                max="10000"
                step="1"
                v-model.number="advanced.n_estimators"
                :disabled="store.busy"
            /></label>
            <label
              ><span title="max_samples：auto、整数细胞数或 (0,1] 小数比例，不能超过当前细胞数"
                >每树细胞数 / 比例</span
              ><input
                aria-label="异常检测细胞子采样"
                v-model="advanced.max_samples"
                :disabled="store.busy"
            /></label>
            <label
              ><span title="max_features：整数特征数或 (0,1] 小数比例，不能超过当前特征数"
                >每树特征数 / 比例</span
              ><input
                aria-label="异常检测特征子采样"
                v-model="advanced.max_features"
                :disabled="store.busy"
            /></label>
            <label
              ><span title="random_state：随机种子，记录并随保存保留">随机种子</span
              ><input
                aria-label="异常检测随机种子"
                type="number"
                min="0"
                max="2147483647"
                step="1"
                v-model.number="advanced.random_state"
                :disabled="store.busy"
            /></label>
            <label
              ><input type="checkbox" v-model="advanced.bootstrap" :disabled="store.busy" /><span
                title="bootstrap：每棵树有放回抽样"
                >有放回抽样</span
              ></label
            >
          </template>
        </div>
      </details>
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
        <details v-if="countTables.samples.rows.length" class="qc-details">
          <summary>各样本细胞数</summary>
          <DataTableView :table="countTables.samples" />
        </details>
        <details class="qc-details" open>
          <summary>来源文件 QC 指标</summary>
          <QCComparison v-if="qc" :before="qc.files" :after="impact.qc.files" />
        </details>
      </template>
      <template v-else>
        <p class="muted">
          设置上方参数并点击“检查影响”，在此对比操作前与候选后的数量、QC 指标和分布。
        </p>
        <details class="qc-details">
          <summary>当前来源文件 QC 明细</summary>
          <DataTableView v-if="qc" :table="qc.files" qc />
        </details>
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
    <details
      ref="historyPanel"
      class="card history-panel"
      :open="historyOpen"
      @toggle="historyOpen = ($event.target as HTMLDetailsElement).open"
    >
      <summary>历史与恢复</summary>
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
    </details>
  </section>
  <div v-else class="card empty-state">
    <h1>尚未建立当前数据集</h1>
    <p>
      当前打开的项目尚无已保存并载入的数据集。原始谱提取后，请审核并纳入样本；独立 H5AD
      可从样本页导入。
    </p>
    <p>打开含数据快照的完整项目会自动恢复矩阵，无需再从快照目录选择文件导入。</p>
    <RouterLink to="/extraction">前往提取审核 →</RouterLink>
    <RouterLink to="/samples">前往样本与独立结果导入 →</RouterLink>
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
