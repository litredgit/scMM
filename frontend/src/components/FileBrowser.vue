<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { request } from '../api/client'
import type { Directory, Root } from '../api/types'

const props = defineProps<{ roots: Root[]; kind: 'raw' | 'results'; disabled?: boolean }>()
const emit = defineEmits<{ selected: [root: string, paths: string[]] }>()
const root = ref(props.roots[0]?.label ?? '')
const path = ref('.')
const search = ref('')
const directory = ref<Directory | null>(null)
const selection = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const page = ref(0)
const selectedRoot = computed(() => props.roots.find((item) => item.label === root.value))
let generation = 0
async function browse(target = path.value, offset = 0) {
  if (!root.value) return
  const ticket = ++generation
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({
      root: root.value,
      path: target,
      kind: props.kind,
      search: search.value,
      offset: String(offset),
    })
    const result = await request<Directory>(`/storage/entries?${query}`)
    if (ticket !== generation) return
    directory.value = result
    path.value = result.path
    page.value = offset
  } catch (cause) {
    if (ticket === generation) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (ticket === generation) loading.value = false
  }
}
function select(value: string) {
  selection.value =
    props.kind === 'results'
      ? [value]
      : selection.value.includes(value)
        ? selection.value.filter((item) => item !== value)
        : [...selection.value, value]
  emit('selected', root.value, [...selection.value])
}
function clear() {
  selection.value = []
  emit('selected', root.value, [])
}
function remove(value: string) {
  selection.value = selection.value.filter((path) => path !== value)
  emit('selected', root.value, [...selection.value])
}
watch(root, () => {
  clear()
  path.value = '.'
  directory.value = null
  void browse('.')
})
watch(
  () => props.roots,
  () => {
    if (!root.value && props.roots[0]) root.value = props.roots[0].label
  },
  { immediate: true },
)
void browse('.')
defineExpose({ clear })
</script>

<template>
  <div class="file-browser">
    <form class="browser-controls" @submit.prevent="browse()">
      <label
        >服务器存储<select v-model="root" aria-label="服务器存储" :disabled="disabled || loading">
          <option v-for="item in roots" :key="item.label">{{ item.label }}</option>
        </select></label
      >
      <label class="grow"
        >目录路径<input v-model="path" :disabled="disabled || loading" aria-label="目录路径"
      /></label>
      <button :disabled="disabled || loading">打开路径</button>
    </form>
    <p class="storage-path">{{ selectedRoot?.path }}</p>
    <div class="browser-toolbar">
      <button
        type="button"
        :disabled="disabled || loading || !directory?.parent"
        @click="browse(directory!.parent!)"
      >
        ↑ 上级目录
      </button>
      <form class="actions" @submit.prevent="browse(directory?.path ?? '.')">
        <input v-model="search" aria-label="搜索文件" placeholder="搜索文件或目录" /><button
          :disabled="disabled || loading"
        >
          搜索
        </button>
      </form>
      <button
        v-if="kind === 'results'"
        type="button"
        :disabled="disabled || loading || !directory"
        @click="select(directory!.path)"
      >
        选择当前结果目录
      </button>
    </div>
    <p v-if="error" role="alert" class="inline-error">{{ error }}</p>
    <div class="file-entries" :aria-busy="loading">
      <p v-if="loading" role="status" class="muted">正在读取目录…</p>
      <p v-else-if="!directory?.entries.length" class="muted">
        此目录中没有匹配的{{ kind === 'raw' ? '原始文件' : '结果文件' }}。
      </p>
      <template v-else
        ><button
          v-for="item in directory.entries"
          :key="item.path"
          type="button"
          class="file-entry"
          :class="{ selected: selection.includes(item.path) }"
          :disabled="disabled"
          @click="item.directory ? browse(item.path) : select(item.path)"
        >
          <span class="file-icon">{{ item.directory ? '▰' : '▤' }}</span
          ><span class="grow">{{ item.name }}</span
          ><small>{{
            item.directory ? '打开目录 →' : `${((item.bytes ?? 0) / 1024 ** 2).toFixed(2)} MB`
          }}</small
          ><span v-if="selection.includes(item.path)">✓</span>
        </button></template
      >
    </div>
    <div v-if="directory && directory.total > 200" class="actions">
      <button
        type="button"
        :disabled="disabled || loading || page === 0"
        @click="browse(directory!.path, page - 200)"
      >
        上一页</button
      ><span
        >{{ page + 1 }}–{{ Math.min(page + 200, directory.total) }} / {{ directory.total }}</span
      ><button
        type="button"
        :disabled="disabled || loading || page + 200 >= directory.total"
        @click="browse(directory!.path, page + 200)"
      >
        下一页
      </button>
    </div>
    <div class="selection-list">
      <span>已选 {{ selection.length }} 项</span
      ><button v-if="selection.length" type="button" :disabled="disabled" @click="clear">
        清空选择
      </button>
      <ul>
        <li v-for="item in selection" :key="item">
          {{ item
          }}<button
            type="button"
            :disabled="disabled"
            @click="remove(item)"
            :aria-label="`移除 ${item}`"
          >
            ×
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
