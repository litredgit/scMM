<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { useReadScope } from '../api/readScope'
const props = defineProps<{
  path: string
  root?: string
  scope?: 'snapshots' | 'previews' | 'exports' | 'batches'
  disabled?: boolean
}>()
const emit = defineEmits<{ changed: [] }>()
const store = useWorkspace()
const plan = ref<{ token: string; path: string; files: number; bytes: number }>()
const reads = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  props.path,
  props.root,
  props.scope,
])
watch(
  () => [props.path, props.root, props.scope, store.current?.revision],
  () => {
    plan.value = undefined
  },
)
async function inspect() {
  const accept = reads.begin()
  const value = await store.inspect<NonNullable<typeof plan.value>>(
    '/saved/plan',
    {
      root: props.root ?? '项目结果',
      path: props.path,
      scope: props.scope,
    },
    accept,
  )
  if (accept()) plan.value = value
}
async function move() {
  if (!plan.value) return
  const token = plan.value.token
  const accept = reads.begin()
  plan.value = undefined
  const result = await store.inspect('/saved/move', { token }, accept)
  if (result && accept()) {
    store.notice = '所选内容已移入共享回收区，尚未释放磁盘空间。'
    emit('changed')
  }
}
</script>
<template>
  <span class="trash-action">
    <button class="danger" :disabled="store.busy || disabled || !path" @click="inspect">
      移入回收站
    </button>
    <span v-if="plan" class="cleanup-review" role="status">
      <span
        >{{ plan.path }} · {{ plan.files }} 文件 · {{ (plan.bytes / 1048576).toFixed(2) }} MiB</span
      >
      <button class="danger" :disabled="store.busy" @click="move">执行移入回收站</button>
      <button :disabled="store.busy" @click="plan = undefined">收起计划</button>
    </span>
  </span>
</template>
