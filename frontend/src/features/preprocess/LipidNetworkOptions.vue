<script setup lang="ts">
import type { LipidInfo } from './lipids'
export interface NetworkOptions {
  method: string
  support_all: number
  support_joint: number
  min_joint_cells: number
  plot_threshold: number
  consensus_fraction: number
  min_support_samples: number
  condition_field: string
  samples: string[]
  conditions: string[]
  molecule_layer: string
}
const options = defineModel<NetworkOptions>({ required: true })
defineProps<{ info?: LipidInfo }>()
const fields = [
  { key: 'support_all', help: '全细胞相关（保留零值）的注释支持阈值。', max: 1, min: 0 },
  {
    key: 'support_joint',
    help: '共同检出细胞的注释支持阈值；需与全细胞阈值同时满足。',
    max: 1,
    min: 0,
  },
  { key: 'min_joint_cells', help: '每对特征、每样本最低共同检出数；不足属于不可评估。', min: 2 },
  {
    key: 'plot_threshold',
    help: '绘图要求全细胞 |ρ| 达到此值；绘图边不自动支持注释。',
    max: 1,
    min: 0,
  },
  { key: 'consensus_fraction', help: '同条件可评估样本中至少此比例支持。', max: 1, min: 0 },
  { key: 'min_support_samples', help: '同条件至少此数量的样本支持才属于重复支持。', min: 2 },
] as const
</script>
<template>
  <details class="card">
    <summary>相关性辅助注释与网络 · 高级参数</summary>
    <p class="muted">
      按
      {{ info?.sample_field || '单样本' }}
      分开计算；未选条件字段时仅提供逐样本结果。初始阈值尚需真实数据检查。
    </p>
    <div class="field-grid">
      <label
        ><FieldLabel name="method" text="Spearman 对每个样本内的强度排序；Pearson 计算线性相关。" />
        <select v-model="options.method" aria-label="网络 method">
          <option value="spearman">Spearman</option>
          <option value="pearson">Pearson</option>
        </select>
      </label>
      <label
        ><FieldLabel
          name="molecule_layer"
          text="默认从所选原始强度层的完整特征集合计算 total，不随筛选改变分母；已有层必须未插补且为强度。"
        />
        <select v-model="options.molecule_layer" aria-label="molecule_layer">
          <option value="total">total（完整原始特征集合派生）</option>
          <option v-for="layer in info?.molecule_layers" :key="layer" :value="layer">
            {{ layer }}
          </option>
        </select>
      </label>
      <label v-for="field in fields" :key="field.key"
        ><FieldLabel :name="field.key" :text="field.help" /><input
          v-model.number="options[field.key]"
          :aria-label="field.key"
          type="number"
          :min="field.min"
          :max="'max' in field ? field.max : undefined"
          :step="'max' in field ? 'any' : 1"
      /></label>
      <label
        ><FieldLabel
          name="condition_field"
          text="明确选择同条件重复所依据的样本级字段；不推断处理组。同一样本内值须唯一且不缺失。"
        />
        <select
          v-model="options.condition_field"
          aria-label="condition_field"
          @change="options.conditions = []"
        >
          <option value="">未设置（逐样本）</option>
          <option v-for="field in info?.condition_fields" :key="field" :value="field">
            {{ field }}
          </option>
        </select>
      </label>
      <label
        ><FieldLabel name="samples" text="留空为全部样本；不会把不同样本的细胞混合。" /><select
          v-model="options.samples"
          aria-label="网络 samples"
          multiple
        >
          <option v-for="sample in info?.samples" :key="sample" :value="sample">
            {{ sample }}
          </option>
        </select></label
      >
      <label v-if="options.condition_field"
        ><FieldLabel name="conditions" text="留空为全部条件；共识只在同条件内部判断。" /><select
          v-model="options.conditions"
          aria-label="网络 conditions"
          multiple
        >
          <option
            v-for="condition in info?.condition_values[options.condition_field]"
            :key="condition"
            :value="condition"
          >
            {{ condition }}
          </option>
        </select></label
      >
    </div>
    <p class="muted">
      辅助证据、同位素比例及 m/z 注释网络共用上方 intensity_layer。不插补，不修改当前矩阵。
    </p>
  </details>
</template>
