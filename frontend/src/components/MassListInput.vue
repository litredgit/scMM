<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'
const props = defineProps<{ modelValue: unknown }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const element = ref<HTMLInputElement>()
let editing = false
function render() {
  if (!element.value || editing) return
  const raw = String(props.modelValue ?? '')
  element.value.value = raw
    .split(',')
    .map((part) => (part.trim() && Number.isFinite(Number(part)) ? Number(part).toFixed(4) : part))
    .join(', ')
}
function focus() {
  editing = true
  if (element.value) {
    element.value.value = String(props.modelValue ?? '')
    element.value.select()
  }
}
async function blur() {
  editing = false
  await nextTick()
  render()
}
onMounted(render)
watch(() => props.modelValue, render)
</script>
<template>
  <input
    ref="element"
    type="text"
    @focus="focus"
    @blur="blur"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>
