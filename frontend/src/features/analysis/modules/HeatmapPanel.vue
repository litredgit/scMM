<script setup lang="ts">
import { displayName } from '../../../help/labels'
import { useViewState } from '../../../api/viewState'
import { ref, computed, watch } from 'vue'
import PlotScope, { type Scope } from '../components/PlotScope.vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import PlotView from '../../../components/PlotView.vue'
import type { Figure } from '../../../api/types'
const { store, info, selectedFeatures, refreshAnalysis } = useAnalysisContext()
const scope = ref<Scope>({ group_key: 'group', groups: null, sample_key: 'sample', samples: null })
const colorscale = ref('RdBu'),
  colorMin = ref<number | ''>(''),
  colorMax = ref<number | ''>('')
const applied = ref('')
const signature = computed(() =>
  JSON.stringify([
    features.value,
    group.value,
    sample.value,
    equal.value,
    zscore.value,
    rows.value,
    columns.value,
    layer.value,
    scope.value,
    colorscale.value,
    colorMin.value,
    colorMax.value,
  ]),
)
const features = ref(''),
  group = ref(''),
  sample = ref(''),
  equal = ref(false),
  zscore = ref(true),
  rows = ref(true),
  columns = ref(false),
  layer = ref<string | null>(null),
  figure = ref<Figure>()
async function useAnnotated() {
  const value = await store.read<{ features: string[] }>('/analysis/annotated-features')
  if (value) features.value = value.features.join('\n')
}
async function useMarkers() {
  const result = await store.read<{ table: { rows: Record<string, unknown>[] } }>(
    '/analysis/results/markers?limit=1000',
  )
  if (result)
    features.value = [
      ...new Set(
        result.table.rows
          .filter((r) => r.weight === undefined || Number(r.weight) > 0)
          .map((r) => String(r.feature_id)),
      ),
    ]
      .slice(0, 50)
      .join('\n')
}
async function draw() {
  const requested = signature.value
  await store.analysisTransaction(async (api) => {
    const value = await api.command<Figure>('/analysis/plot', {
      kind: 'heatmap',
      options: {
        features: [
          ...new Set(
            features.value
              .split(/[\n,;]+/)
              .map((v) => v.trim())
              .filter(Boolean),
          ),
        ],
        layer: layer.value,
        group_key: group.value || null,
        sample_key: sample.value || scope.value.sample_key,
        equal_samples: equal.value,
        zscore: zscore.value,
        cluster_rows: rows.value,
        cluster_columns: columns.value,
        scope: scope.value,
        colorscale: colorscale.value,
        color_min: colorMin.value === '' ? null : colorMin.value,
        color_max: colorMax.value === '' ? null : colorMax.value,
      },
    })
    if (value && api.isCurrent?.() !== false) {
      figure.value = value
      applied.value = requested
      await refreshAnalysis(api)
    }
  })
}
async function readSaved() {
  await store.analysisTransaction(async (api) => {
    const value = await api.read<Figure>('/analysis/figures/heatmap')
    if (!value || api.isCurrent?.() === false) return
    const parameters = (value.layout.meta as { parameters?: Record<string, unknown> } | undefined)
      ?.parameters
    if (parameters) {
      if (Array.isArray(parameters.features)) features.value = parameters.features.join('\n')
      group.value = typeof parameters.group_key === 'string' ? parameters.group_key : ''
      sample.value = typeof parameters.sample_key === 'string' ? parameters.sample_key : ''
      layer.value = typeof parameters.layer === 'string' ? parameters.layer : null
      for (const [name, target] of [
        ['equal_samples', equal],
        ['zscore', zscore],
        ['cluster_rows', rows],
        ['cluster_columns', columns],
      ] as const)
        if (typeof parameters[name] === 'boolean') target.value = parameters[name] as boolean
      scope.value = parameters.scope
        ? (parameters.scope as Scope)
        : { group_key: 'group', groups: null, sample_key: 'sample', samples: null }
      if (typeof parameters.colorscale === 'string') colorscale.value = parameters.colorscale
      colorMin.value = typeof parameters.color_min === 'number' ? parameters.color_min : ''
      colorMax.value = typeof parameters.color_max === 'number' ? parameters.color_max : ''
    }
    figure.value = value
    applied.value = signature.value
  })
}
watch(
  () =>
    JSON.stringify([store.current?.workspace_id, store.project?.path, store.project?.dataset?.id]),
  () => {
    figure.value = undefined
    features.value = ''
    scope.value = { group_key: 'group', groups: null, sample_key: 'sample', samples: null }
  },
)
useViewState('heatmap', {
  features,
  group,
  sample,
  equal,
  zscore,
  rows,
  columns,
  layer,
  figure,
  scope,
  colorscale,
  colorMin,
  colorMax,
  applied,
})
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>特征热图</h2>
      <p>每行一个特征；标准分只用于展示。分组均值可选择细胞等权或样本等权。</p>
      <PlotScope
        v-model="scope"
        :observations="info?.observations ?? {}"
        :disabled="store.busy"
        ordered
      />
      <p v-if="!columns" class="muted">
        按上方样本顺序排列，样本内按峰顶采集时间排列；缺少时间时保留原始顺序。
      </p>
      <p v-else class="muted">列聚类会重新排列细胞或均值列，不保留指定样本顺序。</p>
      <label>特征编号（换行或逗号分隔）<textarea v-model="features" rows="5" /></label>
      <div class="actions">
        <button @click="features = selectedFeatures.join('\n')">使用已选特征</button
        ><button class="preview" :disabled="store.busy" @click="useMarkers">
          使用前 50 个正向 Marker</button
        ><button class="preview" :disabled="store.busy" @click="useAnnotated">
          使用已注释特征
        </button>
      </div>
      <div class="field-grid">
        <label
          >强度层<select v-model="layer">
            <option :value="null">当前矩阵</option>
            <option v-for="key in info?.layers" :key="key" :value="key">
              {{ displayName(key) }}
            </option>
          </select></label
        ><label
          >列汇总<select v-model="group" aria-label="列汇总">
            <option value="">逐细胞</option>
            <option :value="scope.sample_key">按样本均值</option>
            <option :value="scope.group_key">按组均值</option>
            <option v-for="(_, key) in info?.observations" :key="key" :value="key">
              {{ displayName(key) }}
            </option>
          </select></label
        ><label
          >均值的样本权重列<select v-model="sample" aria-label="均值的样本权重列">
            <option value="">使用作图样本列</option>
            <option v-for="(_, key) in info?.observations" :key="key" :value="key">
              {{ displayName(key) }}
            </option>
          </select></label
        ><label
          >均值权重<select v-model="equal" aria-label="均值权重">
            <option :value="false">细胞等权</option>
            <option :value="true">样本等权</option>
          </select></label
        ><label
          >行标准分<select v-model="zscore" aria-label="行标准分">
            <option :value="true">启用</option>
            <option :value="false">关闭</option>
          </select></label
        ><label
          >特征聚类<select v-model="rows" aria-label="特征聚类">
            <option :value="true">启用</option>
            <option :value="false">关闭</option>
          </select></label
        ><label
          >细胞或分组聚类<select v-model="columns" aria-label="细胞或分组聚类">
            <option :value="true">启用</option>
            <option :value="false">关闭</option>
          </select></label
        >
        <label
          >热图色板<select v-model="colorscale" aria-label="热图色板">
            <option value="RdBu">蓝白红</option>
            <option value="PuOr">紫白橙</option>
            <option value="Viridis">Viridis</option>
            <option value="Cividis">Cividis</option>
          </select></label
        >
        <label
          >色阶下限（空为自动）<input
            v-model.number="colorMin"
            type="number"
            step="any"
            aria-label="热图色阶下限"
        /></label>
        <label
          >色阶上限（空为自动）<input
            v-model.number="colorMax"
            type="number"
            step="any"
            aria-label="热图色阶上限"
        /></label>
      </div>
      <button
        class="primary"
        :disabled="
          store.busy ||
          !features.trim() ||
          scope.groups?.length === 0 ||
          scope.samples?.length === 0
        "
        @click="draw"
      >
        生成热图
      </button>
      <button
        v-if="info?.figures.includes('heatmap')"
        class="preview"
        :disabled="store.busy"
        @click="readSaved"
      >
        读取已保存热图
      </button>
    </section>
    <section class="analysis-visualization">
      <h3>图形</h3>
      <p v-if="figure && signature !== applied" role="status">
        设置已编辑，点击“生成热图”应用；当前显示和下载仍使用上次成功生成的图。
      </p>
      <PlotView v-if="figure" :figure="figure" name="heatmap" />
      <p v-else class="empty-state">选择特征与显示设置，生成热图。</p>
    </section>
  </div>
</template>
