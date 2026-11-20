<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { ionPath, type IonInfo, type IonTable, type IonView } from '../../api/ions'
import { useReadScope } from '../../api/readScope'
import DataTableView from '../../components/DataTable.vue'
const props = defineProps<{ views?: IonView[] }>()
const store = useWorkspace()
const info = ref<IonInfo>()
const sources = computed(() =>
  (props.views ?? info.value?.views ?? []).filter((view) => view.level === 'L2'),
)
const viewId = ref('')
const table = ref<IonTable>()
const offset = ref(0)
const reads = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  store.current?.revision,
  viewId.value,
  offset.value,
])
watch(
  () => [props.views, store.project?.path, store.current?.revision],
  async () => {
    if (props.views || !store.project) return
    const value = await store.read<IonInfo>(ionPath('info'))
    if (value) info.value = value
  },
  { immediate: true },
)
watch(
  sources,
  (items) => {
    if (!items.some((item) => item.id === viewId.value)) viewId.value = items[0]?.id ?? ''
  },
  { immediate: true },
)
watch(viewId, () => {
  offset.value = 0
  table.value = undefined
})
watch(
  () => [viewId.value, offset.value, store.current?.revision],
  async () => {
    if (!viewId.value) return
    const query = new URLSearchParams({
      kind: 'source_ec',
      version: viewId.value,
      offset: String(offset.value),
      limit: '50',
    })
    const value = await store.read<IonTable>(
      `${ionPath('table')}?${query}`,
      undefined,
      reads.begin(),
    )
    if (value) table.value = value
  },
  { immediate: true },
)
</script>

<template>
  <details v-if="sources.length" class="card compound-source">
    <summary>源 L2 离子组与定量映射</summary>
    <label class="field"
      >EC 来源
      <select v-model="viewId">
        <option v-for="item in sources" :key="item.id" :value="item.id">
          {{ item.id.slice(0, 8) }} · {{ item.cell_ids.length }} 观测 ×
          {{ item.variable_ids?.length }} EC
        </option>
      </select>
    </label>
    <p class="muted">中性质量适用于 EC。固定代表离子为可追溯定量来源，缺测表示不可量化。</p>
    <DataTableView v-if="table" :table="table.table" />
    <div v-if="table && table.total > 50" class="actions">
      <button :disabled="!offset" @click="offset -= 50">上一页</button>
      <span>{{ offset + 1 }}–{{ Math.min(offset + 50, table.total) }} / {{ table.total }}</span>
      <button :disabled="offset + 50 >= table.total" @click="offset += 50">下一页</button>
    </div>
  </details>
</template>
