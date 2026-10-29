<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { useReadScope } from '../api/readScope'
import TrashAction from './TrashAction.vue'
const props = defineProps<{ scope: 'snapshots' | 'previews' | 'exports'; refreshKey?: unknown }>()
const store = useWorkspace()
const rows = ref<
  { path: string; name: string; files: number | null; bytes: number | null; protection: string }[]
>([])
const opened = ref(false)
const loading = ref(false)
function toggle(event: Event) {
  opened.value = (event.target as HTMLDetailsElement).open
  void load()
}
const reads = useReadScope(() => [store.current?.workspace_id, store.project?.path, props.scope])
const titles = {
  snapshots: '保存记录与历史快照',
  previews: '细胞预览缓存',
  exports: '已导出的独立 H5AD',
}
async function load() {
  if (!opened.value || !store.project) return
  const accept = reads.begin()
  loading.value = true
  try {
    const value = await store.read<typeof rows.value>(
      `/saved/artifacts?scope=${props.scope}`,
      undefined,
      accept,
    )
    if (value && accept()) rows.value = value
  } finally {
    if (accept()) loading.value = false
  }
}
watch(
  () => [store.project?.path, props.refreshKey],
  () => {
    rows.value = []
    void load()
  },
)
</script>
<template>
  <details class="artifact-list" @toggle="toggle">
    <summary>{{ titles[scope] }}</summary>
    <p class="muted">
      当前引用、未保存数据来源及活动任务受到保护。先查看清理计划，再移入回收站；恢复请到项目首页的统一回收站。
    </p>
    <button class="preview" :disabled="store.busy || loading" @click="load">
      刷新{{ titles[scope] }}
    </button>
    <p v-if="loading">正在检查文件与引用…</p>
    <div v-else class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>文件 / 目录</th>
            <th>占用</th>
            <th>状态与操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.path">
            <td>
              {{ row.name }}<small class="path">{{ row.path }}</small>
            </td>
            <td>{{ row.bytes === null ? '—' : `${(row.bytes / 1048576).toFixed(2)} MiB` }}</td>
            <td>
              <span v-if="row.protection">{{ row.protection }}</span
              ><TrashAction v-else :path="row.path" :scope="scope" @changed="load" />
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length">暂无对应产物。</p>
    </div>
  </details>
</template>
