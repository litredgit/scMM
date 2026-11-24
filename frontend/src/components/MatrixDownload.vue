<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { request } from '../api/client'
import { workspaceBlob } from '../api/workspaceDownload'
import { openCsvExport } from '../api/csvExport'
const props = defineProps<{
  source: 'extracted' | 'current'
  batchPath?: string
  embedded?: boolean
  compact?: boolean
}>()
const store = useWorkspace()
const info = ref<{
  available: boolean
  reason?: string
  cells: number
  features: number
  samples: { id: string; name: string; label: string }[]
}>()
const labels = ref<Record<string, string>>({})
const infoState = ref<'loading' | 'ready' | 'failed'>('loading')
let generation = 0
watch(
  () => [store.current?.workspace_id, store.project?.path, props.batchPath],
  () => {
    generation++
    labels.value = {}
  },
  { flush: 'sync' },
)
async function loadInfo() {
  const token = ++generation
  info.value = undefined
  infoState.value = 'loading'
  const snapshot = store.current
  if (!snapshot || (!store.project?.dataset && !props.batchPath)) return
  const isCurrent = () =>
    token === generation &&
    store.current?.workspace_id === snapshot.workspace_id &&
    store.current?.revision === snapshot.revision
  try {
    const result = await request<NonNullable<typeof info.value>>(
      `/workspace/results/matrix?${new URLSearchParams({ source: props.source, ...(props.batchPath ? { batch_path: props.batchPath } : {}) })}`,
      { workspace: snapshot.workspace_id },
    )
    if (!isCurrent()) return
    info.value = result
    infoState.value = 'ready'
  } catch {
    if (isCurrent()) infoState.value = 'failed'
  }
}
watch(
  () => [
    store.current?.workspace_id,
    store.current?.revision,
    store.project?.path,
    props.batchPath,
  ],
  loadInfo,
  {
    immediate: true,
  },
)
function download() {
  const snapshot = store.current
  const metadata = info.value
  if (!snapshot || !metadata?.available) return
  const ids = new Set(metadata.samples.map((s) => s.id))
  const { source, batchPath } = props
  const isCurrent = () =>
    store.current?.workspace_id === snapshot.workspace_id &&
    store.current?.revision === snapshot.revision &&
    props.source === source &&
    props.batchPath === batchPath
  openCsvExport({
    filename: source === 'extracted' ? 'extracted-matrix.csv' : 'preprocessed-matrix.csv',
    isCurrent,
    samples: metadata.samples,
    labels: Object.fromEntries(Object.entries(labels.value).filter(([id]) => ids.has(id))),
    onLabels: (value) => {
      labels.value = value
    },
    load: (selectedLabels, signal) =>
      workspaceBlob('/results/matrix/download', {
        workspace: snapshot.workspace_id,
        method: 'POST',
        body: {
          revision: snapshot.revision,
          source,
          batch_path: batchPath ?? null,
          labels: selectedLabels,
        },
        signal,
        isCurrent,
      }),
  })
}
</script>
<template>
  <section
    v-if="store.project?.dataset || batchPath"
    :class="embedded ? 'matrix-download' : 'card'"
    aria-label="矩阵 CSV 下载"
  >
    <button class="download" :disabled="store.busy || !info?.available" @click="download">
      {{ source === 'extracted' ? '下载提取原始矩阵 CSV' : '下载预处理矩阵 CSV' }}
    </button>
    <p v-if="info?.available" v-show="!compact" class="muted">
      {{ info.cells }} 细胞 × {{ info.features }} 特征；{{
        source === 'extracted'
          ? batchPath
            ? '所选批次全部成功样本的完整提取矩阵'
            : '审核纳入后的完整原始强度'
          : '当前分支已应用预处理后的完整矩阵，不含降维坐标'
      }}。
    </p>
    <p v-else-if="infoState === 'loading'" class="muted" role="status">正在读取矩阵信息…</p>
    <div v-else-if="infoState === 'failed'" class="actions">
      <span role="status">未能读取矩阵信息。</span>
      <button class="preview" :disabled="store.busy" @click="loadInfo">重试读取</button>
    </div>
    <p v-else class="muted">{{ info?.reason || '当前矩阵不可下载。' }}</p>
    <p v-if="store.busy && info?.available" class="muted" role="status">请等待当前操作完成。</p>
  </section>
</template>
