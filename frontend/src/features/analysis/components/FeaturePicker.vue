<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import { useViewState } from '../../../api/viewState'
import { useReadScope } from '../../../api/readScope'
const selected = defineModel<string[]>({ required: true })
const store = useWorkspace()
const query = ref(''),
  sort = ref('mz'),
  descending = ref(false),
  offset = ref(0)
const rows = ref<{ value: string; label: string }[]>([]),
  total = ref(0)
const labels = ref<Record<string, string>>({})
const loading = ref(false)
const limit = 40
let generation = 0
const context = computed(() =>
  JSON.stringify([
    store.current?.workspace_id,
    store.project?.dataset?.id,
    store.project?.dataset?.revision,
  ]),
)
const reads = useReadScope(
  () => [context.value, query.value, sort.value, descending.value, offset.value],
  () => void load(),
)
async function load() {
  const token = ++generation,
    identity = context.value
  const ticket = reads.begin()
  const accept = () => ticket() && token === generation && identity === context.value
  if (!accept()) return
  loading.value = true
  try {
    const params = new URLSearchParams({
      query: query.value,
      sort: sort.value,
      descending: String(descending.value),
      offset: String(offset.value),
      limit: String(limit),
    })
    const result = await store.read<{ rows: typeof rows.value; total: number }>(
      `/analysis/features?${params}`,
      undefined,
      accept,
    )
    if (result && accept()) {
      rows.value = result.rows
      total.value = result.total
      for (const row of result.rows) labels.value[row.value] = row.label
    }
  } finally {
    if (accept()) loading.value = false
  }
}
watch(
  [query, sort, descending, context],
  () => {
    offset.value = 0
    void load()
  },
  { immediate: true },
)
watch(offset, () => void load())
watch(context, () => {
  labels.value = {}
  rows.value = []
})
function toggle(id: string) {
  if (selected.value.includes(id)) selected.value = selected.value.filter((x) => x !== id)
  else if (selected.value.length < 12) selected.value = [...selected.value, id]
}
function move(index: number, delta: number) {
  const next = [...selected.value],
    target = index + delta
  if (target < 0 || target >= next.length) return
  next.splice(target, 0, next.splice(index, 1)[0]!)
  selected.value = next
}
useViewState('violin-picker', { query, sort, descending, offset, labels })
</script>
<template>
  <section class="feature-picker" aria-label="小提琴特征选择">
    <h3>选择小提琴特征</h3>
    <p class="muted">点击火山图中的点，或搜索后勾选；最多 12 个，完成选择后点击绘图。</p>
    <div class="field-grid">
      <label class="field"
        >搜索特征<input
          v-model="query"
          aria-label="小提琴搜索特征"
          placeholder="特征 ID、m/z、注释名称"
      /></label>
      <label class="field"
        >排序<select v-model="sort" aria-label="小提琴特征排序">
          <option value="mz">m/z</option>
          <option value="name">特征 ID</option>
          <option value="mean">平均强度</option>
          <option value="detection">检出比例</option>
        </select></label
      >
      <label class="field"
        >方向<select v-model="descending">
          <option :value="false">升序</option>
          <option :value="true">降序</option>
        </select></label
      >
    </div>
    <p role="status">
      已选 {{ selected.length }} / 12 个特征{{
        selected.length === 12 ? '，已达上限；移除后可继续选择' : ''
      }}
    </p>
    <ol class="selected-features">
      <li v-for="(id, i) in selected" :key="id">
        <span>{{ labels[id] || id }}</span>
        <button
          :aria-label="`上移特征 ${id}`"
          :disabled="i === 0 || store.busy"
          @click="move(i, -1)"
        >
          ↑
        </button>
        <button
          :aria-label="`下移特征 ${id}`"
          :disabled="i === selected.length - 1 || store.busy"
          @click="move(i, 1)"
        >
          ↓
        </button>
        <button :aria-label="`移除特征 ${id}`" :disabled="store.busy" @click="toggle(id)">
          移除
        </button>
      </li>
    </ol>
    <button class="restore" :disabled="!selected.length || store.busy" @click="selected = []">
      清空已选特征
    </button>
    <div class="feature-choices" :aria-busy="loading">
      <label v-for="row in rows" :key="row.value"
        ><input
          type="checkbox"
          :aria-label="`选择小提琴特征 ${row.value}`"
          :checked="selected.includes(row.value)"
          :disabled="store.busy || (!selected.includes(row.value) && selected.length >= 12)"
          @change="toggle(row.value)"
        />{{ row.label }}</label
      >
      <p v-if="!rows.length">{{ loading ? '正在查找特征…' : '没有符合条件的特征' }}</p>
    </div>
    <div class="actions">
      <button :disabled="offset === 0 || loading" @click="offset -= limit">上一页可选特征</button
      ><span>{{ total ? offset + 1 : 0 }}–{{ Math.min(offset + limit, total) }} / {{ total }}</span
      ><button :disabled="offset + limit >= total || loading" @click="offset += limit">
        下一页可选特征
      </button>
    </div>
  </section>
</template>
<style scoped>
.feature-picker {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  margin: 20px 0;
}
.feature-choices {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 8px;
  max-height: 280px;
  overflow: auto;
  margin: 14px 0;
}
.feature-choices label {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  overflow-wrap: anywhere;
  padding: 6px;
  background: #f8fafc;
}
.feature-choices input {
  min-height: 0;
  flex-shrink: 0;
}
.selected-features {
  padding-left: 22px;
}
.selected-features li {
  margin: 8px 0;
  overflow-wrap: anywhere;
}
.selected-features button {
  min-height: 30px;
  padding: 2px 8px;
  margin-left: 6px;
}
</style>
