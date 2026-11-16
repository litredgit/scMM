<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspace } from '../../stores/workspace'
const props = defineProps<{ fields: string[]; disabled?: boolean }>()
const model = defineModel<Record<string, unknown>>({ required: true })
const emit = defineEmits<{ edited: [] }>()
const store = useWorkspace()
const groups = computed(() =>
  props.fields.includes('cell_snr') && props.fields.includes('ref_mz')
    ? [
        {
          title: '参考与提取范围',
          fields: ['ref_mz', 'mz_min', 'mz_max', 'rt_range', 'frame_range'],
        },
        { title: '细胞识别', fields: ['cell_snr', 'cell_min_signal'] },
        { title: '特征保留', fields: ['feature_snr_threshold', 'max_zero_frac'] },
      ]
    : [{ title: '', fields: props.fields }],
)
function rangeValue(key: string, index: number) {
  return (model.value[key] as number[] | null)?.[index] ?? ''
}
function rangeEdit(key: string, index: number, event: Event) {
  const text = (event.target as HTMLInputElement).value
  const current = [...((model.value[key] as number[] | null) ?? [0, 0])]
  current[index] = Number(text)
  model.value[key] = text === '' ? null : current
  emit('edited')
}
function help(key: string) {
  return store.configuration?.processing.find((p) => p.name === key)?.help ?? ''
}
function unit(key: string) {
  if (['ref_mz', 'reference_mz', 'mz_min', 'mz_max'].includes(key)) return 'm/z'
  if (key.includes('ppm')) return 'ppm'
  if (['baseline_filter_size', 'noise_window'].includes(key)) return '扫描数'
  if (key === 'max_zero_frac') return '0–1'
  return ''
}
</script>
<template>
  <div class="parameter-sections">
    <section v-for="(group, index) in groups" :key="index" class="parameter-section">
      <h4 v-if="group.title">{{ group.title }}</h4>
      <div class="parameter-controls">
        <label
          v-for="key in group.fields"
          :key="key"
          class="parameter-field"
          :class="{
            'parameter-field-full': key === 'reference_mz' || (key === 'ref_mz' && !!group.title),
          }"
        >
          <FieldLabel :name="key" :text="help(key)" />
          <span class="parameter-input">
            <template v-if="key === 'rt_range' || key === 'frame_range'">
              <input
                v-for="i in [0, 1]"
                :key="i"
                type="number"
                min="0"
                :step="key === 'frame_range' ? 1 : 'any'"
                :aria-label="`${key}_${i}`"
                :value="rangeValue(key, i)"
                :disabled="disabled"
                :placeholder="i === 0 ? '起点（空值全部）' : '终点'"
                @input="rangeEdit(key, i, $event)"
              />
            </template>
            <select
              v-else-if="key === 'reference_mode'"
              v-model="model[key]"
              :aria-label="key"
              :disabled="disabled"
              @change="emit('edited')"
            >
              <option value="union">任一参考离子满足</option>
              <option value="intersection">全部参考离子满足</option>
            </select>
            <input
              v-else-if="key === 'reference_mz'"
              v-model="model[key]"
              :aria-label="key"
              :disabled="disabled"
              placeholder="逗号分隔；空值使用主参考离子"
              @input="emit('edited')"
            />
            <input
              v-else
              v-model.number="model[key]"
              type="number"
              step="any"
              :aria-label="key"
              :disabled="disabled"
              @input="emit('edited')"
            />
            <span v-if="unit(key)" class="parameter-unit">{{ unit(key) }}</span>
          </span>
        </label>
      </div>
    </section>
  </div>
</template>
