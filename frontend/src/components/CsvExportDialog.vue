<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { csvExport } from '../api/csvExport'
import { csvOffsets, csvRecords, zipCsvTables } from '../api/csvPreview'
import { saveBlob } from '../api/workspaceDownload'
import ExportDialog from './ExportDialog.vue'

const dialog = ref<InstanceType<typeof ExportDialog>>()
const filename = ref('')
const labels = ref<Record<string, string>>({})
const mode = ref('quick')
const busy = ref(false)
const error = ref('')
const artifact = shallowRef<Blob>()
const preview = shallowRef<Blob>()
const tables = shallowRef<Awaited<ReturnType<typeof zipCsvTables>>>([])
const table = ref(0)
const offsets = shallowRef<number[]>([])
const columns = shallowRef<string[]>([])
const rows = shallowRef<string[][]>([])
const rowPage = ref(1)
const columnPage = ref(1)
const rowCount = computed(() => Math.max(0, offsets.value.length - 2))
const rowPages = computed(() => Math.max(1, Math.ceil(rowCount.value / 20)))
const columnPages = computed(() => Math.max(1, Math.ceil(columns.value.length / 30)))
const firstColumn = computed(() => (columnPage.value - 1) * 30)
const visibleColumns = computed(() =>
  columns.value.slice(firstColumn.value, firstColumn.value + 30),
)
const isStale = () => csvExport.value?.isCurrent?.() === false
const stale = computed(isStale)
let controller: AbortController | undefined
let pageGeneration = 0

function stop() {
  controller?.abort()
  controller = undefined
  pageGeneration++
  busy.value = false
}
function resetTable() {
  preview.value = undefined
  offsets.value = []
  columns.value = []
  rows.value = []
  rowPage.value = 1
  columnPage.value = 1
}
function resetArtifact() {
  stop()
  resetTable()
  artifact.value = undefined
  tables.value = []
  table.value = 0
  error.value = ''
}
watch(stale, (value) => {
  if (value) resetArtifact()
})

watch(
  csvExport,
  (request) => {
    resetArtifact()
    if (!request) return
    filename.value = request.filename
    labels.value = { ...request.labels }
    mode.value = 'quick'
    dialog.value?.open()
  },
  { flush: 'post' },
)

async function readRows() {
  const blob = preview.value
  const token = ++pageGeneration
  if (!blob) return
  rows.value = []
  const first = 1 + (rowPage.value - 1) * 20
  const last = Math.min(first + 20, offsets.value.length - 1)
  const text = await blob.slice(offsets.value[first], offsets.value[last]).text()
  if (token === pageGeneration) rows.value = csvRecords(text)
}
watch(rowPage, () => void readRows())

function pageNumber(event: Event, pages: number) {
  const input = event.target as HTMLInputElement
  const page = Math.max(1, Math.min(pages, Math.trunc(Number(input.value)) || 1))
  input.value = String(page)
  return page
}

async function run(action: (signal: AbortSignal) => Promise<void>) {
  stop()
  const operation = new AbortController()
  controller = operation
  busy.value = true
  error.value = ''
  try {
    if (isStale()) throw new Error('导出来源已改变，请重新打开导出窗口。')
    await action(operation.signal)
  } catch (cause) {
    if (!operation.signal.aborted && !isStale())
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (controller === operation) busy.value = false
  }
}

async function load(signal: AbortSignal) {
  const request = csvExport.value!
  const value = artifact.value ?? (await request.load({ ...labels.value }, signal))
  signal.throwIfAborted()
  if (isStale()) throw new Error('导出来源已改变，请重新打开导出窗口。')
  artifact.value = value
  return value
}

function show() {
  resetTable()
  return run(async (signal) => {
    const value = await load(signal)
    const archive = csvExport.value?.archive
    if (archive && !tables.value.length) {
      const directory = await zipCsvTables(value)
      signal.throwIfAborted()
      tables.value = directory
    }
    signal.throwIfAborted()
    if (archive && !tables.value.length) throw new Error('此归档没有 CSV 表。')
    const data = archive ? await tables.value[table.value]!.load() : value
    const index = await csvOffsets(data, mode.value === 'all' ? Infinity : 21, signal)
    const header = await data.slice(0, index[1] ?? 0).text()
    signal.throwIfAborted()
    if (isStale()) throw new Error('导出来源已改变，请重新打开导出窗口。')
    offsets.value = index
    columns.value = csvRecords(header)[0] ?? []
    preview.value = data
    await readRows()
  })
}

function download() {
  return run(async (signal) => {
    const checked = await load(signal)
    await csvExport.value?.verify?.()
    signal.throwIfAborted()
    if (isStale()) throw new Error('导出来源已改变，请重新打开导出窗口。')
    const extension = csvExport.value?.archive ? '.zip' : '.csv'
    const name = filename.value.trim()
    saveBlob(checked, name.toLowerCase().endsWith(extension) ? name : name + extension)
  })
}
function updateLabel(id: string, value: string) {
  labels.value[id] = value
  csvExport.value?.onLabels?.({ ...labels.value })
  resetArtifact()
}
</script>

<template>
  <ExportDialog ref="dialog" title="CSV 导出" @close="csvExport = undefined">
    <div v-if="csvExport" class="csv-settings actions">
      <label>文件名<input v-model="filename" maxlength="180" :disabled="busy" /></label>
      <label
        >预览范围
        <select v-model="mode" :disabled="busy || stale" @change="artifact && show()">
          <option value="quick">快速预览（前 20 行）</option>
          <option value="all">浏览全部内容</option>
        </select>
      </label>
      <label v-if="tables.length"
        >归档中的表
        <select v-model.number="table" :disabled="busy || stale" @change="show">
          <option v-for="(entry, index) in tables" :key="entry.name" :value="index">
            {{ entry.name }}
          </option>
        </select>
      </label>
    </div>
    <details v-if="csvExport?.samples?.length" class="csv-labels">
      <summary>CSV 标签设置</summary>
      <p class="muted">设置本次 CSV 的 Label 列，可让多个样本共用标签。</p>
      <div class="field-grid">
        <label v-for="sample in csvExport.samples" :key="sample.id">
          {{ sample.name }}
          <input
            :aria-label="`CSV 标签 ${sample.name}`"
            :value="labels[sample.id] ?? sample.label"
            :disabled="busy || stale"
            @input="updateLabel(sample.id, ($event.target as HTMLInputElement).value)"
          />
        </label>
      </div>
    </details>
    <p v-if="stale" role="status">导出来源已改变，请重新打开导出窗口。</p>
    <p v-if="busy" role="status">正在读取导出数据…</p>
    <p v-if="error" role="alert" class="state-note">{{ error }}</p>
    <div v-if="preview && !stale">
      <div class="actions csv-pages">
        <span role="status"
          >{{ mode === 'all' ? '全部' : '当前预览' }} {{ rowCount }} 行 ×
          {{ columns.length }} 列</span
        >
        <template v-if="rowPages > 1">
          <button :disabled="rowPage <= 1" @click="rowPage--">上一页</button>
          <label class="inline-field"
            >行页
            <input
              :value="rowPage"
              aria-label="CSV 行页"
              type="number"
              min="1"
              :max="rowPages"
              @change="rowPage = pageNumber($event, rowPages)"
            />
          </label>
          <span>/ {{ rowPages }}</span>
          <button :disabled="rowPage >= rowPages" @click="rowPage++">下一页</button>
        </template>
        <template v-if="columnPages > 1">
          <button :disabled="columnPage <= 1" @click="columnPage--">上一组列</button>
          <label class="inline-field"
            >列页
            <input
              :value="columnPage"
              aria-label="CSV 列页"
              type="number"
              min="1"
              :max="columnPages"
              @change="columnPage = pageNumber($event, columnPages)"
            />
          </label>
          <span>/ {{ columnPages }}</span>
          <button :disabled="columnPage >= columnPages" @click="columnPage++">下一组列</button>
        </template>
      </div>
      <div v-if="columns.length" class="csv-preview-table" tabindex="0" aria-label="CSV 数据预览">
        <table>
          <thead>
            <tr>
              <th scope="col">行</th>
              <th v-for="(column, index) in visibleColumns" :key="index" scope="col">
                {{ column }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="index">
              <th scope="row">{{ (rowPage - 1) * 20 + index + 1 }}</th>
              <td v-for="(_, col) in visibleColumns" :key="col">{{ row[firstColumn + col] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted">此表没有数据。</p>
    </div>
    <template #footer>
      <button class="preview" :disabled="busy || stale" @click="show">预览 CSV</button>
      <button class="download" :disabled="busy || stale || !filename.trim()" @click="download">
        {{ csvExport?.archive ? '下载归档' : '下载 CSV' }}
      </button>
    </template>
  </ExportDialog>
</template>

<style scoped>
.csv-settings {
  align-items: end;
}
.csv-labels,
.csv-pages {
  margin-block: 10px;
}
.csv-pages input {
  width: 66px;
}
.csv-preview-table {
  max-height: 565px;
  overflow: auto;
  border: 1px solid #dbe4ed;
}
.csv-preview-table table {
  width: max-content;
  min-width: 100%;
}
.csv-preview-table thead {
  position: sticky;
  top: 0;
}
.csv-preview-table td,
.csv-preview-table th {
  max-width: 360px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
