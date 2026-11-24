<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useReadScope } from '../../api/readScope'
import { openWorkspaceCsv } from '../../api/csvExport'
import { useWorkspace } from '../../stores/workspace'
import DataTableView from '../../components/DataTable.vue'
import PlotView from '../../components/PlotView.vue'
import type { DataTable, Figure } from '../../api/types'

const props = defineProps<{ reportId: string }>()
const store = useWorkspace()
const report = ref<{ table: DataTable; figure: Figure | null; method: { version: string } }>()
const offset = ref(0)
const path = computed(() => `/methods/reports/${encodeURIComponent(props.reportId)}`)
const context = () => [store.current?.workspace_id, store.current?.revision, props.reportId]
const scope = useReadScope(context, () => void load())
async function load() {
  const accept = scope.begin()
  const value = await store.read<NonNullable<typeof report.value>>(
    `${path.value}?offset=${offset.value}`,
    undefined,
    accept,
  )
  if (accept()) report.value = value
}
watch(
  context,
  () => {
    report.value = undefined
    offset.value = 0
    void load()
  },
  { immediate: true },
)

function download() {
  const workspace = store.current?.workspace_id
  if (!workspace) return
  openWorkspaceCsv(`${props.reportId.replace(':', '-')}.csv`, `${path.value}?download=1`, {
    workspace,
    isCurrent: scope.begin(),
  })
}

function changePage(delta: number) {
  offset.value += delta
  void load()
}
</script>

<template>
  <template v-if="report">
    <div class="actions">
      <span class="muted">方法版本 {{ report.method.version }} · {{ report.table.total }} 行</span>
      <button class="download" :disabled="store.busy" @click="download">下载完整 CSV</button>
      <button v-if="offset" class="preview" @click="changePage(-200)">上一页</button>
      <button v-if="offset + 200 < report.table.total" class="preview" @click="changePage(200)">
        下一页
      </button>
    </div>
    <DataTableView :table="report.table" />
    <PlotView v-if="report.figure" :figure="report.figure" :name="reportId.replace(':', '-')" />
  </template>
  <button v-else class="preview" :disabled="store.busy" @click="load">读取方法报告</button>
</template>
