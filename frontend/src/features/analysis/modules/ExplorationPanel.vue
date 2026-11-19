<script setup lang="ts">
import ScientificInput from '../../../components/ScientificInput.vue'
import { computed, ref, watch } from 'vue'
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
const groupKey = ref('group'),
  groups = ref(''),
  detection = ref(0),
  intensity = ref(0),
  setKind = ref('upset'),
  annotation = ref('')
const entity = ref('feature')
const figure = ref<Figure>()
const notes = computed(
  () => (figure.value?.layout.meta as { notes?: string[] } | undefined)?.notes ?? [],
)
watch(
  () => [store.current?.workspace_id, store.project?.path, store.project?.dataset?.id],
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
      layer: layer.value,
      replicate_key: replicate.value || null,
      permutations: permutations.value,
      seed: seed.value,
      include_zeros: zeros.value,
    }
  return {
    entity: entity.value,
    group_key: groupKey.value,
    groups: groups.value
      .split(/[\n,，;]+/)
      .map((v) => v.trim())
      .filter(Boolean),
    layer: layer.value,
    detection_rate: detection.value,
    intensity_threshold: intensity.value,
    kind: setKind.value,
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
  groups,
  detection,
  intensity,
  setKind,
  annotation,
  figure,
})
</script>
<template>
  <div class="card">
    <h2>相关性与集合比较</h2>
    <label
      >分析方式<select v-model="kind" :disabled="store.busy" @change="figure = undefined">
        <option value="target_correlations">目标变量与全部特征的相关性</option>
        <option value="association">数值关联与重复单位检验</option>
        <option value="set_comparison">特征集合比较</option>
      </select></label
    >
    <label
      >输入强度层<select v-model="layer" :disabled="store.busy">
        <option :value="null">当前矩阵</option>
        <option v-for="key in info?.layers" :key="key" :value="key">{{ key }}</option>
      </select></label
    >
    <template v-if="kind !== 'set_comparison'">
      <label
        >目标变量<input
          v-model="target"
          :disabled="store.busy"
          placeholder="feature:稳定特征编号 或 obs:数值列名"
      /></label>
      <label
        >零值处理<select v-model="zeros" :disabled="store.busy">
          <option :value="true">保留零值</option>
          <option :value="false">逐对排除任一变量为零的细胞</option>
        </select></label
      >
      <label v-if="kind === 'target_correlations'"
        >相关方法<select v-model="method" :disabled="store.busy">
          <option value="pearson">Pearson</option>
          <option value="spearman">Spearman</option>
          <option value="kendall">Kendall</option>
        </select></label
      >
      <template v-else>
        <label
          >纵轴变量<input
            v-model="y"
            :disabled="store.busy"
            placeholder="feature:稳定特征编号 或 obs:数值列名"
        /></label>
        <label
          >独立重复单位<select v-model="replicate" :disabled="store.busy">
            <option value="">细胞级描述，不作置换检验</option>
            <option v-for="(_, key) in info?.observations" :key="key" :value="key">
              {{ key }}
            </option>
          </select></label
        >
        <label
          >置换次数（0 为关闭）<input
            v-model.number="permutations"
            type="number"
            min="0"
            max="10000"
            :disabled="store.busy || !replicate"
        /></label>
        <label
          >随机种子<input v-model.number="seed" type="number" min="0" :disabled="store.busy"
        /></label>
        <p>选择重复列后先计算各重复的均值。请使用真实独立重复；分组标签本身不等于重复单位。</p>
      </template>
    </template>
    <template v-else>
      <label
        >集合对象<select v-model="entity" :disabled="store.busy">
          <option value="feature">稳定特征</option>
          <option value="candidate">当前有效版本的候选身份</option>
        </select></label
      >
      <label
        >分组列<select v-model="groupKey" :disabled="store.busy">
          <option v-for="(_, key) in info?.observations" :key="key" :value="key">{{ key }}</option>
        </select></label
      >
      <label>参与比较的分组（逗号分隔）<input v-model="groups" :disabled="store.busy" /></label>
      <label
        >检出强度下限<ScientificInput
          :model-value="intensity"
          @update:model-value="intensity = $event ?? 0"
          scientific
          :disabled="store.busy"
      /></label>
      <label
        >组内最低检出比例<input
          v-model.number="detection"
          type="number"
          min="0"
          max="1"
          step="0.01"
          :disabled="store.busy"
      /></label>
      <label
        >图形<select v-model="setKind" :disabled="store.busy">
          <option value="upset">UpSet 交集与成员关系</option>
          <option value="venn">Venn（2–3 组，面积不按数量缩放）</option>
        </select></label
      >
      <label
        >下载表的注释标签<select v-model="annotation" :disabled="store.busy">
          <option value="">稳定特征编号</option>
          <option v-for="key in info?.feature_columns" :key="key" :value="key">{{ key }}</option>
        </select></label
      >
      <p>集合按稳定特征编号计数，名称仅作标签。相同名称不自动视为同一化合物。</p>
    </template>
    <div class="actions">
      <button class="primary" :disabled="store.busy" @click="draw()">计算并绘图</button
      ><button
        class="preview"
        :disabled="store.busy || !info?.figures.includes(kind)"
        @click="draw(true)"
      >
        读取已保存图形
      </button>
    </div>
    <p v-for="note in notes" :key="note" class="muted">{{ note }}</p>
    <PlotView v-if="figure" :figure="figure" :name="kind" />
  </div>
</template>
