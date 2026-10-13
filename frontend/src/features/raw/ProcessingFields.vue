<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useWorkspace } from '../../stores/workspace'
const props = defineProps<{ fields: string[]; disabled?: boolean }>()
const model = defineModel<Record<string, unknown>>({ required: true })
const emit = defineEmits<{ edited: [] }>()
const store = useWorkspace()
const element = ref<HTMLElement>()
const labelFont = ref('16px sans-serif'),
  inputFont = ref('16px sans-serif')
let context: CanvasRenderingContext2D | null = null
let observer: ResizeObserver | undefined
onMounted(() => {
  context = document.createElement('canvas').getContext('2d')
  const measure = () => {
    const label = element.value?.querySelector('.field-label')
    const input = element.value?.querySelector('input, select')
    if (label) labelFont.value = getComputedStyle(label).font
    if (input) inputFont.value = getComputedStyle(input).font
  }
  measure()
  observer = new ResizeObserver(measure)
  if (element.value) observer.observe(element.value)
})
onBeforeUnmount(() => observer?.disconnect())
function textWidth(value: string, font: string) {
  if (!context) return value.length * 8.5
  context.font = font
  return Math.ceil(context.measureText(value).width)
}
const groups = computed(() => {
  const result: string[][] = []
  for (const key of props.fields) {
    if (key === 'mz_max' && result.at(-1)?.[0] === 'mz_min') result.at(-1)!.push(key)
    else result.push([key])
  }
  return result
})
function help(key: string) {
  return store.configuration?.processing.find((p) => p.name === key)?.help ?? ''
}
function dimensions(key: string) {
  const value = key === 'reference_mode' ? 'intersection' : String(model.value[key] ?? '')
  const input = Math.max(100, Math.min(190, textWidth(value, inputFont.value) + 44))
  return {
    '--field-width': `${Math.max(input, textWidth(key, labelFont.value) + 32)}px`,
    '--input-width': `${input}px`,
  }
}
</script>
<template>
  <div ref="element" class="parameter-controls">
    <div
      v-for="group in groups"
      :key="group[0]"
      class="parameter-group"
      :class="{ 'parameter-group-wide': group.includes('reference_mz') }"
    >
      <label v-for="key in group" :key="key" class="parameter-field" :style="dimensions(key)">
        <FieldLabel :name="key" :text="help(key)" />
        <select
          v-if="key === 'reference_mode'"
          v-model="model[key]"
          :aria-label="key"
          :disabled="disabled"
          @change="emit('edited')"
        >
          <option>union</option>
          <option>intersection</option>
        </select>
        <input
          v-else-if="key === 'reference_mz'"
          v-model="model[key]"
          :aria-label="key"
          :disabled="disabled"
          placeholder="逗号分隔；空值使用 ref_mz"
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
      </label>
    </div>
  </div>
</template>
