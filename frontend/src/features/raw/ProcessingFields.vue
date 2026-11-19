<script setup lang="ts">
import MassListInput from '../../components/MassListInput.vue'
import ScientificInput from '../../components/ScientificInput.vue'
import { computed, useId } from 'vue'
import { useWorkspace } from '../../stores/workspace'
const props = defineProps<{
  fields: string[]
  disabled?: boolean
  referencePresets?: Record<string, number>
}>()
const model = defineModel<Record<string, unknown>>({ required: true })
const emit = defineEmits<{ edited: []; 'preset-selected': [name: string] }>()
const store = useWorkspace()
const referenceListId = useId()
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
function updateMass(key: string, value: number | null) {
  model.value[key] = value
  if (key === 'ref_mz') {
    const preset = Object.entries(props.referencePresets ?? {}).find(([, mass]) => mass === value)
    if (preset) emit('preset-selected', preset[0])
  }
  emit('edited')
}
function inputWidth(key: string) {
  if (['ref_mz', 'mz_min', 'mz_max'].includes(key)) return '112px'
  if (key === 'reference_mz' || key === 'reference_mode') return '220px'
  if (key === 'rt_range') return '82px'
  if (key === 'frame_range') return '88px'
  if (/snr|signal|intensity/.test(key)) return '86px'
  if (/frac|fraction/.test(key)) return '72px'
  if (key === 'n_jobs') return '64px'
  return '90px'
}
function rangeValue(key: string, index: number) {
  return (model.value[key] as number[] | null)?.[index] ?? ''
}
function rangeNumber(key: string, index: number, value: number | null) {
  const current = [...((model.value[key] as number[] | null) ?? [0, 0])]
  current[index] = value ?? 0
  model.value[key] = value === null ? null : current
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
  if (key === 'rt_range') return 's'
  return ''
}
</script>
<template>
  <div class="parameter-sections">
    <datalist v-if="referencePresets" :id="referenceListId">
      <option
        v-for="(mass, name) in referencePresets"
        :key="name"
        :value="String(mass)"
        :label="`${name} · ${mass.toFixed(4)}`"
      />
    </datalist>
    <details
      v-for="group in groups"
      :key="group.title"
      :class="{ 'parameter-section-plain': !group.title }"
      class="parameter-section"
      :open="true"
    >
      <summary>{{ group.title || '参数设置' }}</summary>
      <div class="parameter-controls">
        <label
          v-for="key in group.fields"
          :key="key"
          class="parameter-field"
          :style="{ '--compact-input': inputWidth(key) }"
          :class="{
            'parameter-field-full': key === 'reference_mz',
            'parameter-field-pair': key === 'rt_range' || key === 'frame_range',
            'parameter-field-mass': ['ref_mz', 'mz_min', 'mz_max'].includes(key),
          }"
        >
          <FieldLabel :name="key" :text="help(key)" />
          <span class="parameter-input">
            <template v-if="key === 'rt_range' || key === 'frame_range'">
              <ScientificInput
                v-for="i in [0, 1]"
                :key="i"
                :model-value="rangeValue(key, i)"
                :decimals="key === 'rt_range' ? 1 : 0"
                :aria-label="`${key}_${i}`"
                :disabled="disabled"
                @update:model-value="(value) => rangeNumber(key, i, value)"
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
            <MassListInput
              v-else-if="key === 'reference_mz'"
              v-model="model[key]"
              :aria-label="key"
              :disabled="disabled"
              placeholder="逗号分隔；空值使用主参考离子"
              @input="emit('edited')"
            />
            <ScientificInput
              v-else-if="['ref_mz', 'mz_min', 'mz_max'].includes(key)"
              :model-value="model[key]"
              :list="key === 'ref_mz' && referencePresets ? referenceListId : undefined"
              :decimals="4"
              :aria-label="key"
              :disabled="disabled"
              @update:model-value="(value) => updateMass(key, value)"
            />
            <ScientificInput
              v-else-if="/snr|signal|intensity/.test(key)"
              v-model="model[key]"
              scientific
              :aria-label="key"
              :disabled="disabled"
              @update:model-value="emit('edited')"
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
    </details>
  </div>
</template>
