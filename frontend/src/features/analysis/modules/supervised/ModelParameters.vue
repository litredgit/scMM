<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
const { train, logistic, lda, plsda, forest, store } = useAnalysisContext()
type Field = {
  key: string
  label: string
  help: string
  type?: 'number' | 'checkbox'
  options?: (string | null)[]
  nullable?: boolean
}
const fields: Record<string, Field[]> = {
  logistic: [
    { key: 'C', label: '正则化倒数', help: 'C：正数；越小约束越强。', type: 'number' },
    {
      key: 'solver',
      label: '求解器',
      help: 'solver：L1 仅支持 liblinear/saga；elasticnet 仅支持 saga。',
      options: ['lbfgs', 'liblinear', 'newton-cg', 'newton-cholesky', 'sag', 'saga'],
    },
    {
      key: 'penalty',
      label: '正则化方式',
      help: 'penalty：不正则化时 C 保持 1。',
      options: ['l2', 'l1', 'elasticnet', null],
    },
    {
      key: 'l1_ratio',
      label: '混合正则化比例',
      help: 'l1_ratio：仅 elasticnet 使用，须在 0–1 内。',
      type: 'number',
      nullable: true,
    },
    {
      key: 'class_weight',
      label: '类别权重',
      help: 'class_weight：balanced 按训练类别频率调整。',
      options: ['balanced', null],
    },
    { key: 'fit_intercept', label: '拟合截距', help: 'fit_intercept', type: 'checkbox' },
    { key: 'tol', label: '收敛容差', help: 'tol：正数。', type: 'number' },
    { key: 'max_iter', label: '最大迭代次数', help: 'max_iter：正整数。', type: 'number' },
  ],
  lda: [
    { key: 'shrinkage', label: '协方差收缩', help: 'shrinkage：留空、auto 或 0–1；svd 仅可留空。' },
    {
      key: 'n_components',
      label: '潜变量数',
      help: 'n_components：留空使用上限；不超过特征数与类别数减一。',
      type: 'number',
      nullable: true,
    },
    { key: 'tol', label: '奇异值容差', help: 'tol：svd 使用的正数容差。', type: 'number' },
    { key: 'store_covariance', label: '保留协方差', help: 'store_covariance', type: 'checkbox' },
  ],
  plsda: [
    {
      key: 'n_components',
      label: '潜变量数',
      help: 'n_components：正整数；按每个训练折的细胞/特征数限制，报告记录实际值。',
      type: 'number',
    },
    { key: 'max_iter', label: '最大迭代次数', help: 'max_iter：正整数。', type: 'number' },
  ],
  random_forest: [
    { key: 'n_estimators', label: '决策树数', help: 'n_estimators：1–10000。', type: 'number' },
    {
      key: 'max_depth',
      label: '最大树深',
      help: 'max_depth：留空不限，或正整数。',
      type: 'number',
      nullable: true,
    },
    {
      key: 'min_samples_split',
      label: '分裂最小样本数',
      help: 'min_samples_split：整数至少 2，或 (0,1] 小数比例；2 与 0.2 含义不同。',
    },
    {
      key: 'min_samples_leaf',
      label: '叶节点最小样本数',
      help: 'min_samples_leaf：正整数，或 (0,1) 小数比例。',
    },
    {
      key: 'max_features',
      label: '分裂候选特征',
      help: 'max_features：sqrt、log2、留空全部、正整数个数或 (0,1] 小数比例。',
    },
    {
      key: 'bootstrap',
      label: '有放回抽样',
      help: 'bootstrap：启用才可设置抽样数量。',
      type: 'checkbox',
    },
    {
      key: 'max_samples',
      label: '每棵树抽样量',
      help: 'max_samples：留空使用全部、正整数或 (0,1] 小数比例；须适用于最小训练折。',
    },
    {
      key: 'criterion',
      label: '分裂准则',
      help: 'criterion',
      options: ['gini', 'entropy', 'log_loss'],
    },
    {
      key: 'class_weight',
      label: '类别权重',
      help: 'class_weight',
      options: ['balanced', 'balanced_subsample', null],
    },
  ],
}
const values = computed(
  () =>
    ({ logistic, lda, plsda, random_forest: forest })[
      train.model as 'logistic' | 'lda' | 'plsda' | 'random_forest'
    ] as unknown as Record<string, unknown>,
)
function update(field: Field, event: Event) {
  const input = event.target as HTMLInputElement
  values.value[field.key] =
    field.type === 'checkbox'
      ? input.checked
      : field.type === 'number'
        ? input.value === '' && field.nullable
          ? null
          : input.value === ''
            ? ''
            : Number(input.value)
        : input.value
}
</script>
<template>
  <div class="field-grid" aria-label="模型超参数">
    <label v-for="field in fields[train.model]" :key="field.key" :title="field.help">
      {{ field.label }}
      <select
        v-if="field.options"
        v-model="values[field.key]"
        :aria-label="`${train.model} ${field.key}`"
        :disabled="store.busy"
      >
        <option v-for="choice in field.options" :key="String(choice)" :value="choice">
          {{ choice ?? '不使用' }}
        </option>
      </select>
      <input
        v-else
        :type="field.type ?? 'text'"
        :value="values[field.key] ?? ''"
        :checked="values[field.key] === true"
        :aria-label="`${train.model} ${field.key}`"
        :step="field.type === 'number' ? 'any' : undefined"
        :disabled="store.busy"
        @input="update(field, $event)"
      />
    </label>
  </div>
</template>
