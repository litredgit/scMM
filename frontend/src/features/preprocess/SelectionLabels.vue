<script setup lang="ts">
import { ref, watch } from 'vue'
import PlotView from '../../components/PlotView.vue'
import type { Figure } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
const gateFigure = ref<Figure>()
async function drawGate() {
  gateFigure.value = await store.command<Figure>('/analysis/selection-plot', {
    x: x.value,
    y: y.value,
  })
}
function selection(ids: string[]) {
  selected.value = ids.join('\n')
}
const name = ref('review'),
  axis = ref('cell'),
  mode = ref('ids'),
  selected = ref(''),
  enabled = ref(true),
  invert = ref(false),
  threshold = ref(0.1),
  source = ref(''),
  x = ref(''),
  y = ref(''),
  polygon = ref(''),
  contamination = ref(0.05)
const labels = ref<Record<string, { axis: string; enabled: boolean }>>({})
async function read() {
  const value = await store.read<{ labels: typeof labels.value }>('/analysis/selection-labels')
  if (value) labels.value = value.labels
}
watch(
  () => [store.current?.workspace_id, store.project?.dataset?.id, store.project?.dataset?.revision],
  () => {
    labels.value = {}
    if (store.project?.dataset) void read()
  },
  { immediate: true },
)
async function apply(toggle?: string) {
  const record = toggle ? labels.value[toggle] : undefined
  await store.mutate(
    '/analysis/selection-labels',
    toggle
      ? {
          name: toggle.replace(/^(cell|feature)_keep_/, ''),
          axis: record!.axis,
          mode: 'toggle',
          enabled: !record!.enabled,
        }
      : {
          name: name.value,
          axis: axis.value,
          mode: mode.value === 'lasso' ? 'ids' : mode.value,
          ids: selected.value
            .split(/[\n,;]+/)
            .map((v) => v.trim())
            .filter(Boolean),
          enabled: enabled.value,
          invert: invert.value,
          threshold: threshold.value,
          source_file: source.value || null,
          x: x.value || null,
          y: y.value || null,
          polygon:
            mode.value === 'polygon'
              ? polygon.value
                  .split('\n')
                  .filter((v) => v.trim())
                  .map((v) => v.split(/[,，\s]+/).map(Number))
              : null,
          contamination: contamination.value,
          seed: 42,
        },
  )
  await read()
}
</script>
<template>
  <section class="card">
    <h2>可逆筛选标签</h2>
    <p>
      标签组合使用交集。关闭全部标签可恢复完整筛选前矩阵；启用期间请先关闭标签再归一化、插补或执行其他矩阵变换。
    </p>
    <label
      >标签名<input v-model="name" :disabled="store.busy" placeholder="英文字母、数字和下划线"
    /></label>
    <label
      >对象<select v-model="axis" :disabled="store.busy" @change="mode = 'ids'">
        <option value="cell">细胞</option>
        <option value="feature">特征</option>
      </select></label
    >
    <label
      >标签来源<select v-model="mode" :disabled="store.busy">
        <option value="ids">稳定编号列表</option>
        <option v-if="axis === 'feature'" value="detection">检出率</option>
        <option v-if="axis === 'cell'" value="outliers">Isolation Forest</option>
        <option v-if="axis === 'cell'" value="polygon">输入多边形顶点</option>
        <option v-if="axis === 'cell'" value="lasso">图上套索圈选</option>
      </select></label
    >
    <label v-if="mode === 'ids'"
      >保留编号（每行一个）<textarea v-model="selected" :disabled="store.busy" />
    </label>
    <template v-if="mode === 'detection'"
      ><label
        >最低检出比例<input
          v-model.number="threshold"
          type="number"
          min="0"
          max="1"
          step=".01"
          :disabled="store.busy" /></label
      ><label>来源文件（空值为全部细胞）<input v-model="source" :disabled="store.busy" /></label
    ></template>
    <label v-if="mode === 'outliers'"
      >预期异常比例<input
        v-model.number="contamination"
        type="number"
        min=".001"
        max=".5"
        step=".01"
        :disabled="store.busy"
    /></label>
    <template v-if="mode === 'polygon' || mode === 'lasso'"
      ><label
        >横轴变量<input
          v-model="x"
          placeholder="feature:特征编号 或 obs:数值列"
          :disabled="store.busy" /></label
      ><label
        >纵轴变量<input
          v-model="y"
          placeholder="feature:特征编号 或 obs:数值列"
          :disabled="store.busy" /></label
      ><label v-if="mode === 'polygon'"
        >圈门顶点（每行 x,y）<textarea v-model="polygon" :disabled="store.busy" /></label
    ></template>
    <template v-if="mode === 'lasso'">
      <button class="preview" :disabled="store.busy || !x || !y" @click="drawGate">
        绘制圈选图
      </button>
      <p>
        在图上套索圈选后，点击保存标签。已选
        {{ selected.split('\n').filter(Boolean).length }} 个细胞。
      </p>
      <PlotView
        v-if="gateFigure"
        :figure="gateFigure"
        name="selection_gate"
        @selection="selection"
      />
    </template>
    <label
      >选择方向<select v-model="invert" :disabled="store.busy">
        <option :value="false">保留选中项</option>
        <option :value="true">保留未选中项</option>
      </select></label
    >
    <label
      >应用方式<select v-model="enabled" :disabled="store.busy">
        <option :value="true">保存标签并启用筛选</option>
        <option :value="false">只保存标签</option>
      </select></label
    >
    <button class="primary" :disabled="store.busy" @click="apply()">保存标签</button>
    <div v-for="(record, key) in labels" :key="key" class="actions">
      <span>{{ key }} · {{ record.enabled ? '已启用' : '未启用' }}</span
      ><button class="preview" :disabled="store.busy" @click="apply(String(key))">
        {{ record.enabled ? '关闭筛选' : '启用筛选' }}
      </button>
    </div>
  </section>
</template>
