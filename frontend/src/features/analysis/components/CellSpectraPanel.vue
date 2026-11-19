<script setup lang="ts">
import { useViewState } from '../../../api/viewState'
import { computed, ref, watch } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import PlotView from '../../../components/PlotView.vue'
import type { Figure } from '../../../api/types'
const store = useWorkspace()
const sampleInput = computed(() => store.project?.dataset?.observation_kind === 'sample')
const observationLabel = computed(() => (sampleInput.value ? '样本' : '细胞'))
const source = ref('matrix'),
  normalization = ref('raw'),
  mirror = ref(false),
  average = ref(false),
  figure = ref<Figure>()
watch(sampleInput, (sample) => {
  if (sample) source.value = 'matrix'
})
watch(
  () => JSON.stringify(store.selectedCells),
  () => {
    figure.value = undefined
  },
)
async function draw() {
  const selected = JSON.stringify(store.selectedCells)
  const value = await store.command<Figure>('/analysis/cell-spectra', {
    cells: store.selectedCells,
    source: source.value,
    normalization: normalization.value,
    mirror: mirror.value,
    average: average.value,
  })
  if (value && selected === JSON.stringify(store.selectedCells)) figure.value = value
}
useViewState('cell-spectra', { source, normalization, mirror, average, figure })
</script>
<template>
  <div v-if="store.selectedCells.length" class="card selected-cell-spectra">
    <div class="section-heading">
      <h2>{{ sampleInput ? '所选样本特征谱' : '所选细胞质谱' }}</h2>
      <button @click="store.selectedCells = []">清除所选{{ observationLabel }}</button>
    </div>
    <p>点击分析图中的{{ observationLabel }}点选择，最多保留两个{{ observationLabel }}。</p>
    <p v-if="sampleInput" class="muted">
      普通样本矩阵可查看当前特征谱。提取窗口和峰顶原始谱适用于已提取细胞。
    </p>
    <div class="actions">
      <button
        v-for="cell in store.selectedCells"
        :key="cell"
        @click="store.selectedCells = store.selectedCells.filter((c) => c !== cell)"
      >
        {{ cell }} ×
      </button>
    </div>
    <div class="field-grid">
      <label
        >谱来源<select v-model="source">
          <option value="matrix">当前矩阵特征谱</option>
          <option value="window" :disabled="sampleInput">提取窗口合谱</option>
          <option value="apex" :disabled="sampleInput">峰顶单扫描原始谱</option>
        </select></label
      ><label
        >强度<select v-model="normalization">
          <option value="raw">原始强度</option>
          <option value="max">最大值归一化</option>
          <option value="tic">总强度归一化</option>
        </select></label
      ><label
        >对比布局<select v-model="mirror">
          <option :value="false">叠加</option>
          <option :value="true">上下镜像</option>
        </select></label
      ><label v-if="source === 'window'"
        >窗口计算<select v-model="average">
          <option :value="false">求和</option>
          <option :value="true">扫描平均</option>
        </select></label
      >
    </div>
    <button class="preview" :disabled="store.busy" @click="draw">查看质谱</button
    ><PlotView v-if="figure" :figure="figure" name="cell-spectra" />
  </div>
</template>
