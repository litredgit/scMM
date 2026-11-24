<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useReadScope } from '../../api/readScope'
import type { AnalysisInfo, Figure } from '../../api/types'
import NumericVariable from '../../components/NumericVariable.vue'
import PlotView from '../../components/PlotView.vue'
import { colorScales, palettes } from '../../components/plotColors'
import { displayName } from '../../help/labels'
import { useWorkspace } from '../../stores/workspace'

const props = defineProps<{ info?: AnalysisInfo }>()
const store = useWorkspace()
const kind = ref('distribution')
const layer = ref('')
const metric = ref('detected_features')
const variable = ref('')
const groupKey = ref('')
const bins = ref(40)
const relative = ref(true)
const palette = ref('scMM')
const aggregate = ref('mean')
const colorscale = ref('RdBu')
const square = ref(false)
const figure = ref<Figure>()
const plotted = ref('')
const names: Record<string, string> = {
  sample_id: '样本',
  sample: '样本名',
  batch: '采集批次',
  group: '实验分组',
  source_file: '来源文件',
}
const groups = computed(() =>
  (kind.value === 'distribution'
    ? ['sample_id', 'sample', 'batch', 'group', 'source_file']
    : ['sample_id', 'sample', 'source_file']
  ).filter((column) => props.info?.observations[column]?.some((value) => value.trim())),
)
const context = () =>
  JSON.stringify([
    store.current?.workspace_id,
    store.project?.path,
    store.project?.dataset?.id,
    store.project?.dataset?.revision,
  ])
watch(context, () => {
  figure.value = undefined
  plotted.value = ''
})
watch(
  [() => props.info?.token[0], () => props.info?.original_layer],
  () => {
    layer.value = props.info?.original_layer ?? ''
  },
  { immediate: true },
)
watch(
  groups,
  (available) => {
    if (!available.includes(groupKey.value)) groupKey.value = available[0] ?? ''
  },
  { immediate: true },
)
const options = computed(() => ({
  kind: kind.value,
  group_key: groupKey.value,
  layer: layer.value || null,
  metric: metric.value === 'variable' ? variable.value : metric.value,
  bins: bins.value,
  relative: relative.value,
  palette: palette.value,
  aggregate: aggregate.value,
  colorscale: colorscale.value,
  square: square.value,
}))
const signature = computed(() => JSON.stringify(options.value))
const reads = useReadScope(() => [context(), signature.value])
const omitted = computed(() =>
  Number((figure.value?.layout.meta as { omitted?: number })?.omitted ?? 0),
)
async function draw() {
  const accept = reads.begin()
  const result = await store.inspect<{ value: Figure }>('/analysis/qc-plot', options.value, accept)
  if (result && accept()) {
    figure.value = result.value
    plotted.value = signature.value
  }
}
</script>

<template>
  <div class="preprocess-workspace">
    <section class="card qc-settings">
      <h2>QC 预览</h2>
      <fieldset class="field-grid" :disabled="store.busy">
        <label
          >图形
          <select v-model="kind" aria-label="图形">
            <option value="distribution">箱线图和直方图</option>
            <option value="sample_correlation">样本相关性热图</option>
          </select>
        </label>
        <label
          >{{ kind === 'distribution' ? '分组依据' : '样本标识' }}
          <select
            v-model="groupKey"
            :aria-label="kind === 'distribution' ? '分组依据' : '样本标识'"
          >
            <option v-for="key in groups" :key="key" :value="key">{{ names[key] }}</option>
          </select>
        </label>
        <label
          >QC 数据层
          <select v-model="layer">
            <option value="">当前矩阵</option>
            <option v-for="item in info?.layers ?? []" :key="item" :value="item">
              {{ displayName(item) }}
            </option>
          </select>
        </label>
        <template v-if="kind === 'distribution'">
          <label
            >指标
            <select v-model="metric">
              <option value="detected_features">检出特征数（> 0）</option>
              <option value="total_intensity">总强度</option>
              <option value="variable">参考离子、特征或细胞指标</option>
            </select>
          </label>
          <NumericVariable v-if="metric === 'variable'" v-model="variable" label="QC 数值变量" />
          <label
            >直方图纵轴
            <select v-model="relative">
              <option :value="true">组内比例</option>
              <option :value="false">观测数</option>
            </select>
          </label>
          <label>分箱数<input v-model.number="bins" type="number" min="5" max="200" /></label>
          <label
            >分类配色<select v-model="palette">
              <option v-for="item in palettes" :key="item">{{ item }}</option>
            </select></label
          >
        </template>
        <template v-else>
          <label
            >样本内聚合
            <select v-model="aggregate">
              <option value="mean">均值</option>
              <option value="median">中位数</option>
            </select>
          </label>
          <label
            >相关性
            <select v-model="square">
              <option :value="false">Pearson r（−1 到 1）</option>
              <option :value="true">Pearson R²（0 到 1）</option>
            </select>
          </label>
          <label
            >热图色标<select v-model="colorscale" aria-label="热图色标">
              <option v-for="item in colorScales" :key="item">{{ item }}</option>
            </select></label
          >
        </template>
      </fieldset>
      <p v-if="!groups.length" class="muted">请在数据检查与编辑中补充样本或批次信息。</p>
      <p v-else-if="kind === 'distribution'" class="muted">
        各组使用相同分箱。检出数和总强度基于所选层。
      </p>
      <p v-else class="muted">先聚合同一样本，再按特征计算样本之间的相关系数。</p>
      <button
        class="primary"
        :disabled="
          store.busy || !groupKey || (kind === 'distribution' && metric === 'variable' && !variable)
        "
        @click="draw"
      >
        生成 QC 图
      </button>
    </section>
    <section class="card">
      <h2>{{ kind === 'distribution' ? '分布预览' : '样本热图' }}</h2>
      <p v-if="figure && plotted !== signature" role="status">
        参数已更改，点击「生成 QC 图」更新。
      </p>
      <p v-if="omitted" class="muted">{{ omitted }} 个观测因标签或数值缺失未显示。</p>
      <PlotView v-if="figure" :figure="figure" name="qc-distributions" />
      <p v-else class="muted">选择数据层和分组后生成图形。</p>
    </section>
  </div>
</template>

<style scoped>
.qc-settings fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
</style>
