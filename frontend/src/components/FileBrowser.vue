<script setup lang="ts">
import { formatTime } from '../help/time'
import { computed, ref, watch } from 'vue'
import { request } from '../api/client'
import type { Directory, Root, FileEntry } from '../api/types'

const props = defineProps<{
  roots: Root[]
  kind: 'raw' | 'results'
  disabled?: boolean
  purpose?: 'import' | 'manage'
}>()
const emit = defineEmits<{ selected: [root: string, paths: string[]]; project: [path: string] }>()
const root = ref(props.roots[0]?.label ?? '')
const path = ref('.')
const includeInternal = ref(false)
const selectedInfo = ref<FileEntry>()
function date(value?: string | null) {
  return value ? formatTime(value) : '—'
}
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
      include_internal: String(includeInternal.value),
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
  selectedInfo.value =
    directory.value?.entries.find((e) => e.path === value) ??
    (directory.value?.latest?.path === value ? directory.value.latest : undefined)
  selection.value =
    props.kind === 'results'
      ? [value]
      : selection.value.includes(value)
        ? selection.value.filter((item) => item !== value)
        : [...selection.value, value]
  emit('selected', root.value, [...selection.value])
}
function clear() {
  selectedInfo.value = undefined
  selection.value = []
  emit('selected', root.value, [])
}
function remove(value: string) {
  if (selectedInfo.value?.path === value) selectedInfo.value = undefined
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
watch(includeInternal, () => void browse(directory.value?.path ?? '.'))
void browse('.')
defineExpose({ clear })
</script>

<template>
  <div class="file-browser">
    <form class="browser-controls" @submit.prevent="browse()">
      <label
        ><FieldLabel name="服务器存储" /><select
          v-model="root"
          aria-label="服务器存储"
          :disabled="disabled || loading"
        >
          <option v-for="item in roots" :key="item.label">{{ item.label }}</option>
        </select></label
      >
      <label class="grow"
        ><FieldLabel name="目录路径" /><input
          v-model="path"
          :disabled="disabled || loading"
          aria-label="目录路径"
      /></label>
      <button :disabled="disabled || loading">打开路径</button>
    </form>
    <p class="storage-path">{{ selectedRoot?.path }}</p>
    <label v-if="kind === 'results'" class="inline-check"
      ><input
        v-model="includeInternal"
        aria-label="显示内部快照、提取产物和缓存"
        type="checkbox"
        :disabled="disabled || loading" />显示内部快照、提取产物和缓存
      <HelpTip
        label="内部文件"
        text="默认收起当前/历史快照、恢复起点和处理缓存。完整恢复优先打开项目；高级浏览可查看内部文件，但删除仍须通过引用和任务检查。"
    /></label>
    <div v-if="kind === 'results' && directory?.context?.project_name" class="result-context">
      <strong>{{ directory.context.project_name }} · {{ directory.context.role }}</strong>
      <p>{{ directory.context.detail }} {{ directory.context.protection }}</p>
      <button
        v-if="purpose !== 'manage' && directory?.context?.project_path"
        :disabled="disabled"
        @click="emit('project', directory!.context!.project_path!)"
      >
        打开所属项目
      </button>
    </div>
    <div v-if="kind === 'results' && selectedInfo" class="latest-result" role="status">
      <strong>已选结果：{{ selectedInfo.name }}</strong>
      <HelpTip
        :text="`${selectedInfo.detail ?? ''} ${selectedInfo.protection ?? ''}`"
        label="结果用途"
      />
      <p>
        {{ selectedInfo.role
        }}{{ selectedInfo.project_name ? ` · ${selectedInfo.project_name}` : '' }} ·
        {{ date(selectedInfo.modified_at) }}（北京时间）
      </p>
      <button
        v-if="selectedInfo.project_path && purpose !== 'manage'"
        :disabled="disabled"
        @click="emit('project', selectedInfo!.project_path!)"
      >
        打开完整项目（推荐）
      </button>
    </div>
    <div
      v-if="kind === 'results' && purpose !== 'manage' && !selection.length && directory?.latest"
      class="latest-result"
    >
      <p>
        当前目录最近记录的可用矩阵：{{ directory.latest.name }} · {{ directory.latest.role }} ·
        {{ date(directory.latest.modified_at) }}（北京时间）。时间仅供参考，请核对所属项目和用途。
      </p>
      <button
        v-if="directory.latest.project_path"
        :disabled="disabled || loading"
        @click="emit('project', directory!.latest!.project_path!)"
      >
        打开所属完整项目（推荐）
      </button>
      <button :disabled="disabled || loading" @click="select(directory!.latest!.path)">
        选择此矩阵供导入检查
      </button>
    </div>
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
      <template v-else>
        <div v-for="item in directory.entries" :key="item.path" class="file-entry-row">
          <button
            type="button"
            class="file-entry"
            :class="{ selected: selection.includes(item.path) }"
            :disabled="disabled"
            @click="item.directory ? browse(item.path) : select(item.path)"
          >
            <span class="file-icon">{{ item.directory ? '▰' : '▤' }}</span>
            <span class="file-info"
              ><strong>{{ item.name }}</strong>
              <small v-if="kind === 'results'"
                >{{ item.role }}{{ item.project_name ? ` · ${item.project_name}` : '' }} ·
                {{ date(item.modified_at) }}（北京时间）</small
              >
            </span>
            <small>{{
              item.directory ? '打开目录 →' : `${((item.bytes ?? 0) / 1024 ** 2).toFixed(2)} MiB`
            }}</small>
            <span v-if="selection.includes(item.path)">✓</span>
          </button>
          <HelpTip
            v-if="kind === 'results'"
            :text="`${item.detail ?? ''} ${item.protection ?? ''} 完整路径：${selectedRoot?.path}/${item.path}`"
            :label="item.name"
          />
          <button
            v-if="purpose !== 'manage' && item.project_path && item.role === '项目（推荐打开）'"
            :disabled="disabled"
            @click="emit('project', item.project_path!)"
          >
            打开项目
          </button>
        </div>
      </template>
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
