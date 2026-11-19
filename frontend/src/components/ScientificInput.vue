<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'
const props = defineProps<{ modelValue: unknown; scientific?: boolean; decimals?: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()
const element = ref<HTMLInputElement>()
let editing = false
let invalid = ''
function render() {
  if (!element.value || editing) return
  const raw = props.modelValue
  const value = Number(raw)
  let text = raw == null || raw === '' ? '' : String(raw)
  if (raw != null && raw !== '' && Number.isFinite(value)) {
    text = props.scientific
      ? value.toExponential(1)
      : props.decimals == null
        ? String(value)
        : value.toFixed(props.decimals)
  }
  element.value.value = invalid || text
}
function focus() {
  editing = true
  if (element.value) {
    element.value.value = invalid || String(props.modelValue ?? '')
    element.value.select()
  }
}
function commit(event: Event) {
  const input = event.target as HTMLInputElement
  const value = input.value.trim() === '' ? null : Number(input.value)
  if (value !== null && !Number.isFinite(value)) {
    invalid = input.value
    emit('update:modelValue', Number.NaN)
    input.setCustomValidity('请输入有限数值。')
    input.reportValidity()
    return
  }
  invalid = ''
  input.setCustomValidity('')
  emit('update:modelValue', value)
}
async function blur() {
  editing = false
  await nextTick()
  render()
}
onMounted(render)
watch(
  () => props.modelValue,
  (value) => {
    if (value == null || Number.isFinite(Number(value))) {
      invalid = ''
      element.value?.setCustomValidity('')
    }
    render()
  },
)
watch(() => [props.scientific, props.decimals], render)
</script>
<template>
  <input
    ref="element"
    type="text"
    inputmode="decimal"
    @focus="focus"
    @blur="blur"
    @change="commit"
  />
</template>
