<script setup lang="ts">
import { resultTitles } from '../results'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import type { ResultName } from '../types'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import DataTableView from '../../../components/DataTable.vue'
const props = defineProps<{ name: ResultName; heading?: boolean }>()
const { tables, has, loadResult, store } = useAnalysisContext()
const router = useRouter()
const table = computed(() => tables.value[props.name])
const rowFilter = computed(
  () => (table.value as { row_filter?: string } | undefined)?.row_filter ?? 'all',
)
const offset = computed(() => table.value?.offset ?? 0)
const canReview = computed(
  () =>
    Boolean(store.project?.annotation?.sources.length) &&
    ['differential', 'markers'].includes(props.name),
)
async function reviewFeature(feature: string) {
  const revision = store.current?.revision
  const target = await store.read<{ source: string; feature: string }>(
    '/analysis/feature-review-target?' + new URLSearchParams({ feature }),
  )
  if (target && revision === store.current?.revision)
    await router.push({ path: '/annotation', query: target })
}
const negative = ref(false)
const shown = computed(() => {
  const table = tables.value[props.name]
  return table && props.name === 'markers' && !negative.value
    ? { ...table, rows: table.rows.filter((r) => r.weight === undefined || Number(r.weight) > 0) }
    : table
})
</script>
<template>
  <template v-if="has(name) && tables[name]"
    ><h3 v-if="heading">{{ resultTitles[name] }}</h3>
    <label v-if="name === 'differential'">
      结果范围
      <select
        aria-label="筛选差异结果"
        :value="rowFilter"
        :disabled="store.busy"
        @change="loadResult(name, 0, undefined, ($event.target as HTMLSelectElement).value)"
      >
        <option value="all">全部</option>
        <option value="finite_effect">有限 log₂FC</option>
        <option value="single_zero">单侧零</option>
        <option value="both_zero">双侧零</option>
        <option value="not_estimable">检验不可估计</option>
      </select>
    </label>
    <label v-if="name === 'markers' && table?.columns.includes('weight')"
      ><input type="checkbox" v-model="negative" />同时显示负权重</label
    >
    <div v-if="table && table.total > 200" class="actions">
      <button
        class="preview"
        :disabled="store.busy || offset === 0"
        @click="loadResult(name, offset - 200, undefined, rowFilter)"
      >
        上一页
      </button>
      <span>{{ offset + 1 }}–{{ offset + table.rows.length }} / {{ table.total }}</span>
      <button
        class="preview"
        :disabled="store.busy || offset + 200 >= table.total"
        @click="loadResult(name, offset + 200, undefined, rowFilter)"
      >
        下一页
      </button>
    </div>
    <DataTableView v-if="shown" :table="shown">
      <template v-if="canReview" #feature_id="{ value }">
        <button
          type="button"
          class="feature-review-link"
          :disabled="store.busy"
          :title="'查看测量峰 ' + value"
          @click="reviewFeature(String(value))"
        >
          {{ value }}
        </button>
      </template>
    </DataTableView>
  </template>
</template>

<style scoped>
.feature-review-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--teal);
  text-decoration: underline;
}
</style>
