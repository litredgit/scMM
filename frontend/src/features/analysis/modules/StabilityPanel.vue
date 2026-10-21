<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import StoredAnalysisPlot from './StoredAnalysisPlot.vue'
import { displayName } from '../../../help/labels'
const { store, info, stability, featureOptions, search, observed } = useAnalysisContext()
const options = computed(() => ({
  ...stability,
  time_key: stability.time_kind === 'stored_order' ? null : stability.time_key,
}))
const ready = computed(
  () =>
    !!stability.source_key &&
    !!stability.feature &&
    !!stability.time_kind &&
    (stability.time_kind === 'stored_order' || !!stability.time_key),
)
</script>
<template>
  <StoredAnalysisPlot kind="stability" title="采集稳定性 QC" :options="options" :ready="ready">
    <p>明确选择坐标含义及来源。当前存储顺序不等于采集顺序；细胞级稳定性不代表独立生物重复。</p>
    <label
      >搜索参考特征<input aria-label="稳定性参考特征搜索" v-model="search" :disabled="store.busy"
    /></label>
    <div class="field-grid">
      <label
        >参考特征 ID<select
          aria-label="稳定性参考特征"
          v-model="stability.feature"
          :disabled="store.busy"
        >
          <option value="" disabled>明确选择稳定 ID</option>
          <option
            v-if="stability.feature && !featureOptions.some((v) => v.value === stability.feature)"
            :value="stability.feature"
          >
            {{ stability.feature }}（已选）
          </option>
          <option v-for="option in featureOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select></label
      >
      <label
        >来源列<select
          aria-label="稳定性来源列"
          v-model="stability.source_key"
          :disabled="store.busy"
        >
          <option value="" disabled>明确选择来源</option>
          <option v-for="key in observed" :key="key" :value="key">{{ displayName(key) }}</option>
        </select></label
      >
      <label
        >坐标含义<select
          aria-label="稳定性坐标含义"
          v-model="stability.time_kind"
          :disabled="store.busy"
        >
          <option value="" disabled>明确选择坐标含义</option>
          <option value="acquisition_seconds">采集坐标（秒）</option>
          <option value="normalized_time">归一化时间（0–1）</option>
          <option value="pseudotime">伪时间（算法尺度）</option>
          <option value="stored_order">当前存储顺序（非采集时间）</option>
        </select></label
      >
      <label v-if="stability.time_kind !== 'stored_order'"
        >时间列<select
          aria-label="稳定性时间列"
          v-model="stability.time_key"
          :disabled="store.busy"
        >
          <option :value="null" disabled>明确选择数值时间列</option>
          <option v-for="key in observed" :key="key" :value="key">{{ displayName(key) }}</option>
        </select></label
      >
      <label
        ><span title="bins：2 至 100 个等宽窗口，空窗口仍保留；边界最大值纳入最后一个窗口"
          >窗口数</span
        ><input
          aria-label="稳定性窗口数"
          v-model.number="stability.bins"
          type="number"
          min="2"
          max="100"
          step="1"
          :disabled="store.busy"
      /></label>
      <label
        >强度层<select v-model="stability.layer" :disabled="store.busy">
          <option :value="null">当前矩阵</option>
          <option v-for="key in info?.layers" :key="key" :value="key">
            {{ displayName(key) }}
          </option>
        </select></label
      >
    </div>
    <p class="muted">
      最多 100 个来源、200
      万矩阵数值。参考强度箱图、窗口细胞数和来源中位谱相关使用相同的有限坐标细胞；完整导出保留排除标记与空窗口。
    </p>
  </StoredAnalysisPlot>
</template>
