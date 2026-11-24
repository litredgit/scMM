<script setup lang="ts">
import { ref, watch } from 'vue'
import { useReadScope } from '../api/readScope'
import { useWorkspace } from '../stores/workspace'

const props = defineProps<{ label: string; disabled?: boolean }>()
const model = defineModel<string>({ required: true })
const store = useWorkspace()
const query = ref('')
const options = ref<{ value: string; label: string }[]>([])
const context = () =>
  JSON.stringify([
    store.current?.workspace_id,
    store.project?.dataset?.id,
    store.project?.dataset?.revision,
  ])
const reads = useReadScope(
  () => [context(), query.value],
  () => void read(),
)
async function read() {
  const accept = reads.begin()
  const params = new URLSearchParams({ query: query.value, pool: 'false', embeddings: 'false' })
  const result = await store.read<{ options: typeof options.value }>(
    `/analysis/selection-axes?${params}`,
    undefined,
    accept,
  )
  if (accept() && result) options.value = result.options
}
watch([context, query], () => void read(), { immediate: true })
</script>

<template>
  <label>
    {{ props.label }}
    <input
      v-model="query"
      :aria-label="'搜索' + props.label"
      placeholder="搜索指标、特征 ID 或 m/z"
      :disabled="disabled"
    />
    <select v-model="model" :aria-label="props.label" :disabled="disabled">
      <option value="">选择数值变量</option>
      <option v-if="model && !options.some((item) => item.value === model)" :value="model">
        {{ model }}
      </option>
      <option v-for="item in options" :key="item.value" :value="item.value">
        {{ item.label }}
      </option>
    </select>
  </label>
</template>
