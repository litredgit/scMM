<script setup lang="ts">
import { displayName } from '../../../help/labels'
import { useViewState } from '../../../api/viewState'
import { ref } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import PlotView from '../../../components/PlotView.vue'
import type { Figure } from '../../../api/types'
const { store, info, selectedFeatures } = useAnalysisContext()
const features = ref(''),
  group = ref(''),
  sample = ref(''),
  equal = ref(false),
  zscore = ref(true),
  rows = ref(true),
  columns = ref(true),
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
  const value = await store.command<Figure>('/analysis/plot', {
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
      sample_key: sample.value || null,
      equal_samples: equal.value,
      zscore: zscore.value,
      cluster_rows: rows.value,
      cluster_columns: columns.value,
    },
  })
  if (value) figure.value = value
}
useViewState('heatmap', { features, group, sample, equal, zscore, rows, columns, layer, figure })
</script>
<template>
  <div class="card">
    <h2>特征热图</h2>
    <p>每行一个特征；标准分只用于展示。分组均值可选择细胞等权或样本等权。</p>
    <label>特征编号（换行或逗号分隔）<textarea v-model="features" rows="5" /></label>
    <div class="actions">
      <button @click="features = selectedFeatures.join('\n')">使用已选特征</button
      ><button class="preview" :disabled="store.busy" @click="useMarkers">
        使用前 50 个正向 Marker</button
      ><button class="preview" :disabled="store.busy" @click="useAnnotated">使用已注释特征</button>
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
        >分组列<select v-model="group">
          <option value="">逐细胞</option>
          <option v-for="(_, key) in info?.observations" :key="key" :value="key">
            {{ displayName(key) }}
          </option>
        </select></label
      ><label
        >样本列<select v-model="sample">
          <option value="">未选择</option>
          <option v-for="(_, key) in info?.observations" :key="key" :value="key">
            {{ displayName(key) }}
          </option>
        </select></label
      ><label
        >均值权重<select v-model="equal">
          <option :value="false">细胞等权</option>
          <option :value="true">样本等权</option>
        </select></label
      ><label
        >行标准分<select v-model="zscore">
          <option :value="true">启用</option>
          <option :value="false">关闭</option>
        </select></label
      ><label
        >特征聚类<select v-model="rows">
          <option :value="true">启用</option>
          <option :value="false">关闭</option>
        </select></label
      ><label
        >细胞或分组聚类<select v-model="columns">
          <option :value="true">启用</option>
          <option :value="false">关闭</option>
        </select></label
      >
    </div>
    <button class="primary" :disabled="store.busy || !features.trim()" @click="draw">
      生成热图</button
    ><PlotView v-if="figure" :figure="figure" name="heatmap" />
  </div>
</template>
