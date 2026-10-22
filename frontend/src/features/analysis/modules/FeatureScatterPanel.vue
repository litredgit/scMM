<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import { useViewState } from '../../../api/viewState'
import { displayName } from '../../../help/labels'
import PlotView from '../../../components/PlotView.vue'
import type { Figure } from '../../../api/types'
import PlotScope from '../components/PlotScope.vue'
const {
  store,
  info,
  scatter,
  observed,
  featureOptions,
  search,
  featureOffset,
  featureTotal,
  pageFeatures,
  refreshAnalysis,
  plotScope,
} = useAnalysisContext()
const figure = ref<Figure>()
let generation = 0
const identity = () =>
  JSON.stringify([store.current?.workspace_id, store.project?.path, store.project?.dataset?.id])
watch(identity, () => {
  generation++
  figure.value = undefined
})
watch(
  () => info.value?.figures,
  (value) => {
    if (value && !value.includes('feature_scatter')) figure.value = undefined
  },
)
const metadata = computed(
  () =>
    (figure.value?.layout.meta ?? {}) as {
      notes?: string[]
      regression?: Record<string, unknown>
      parameters?: Record<string, unknown>
    },
)
const notes = computed(() => metadata.value.notes ?? [])
const fit = computed(() => metadata.value.regression)
const edited = computed(() => {
  const parameters = metadata.value.parameters
  return (
    parameters &&
    (Object.entries(scatter).some(([key, value]) => parameters[key] !== value) ||
      JSON.stringify(parameters.scope) !== JSON.stringify(plotScope.value))
  )
})
const states: Record<string, string> = {
  fitted: '已拟合',
  disabled: '未启用',
  constant_y: '纵轴为常量',
  insufficient_or_constant_x: '点数不足或横轴为常量',
  numerical_failure: '数值尺度不适合拟合',
}
function metric(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toExponential(2) : '未定义'
}
async function draw(saved = false) {
  const target = identity(),
    token = ++generation
  await store.analysisTransaction(async (api) => {
    const value = saved
      ? await api.read<Figure>('/analysis/figures/feature_scatter')
      : await api.command<Figure>('/analysis/plot', {
          kind: 'feature_scatter',
          options: { ...scatter, scope: plotScope.value },
        })
    if (target === identity() && token === generation && value && api.isCurrent?.() !== false) {
      figure.value = value
      await refreshAnalysis(api)
    }
  })
}
useViewState('feature_scatter', { figure })
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>双特征散点</h2>
      <PlotScope
        v-model="plotScope"
        :observations="info?.observations ?? {}"
        :disabled="store.busy"
      />
      <p class="muted">回归线描述当前作图范围内的细胞，不重新计算已有差异检验。</p>
      <p>
        按稳定特征 ID 选择两轴，不自动匹配最近
        m/z。零值保留，回归描述所选范围内全部有限细胞，不能替代独立生物重复。
      </p>
      <label
        >搜索特征<input aria-label="散点特征搜索" v-model="search" :disabled="store.busy"
      /></label>
      <div class="field-grid">
        <label v-for="axis in ['feature_a', 'feature_b'] as const" :key="axis">
          {{ axis === 'feature_a' ? '横轴特征' : '纵轴特征' }}
          <select
            :aria-label="axis === 'feature_a' ? '散点横轴特征' : '散点纵轴特征'"
            v-model="scatter[axis]"
            :disabled="store.busy"
          >
            <option value="" disabled>选择特征 ID</option>
            <option
              v-if="scatter[axis] && !featureOptions.some((v) => v.value === scatter[axis])"
              :value="scatter[axis]"
            >
              {{ scatter[axis] }}（已选）
            </option>
            <option v-for="option in featureOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label
          >强度层<select aria-label="散点强度层" v-model="scatter.layer" :disabled="store.busy">
            <option :value="null">当前矩阵</option>
            <option v-for="key in info?.layers" :key="key" :value="key">
              {{ displayName(key) }}
            </option>
          </select></label
        >
        <label
          >来源 / 分组着色<select
            aria-label="散点着色列"
            v-model="scatter.color_key"
            :disabled="store.busy"
          >
            <option :value="null">统一颜色</option>
            <option v-for="key in observed" :key="key" :value="key">{{ displayName(key) }}</option>
          </select></label
        >
        <label
          ><input
            type="checkbox"
            aria-label="散点线性回归"
            v-model="scatter.regression"
            :disabled="store.busy"
          />显示全体细胞线性回归</label
        >
      </div>
      <div class="actions">
        <button
          class="preview"
          :disabled="store.busy || featureOffset === 0"
          @click="pageFeatures(-200)"
        >
          上一页特征
        </button>
        <span
          >{{ featureOffset + 1 }}–{{ featureOffset + featureOptions.length }} /
          {{ featureTotal }}</span
        >
        <button
          class="preview"
          :disabled="store.busy || featureOffset + featureOptions.length >= featureTotal"
          @click="pageFeatures(200)"
        >
          下一页特征
        </button>
      </div>
      <div class="actions">
        <button
          class="primary"
          :disabled="
            store.busy ||
            !scatter.feature_a ||
            !scatter.feature_b ||
            scatter.feature_a === scatter.feature_b
          "
          @click="draw()"
        >
          绘制双特征散点
        </button>
        <button
          v-if="info?.figures.includes('feature_scatter')"
          class="preview"
          :disabled="store.busy"
          @click="draw(true)"
        >
          读取已保存散点
        </button>
      </div>
      <p class="muted">
        编辑草稿不重画。图形和完整数据随主动保存保留；常量或非有限数值的处理见图形说明及导出表。
      </p>
    </section>
    <section class="analysis-visualization">
      <h3>图形与说明</h3>
      <p v-if="edited">参数已编辑，点击“绘制双特征散点”更新图形。</p>
      <div v-if="fit" aria-label="散点回归摘要">
        <p>
          回归状态：{{ states[String(fit.status)] ?? fit.status }}；有限细胞数：{{ fit.n_cells }}
        </p>
        <p>
          斜率：{{ metric(fit.slope) }}；截距：{{ metric(fit.intercept) }}；R²：{{
            metric(fit.r_squared)
          }}；p 值：{{ metric(fit.p_value) }}
        </p>
      </div>
      <p v-for="note in notes" :key="note">{{ note }}</p>
      <PlotView v-if="figure" :figure="figure" name="feature_scatter" />
      <p v-else class="empty-state">选择两个特征后绘图，或读取项目中已保存的散点。</p>
    </section>
  </div>
</template>
