<script setup lang="ts">
import { openCsvText } from '../../../api/csvExport'
import NumericVariable from '../../../components/NumericVariable.vue'
import ScientificInput from '../../../components/ScientificInput.vue'
import { computed, ref, watch, shallowRef } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import PlotView from '../../../components/PlotView.vue'
import type { Figure } from '../../../api/types'
import { useViewState } from '../../../api/viewState'
const { store, info, refreshAnalysis } = useAnalysisContext()
const kind = ref('target_correlations'),
  target = ref(''),
  y = ref(''),
  layer = ref<string | null>(null)
const method = ref('pearson'),
  zeros = ref(true),
  replicate = ref(''),
  permutations = ref(0),
  seed = ref(42)
const groupKey = ref(''),
  groups = ref<string[]>([]),
  detection = ref(0),
  intensity = ref(0),
  setKind = ref('auto'),
  annotation = ref('')
const entity = ref('feature')
const figure = shallowRef<Figure>()
const grouping = computed(() => {
  if (groupKey.value && info.value?.observations[groupKey.value]) return groupKey.value
  return (
    ['sample_id', 'sample', 'group', 'source_file'].find((key) =>
      info.value?.observations[key]?.some((value) => value.trim()),
    ) ?? ''
  )
})
const choices = computed(() =>
  (info.value?.observations[grouping.value] ?? []).filter((value) => value.trim()),
)
const chosen = computed(() => groups.value.filter((group) => choices.value.includes(group)))
function changeGrouping(event: Event) {
  groupKey.value = (event.target as HTMLSelectElement).value
  groups.value = []
}
const format = computed(() =>
  setKind.value === 'auto' ? (chosen.value.length <= 3 ? 'venn' : 'upset') : setKind.value,
)
const canDraw = computed(() =>
  kind.value === 'set_comparison'
    ? chosen.value.length >= 2 && (format.value !== 'venn' || chosen.value.length <= 3)
    : !!target.value && (kind.value !== 'association' || (!!y.value && y.value !== target.value)),
)
const meta = computed(
  () =>
    figure.value?.layout.meta as
      | {
          association?: {
            n: number
            method: string
            correlation: number
            slope: number
            intercept: number
            r2: number
            unit: string
          }
          set_counts?: {
            union: number
            intersection: number
            groups: { id: string; name: string; total: number; unique: number }[]
          }
          export_tables?: Record<string, string>
        }
      | undefined,
)
const sampleName = (key: string) =>
  grouping.value === 'sample_id' ? (info.value?.sample_labels?.[key] ?? key) : key
function exportTable(key: string) {
  const source = figure.value
  const text = meta.value?.export_tables?.[key]
  if (text !== undefined) openCsvText(key + '.csv', text, () => figure.value === source)
}
const number = (value: number) => (Number.isFinite(value) ? value.toPrecision(5) : '—')
const notes = computed(
  () => (figure.value?.layout.meta as { notes?: string[] } | undefined)?.notes ?? [],
)
watch(
  () => [
    store.current?.workspace_id,
    store.project?.path,
    store.project?.dataset?.id,
    store.project?.dataset?.revision,
  ],
  () => {
    figure.value = undefined
  },
)
watch(
  () => info.value?.figures,
  (values) => {
    if (values && !values.includes(kind.value)) figure.value = undefined
  },
)
function options() {
  if (kind.value === 'target_correlations')
    return {
      target: target.value,
      layer: layer.value,
      method: method.value,
      include_zeros: zeros.value,
    }
  if (kind.value === 'association')
    return {
      x: target.value,
      y: y.value,
      method: method.value,
      layer: layer.value,
      replicate_key: replicate.value || null,
      permutations: permutations.value,
      seed: seed.value,
      include_zeros: zeros.value,
    }
  return {
    entity: entity.value,
    group_key: grouping.value,
    groups: chosen.value,
    layer: layer.value,
    detection_rate: detection.value,
    intensity_threshold: intensity.value,
    kind: format.value,
    annotation_key: annotation.value || null,
  }
}
async function draw(saved = false) {
  await store.analysisTransaction(async (api) => {
    const value = saved
      ? await api.read<Figure>(`/analysis/figures/${kind.value}`)
      : await api.command<Figure>('/analysis/plot', { kind: kind.value, options: options() })
    if (value && api.isCurrent?.() !== false) {
      figure.value = value
      await refreshAnalysis(api)
    }
  })
}
useViewState('exploration', {
  kind,
  entity,
  target,
  y,
  layer,
  method,
  zeros,
  replicate,
  permutations,
  seed,
  groupKey,
  groupsSelected: groups,
  detection,
  intensity,
  setKind,
  annotation,
})
</script>
<template>
  <div class="card exploration">
    <h2>相关性与集合比较</h2>
    <div class="field-grid">
      <label
        >分析方式
        <select v-model="kind" :disabled="store.busy" @change="figure = undefined">
          <option value="target_correlations">目标变量与全部特征的相关性</option>
          <option value="association">双变量相关与线性回归</option>
          <option value="set_comparison">特征集合比较</option>
        </select>
      </label>
      <label
        >强度层
        <select v-model="layer" :disabled="store.busy">
          <option :value="null">当前矩阵</option>
          <option v-for="name in info?.layers ?? []" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
    </div>
    <template v-if="kind !== 'set_comparison'">
      <div class="field-grid">
        <NumericVariable
          v-model="target"
          :label="kind === 'association' ? '横轴变量' : '目标变量'"
          :disabled="store.busy"
        />
        <NumericVariable
          v-if="kind === 'association'"
          v-model="y"
          label="纵轴变量"
          :disabled="store.busy"
        />
        <label
          >零值处理
          <select v-model="zeros" :disabled="store.busy">
            <option :value="true">保留零值</option>
            <option :value="false">排除任一变量为零的观测</option>
          </select>
        </label>
        <label
          >相关方法
          <select v-model="method" :disabled="store.busy">
            <option value="pearson">Pearson</option>
            <option value="spearman">Spearman</option>
            <option value="kendall">Kendall</option>
          </select>
        </label>
      </div>
      <details v-if="kind === 'association'">
        <summary>独立重复与置换检验</summary>
        <div class="field-grid">
          <label
            >独立重复单位<select v-model="replicate" :disabled="store.busy">
              <option value="">按观测描述</option>
              <option v-for="(_, key) in info?.observations" :key="key" :value="key">
                {{ key }}
              </option>
            </select></label
          >
          <label
            >置换次数（0 为关闭）
            <input
              v-model.number="permutations"
              type="number"
              min="0"
              max="10000"
              :disabled="store.busy || !replicate"
            />
          </label>
          <label
            >随机种子
            <input v-model.number="seed" type="number" min="0" :disabled="store.busy" />
          </label>
        </div>
        <p class="muted">
          选择真实独立重复列后，先计算每个重复的均值，再按所选置换次数检验 Pearson 相关性。
        </p>
      </details>
    </template>
    <template v-else>
      <div class="field-grid">
        <label
          >集合对象<select v-model="entity" :disabled="store.busy">
            <option value="feature">稳定特征</option>
            <option value="candidate">当前有效版本的候选身份</option>
          </select></label
        >
        <label
          >分组列<select :value="grouping" :disabled="store.busy" @change="changeGrouping">
            <option v-for="(_, key) in info?.observations" :key="key" :value="key">
              {{ key === 'sample_id' ? '样本（稳定编号）' : key }}
            </option>
          </select></label
        >
        <label
          >检出强度下限<ScientificInput
            :model-value="intensity"
            @update:model-value="intensity = $event ?? 0"
            scientific
            :disabled="store.busy"
        /></label>
        <label
          >组内最低检出比例
          <input
            v-model.number="detection"
            type="number"
            min="0"
            max="1"
            step="0.01"
            :disabled="store.busy"
          />
        </label>
        <label
          >图形
          <select v-model="setKind" :disabled="store.busy">
            <option value="auto">自动选择 Venn／UpSet</option>
            <option value="venn" :disabled="chosen.length > 3">Venn（2–3 组）</option>
            <option value="upset">UpSet</option>
          </select>
        </label>
        <label
          >特征表的注释标签
          <select v-model="annotation" :disabled="store.busy">
            <option value="">稳定特征编号</option>
            <option v-for="key in info?.feature_columns" :key="key" :value="key">{{ key }}</option>
          </select>
        </label>
      </div>
      <fieldset class="sample-sets" :disabled="store.busy">
        <legend>参与比较的样本或组（{{ chosen.length }} / 20）</legend>
        <label v-for="group in choices" :key="group" class="inline-check">
          <input
            v-model="groups"
            type="checkbox"
            :value="group"
            :disabled="chosen.length >= 20 && !chosen.includes(group)"
          />
          {{ sampleName(group) }}
        </label>
      </fieldset>
      <p v-if="chosen.length < 2" class="muted">请选择至少两个样本或组。</p>
      <p v-else-if="chosen.length > 3 && format === 'venn'" class="muted">
        当前样本数可用 UpSet 展示。
      </p>
    </template>
    <div class="actions">
      <button class="primary" :disabled="store.busy || !canDraw" @click="draw()">计算并绘图</button>
      <button
        class="preview"
        :disabled="store.busy || !info?.figures.includes(kind)"
        @click="draw(true)"
      >
        读取已保存图形
      </button>
    </div>
    <div v-if="meta?.association" class="actions association-summary">
      <span
        >有效数 <strong>{{ meta.association.n }}</strong></span
      >
      <span
        >{{ meta.association.method }}
        <strong>{{ number(meta.association.correlation) }}</strong></span
      >
      <span
        >OLS 斜率 <strong>{{ number(meta.association.slope) }}</strong></span
      >
      <span
        >截距 <strong>{{ number(meta.association.intercept) }}</strong></span
      >
      <span
        >R² <strong>{{ number(meta.association.r2) }}</strong></span
      >
      <button
        v-if="meta.export_tables?.statistics"
        class="download"
        @click="exportTable('statistics')"
      >
        回归统计 CSV 导出
      </button>
    </div>
    <div v-if="meta?.set_counts" class="set-summary">
      <div class="actions">
        <span
          >并集 <strong>{{ meta.set_counts.union }}</strong></span
        >
        <span
          >所有所选项共有 <strong>{{ meta.set_counts.intersection }}</strong></span
        >
        <button class="download" @click="exportTable('membership')">集合成员 CSV 导出</button>
        <button class="download" @click="exportTable('intersections')">交集计数 CSV 导出</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>样本或组</th>
            <th>检出数</th>
            <th>独有数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in meta.set_counts.groups" :key="item.id">
            <td>{{ item.name }}</td>
            <td>{{ item.total }}</td>
            <td>{{ item.unique }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-for="note in notes" :key="note" class="muted">{{ note }}</p>
    <PlotView v-if="figure" :figure="figure" :name="kind" />
  </div>
</template>

<style scoped>
.exploration > .field-grid,
.exploration > details {
  margin-bottom: 10px;
}
.sample-sets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  max-height: 140px;
  overflow: auto;
  padding: 6px 10px;
  margin: 8px 0;
  border: 1px solid #dbe4ed;
}
.set-summary table {
  width: auto;
  min-width: 45%;
}
.association-summary span,
.set-summary .actions > span {
  padding: 3px 8px;
  background: #f0f5f8;
  border-radius: 4px;
}
</style>
