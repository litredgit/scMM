<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { workspaceBlob, saveBlob } from '../api/workspaceDownload'
const props = defineProps<{ source: 'extracted' | 'current' }>()
const store = useWorkspace()
const info = ref<{
  available: boolean
  reason?: string
  cells: number
  features: number
  samples: { id: string; name: string; label: string }[]
}>()
const labels = ref<Record<string, string>>({})
let generation = 0
watch(
  () => [store.current?.workspace_id, store.project?.path],
  () => {
    labels.value = {}
  },
  { flush: 'sync' },
)
watch(
  () => [store.current?.workspace_id, store.current?.revision, store.project?.path],
  async () => {
    const token = ++generation
    info.value = undefined
    if (!store.project?.dataset) return
    const result = await store.read<NonNullable<typeof info.value>>(
      `/results/matrix?source=${props.source}`,
    )
    if (token === generation) info.value = result
  },
  { immediate: true },
)
async function download() {
  const snapshot = store.current
  const metadata = info.value
  if (!snapshot || !metadata?.available) return
  await store.run(async (scope) => {
    const ids = new Set(metadata.samples.map((s) => s.id))
    const blob = await workspaceBlob('/results/matrix/download', {
      workspace: snapshot.workspace_id,
      method: 'POST',
      body: {
        revision: snapshot.revision,
        source: props.source,
        labels: Object.fromEntries(Object.entries(labels.value).filter(([id]) => ids.has(id))),
      },
      isCurrent: () =>
        scope.isCurrent() &&
        store.current?.workspace_id === snapshot.workspace_id &&
        store.current?.revision === snapshot.revision,
    })
    saveBlob(
      blob,
      props.source === 'extracted' ? 'extracted-matrix.csv' : 'preprocessed-matrix.csv',
    )
  })
}
</script>
<template>
  <section v-if="store.project?.dataset" aria-label="矩阵 CSV 下载">
    <button class="export" :disabled="store.busy || !info?.available" @click="download">
      {{ source === 'extracted' ? '下载提取原始矩阵 CSV' : '下载预处理矩阵 CSV' }}
    </button>
    <p v-if="info?.available" class="muted">
      {{ info.cells }} 细胞 × {{ info.features }} 特征；{{
        source === 'extracted'
          ? '审核纳入后的完整原始强度'
          : '当前分支已应用预处理后的完整矩阵，不含降维坐标'
      }}。
    </p>
    <p v-else-if="info?.reason" class="muted">{{ info.reason }}</p>
    <details v-if="info?.available">
      <summary>CSV 标签设置</summary>
      <p class="muted">Label 默认使用样本名；修改仅影响本入口下载，可将多个样本设为同一标签。</p>
      <label v-for="sample in info.samples" :key="sample.id">
        {{ sample.name }}
        <input
          :aria-label="`CSV 标签 ${sample.name}`"
          :value="labels[sample.id] ?? sample.label"
          @input="labels[sample.id] = ($event.target as HTMLInputElement).value"
        />
      </label>
    </details>
  </section>
</template>
