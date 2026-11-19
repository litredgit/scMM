<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { useReadScope } from '../../api/readScope'
import SelectionLabels from './SelectionLabels.vue'
const props = defineProps<{ editor?: boolean }>()
const store = useWorkspace()
type Inspection = {
  preview_basis: string
  feature_total: number
  feature_rows: { id: string; name: string }[]
  feature_history: unknown[]
  metadata_history: unknown[]
  observations: number
  features: number
  warnings: string[]
  observation_ids: string[]
  feature_ids: string[]
  values: (number | null)[][]
}
const data = ref<Inspection>()
const featureOffset = ref(0)
const featureQuery = ref('')
const nameFilter = ref('all')
watch(nameFilter, () => {
  featureOffset.value = 0
  void refresh()
})
const featureDrafts = ref<Record<string, string>>({})
watch(
  () =>
    JSON.stringify([
      store.current?.workspace_id,
      store.project?.path,
      store.project?.dataset?.id,
      store.project?.dataset?.revision,
    ]),
  () => {
    featureDrafts.value = {}
    featureOffset.value = 0
  },
)
let sampleSource = ''
const rows = ref<{ id: string; name: string; group: string; subject: string; batch: string }[]>([])
const reads = useReadScope(() => [store.current?.workspace_id, store.current?.revision])
async function refresh() {
  const accept = reads.begin()
  if (!store.project?.dataset) {
    data.value = undefined
    rows.value = []
    sampleSource = ''
    return
  }
  const result = await store.read<Inspection>(
    `/analysis/data-inspection?${new URLSearchParams({ feature_offset: String(featureOffset.value), feature_query: featureQuery.value, name_filter: nameFilter.value })}`,
    undefined,
    accept,
  )
  if (accept()) {
    data.value = result
    const source = JSON.stringify([
      store.current?.workspace_id,
      store.project?.path,
      store.project?.dataset?.id,
      (store.project?.manifest.samples ?? []).map((s) => [
        s.id,
        s.name,
        s.group,
        s.subject,
        s.batch,
      ]),
    ])
    if (source !== sampleSource) {
      sampleSource = source
      rows.value = (store.project?.manifest.samples ?? []).map((s) => ({
        id: s.id,
        name: s.name,
        group: s.group || '',
        subject: s.subject || '',
        batch: s.batch || '',
      }))
    }
  }
}
watch(
  () => JSON.stringify([store.current?.workspace_id, store.current?.revision, store.project?.path]),
  refresh,
  { immediate: true },
)
function quote(text: string) {
  return '"' + text.replaceAll('"', '""') + '"'
}
async function saveFeatures() {
  if (!data.value) return
  const content =
    'feature_id,name\n' +
    Object.entries(featureDrafts.value)
      .map(([id, name]) => [quote(id), quote(name)].join(','))
      .join('\n')
  const applied = await store.command('/analysis/annotations/apply', {
    content,
    format: 'csv',
    mapping: { name: 'display_name' },
    source_key: 'feature_id',
    target_key: 'feature_id',
    mode: 'key',
    clear_unmatched: false,
    transpose: false,
  })
  if (applied) featureDrafts.value = {}
  await refresh()
}
function searchFeatures() {
  featureOffset.value = 0
  void refresh()
}
async function featurePage(direction: number) {
  featureOffset.value = Math.max(0, featureOffset.value + direction * 10)
  await refresh()
}
async function save() {
  await store.mutate('/samples', { samples: rows.value }, 'PATCH', '元数据已应用。')
}
</script>
<template>
  <section>
    <div class="page-title">
      <h1>{{ props.editor ? '数据编辑' : '数据检查' }}</h1>
    </div>
    <template v-if="data">
      <div class="card">
        <p>{{ data.observations }} 个观测 × {{ data.features }} 个特征</p>
        <p v-if="!data.warnings.length">结构检查通过。</p>
        <ul v-else>
          <li v-for="message in data.warnings" :key="message">{{ message }}</li>
        </ul>
      </div>
      <section v-if="!editor" class="card">
        <h2>项目基本信息</h2>
        <p>{{ store.project?.manifest.name }} · {{ rows.length }} 个来源样本</p>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>样本</th>
                <th>分组</th>
                <th>来源个体</th>
                <th>批次</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td>{{ row.name }}</td>
                <td>{{ row.group || '—' }}</td>
                <td>{{ row.subject || '—' }}</td>
                <td>{{ row.batch || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <template v-if="editor">
        <section class="card">
          <h2>样本元数据</h2>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>名称</th>
                  <th>分组</th>
                  <th>来源个体</th>
                  <th>批次</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in rows" :key="row.id">
                  <td>{{ row.id }}</td>
                  <td v-for="key in ['name', 'group', 'subject', 'batch'] as const" :key="key">
                    <input
                      v-model="row[key]"
                      :aria-label="`${row.id} ${key}`"
                      :disabled="store.busy"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <button class="primary" :disabled="store.busy || !rows.length" @click="save">
            应用元数据
          </button>
        </section>
        <details class="card">
          <summary>元数据修改记录</summary>
          <pre>{{ JSON.stringify(data.metadata_history, null, 2) }}</pre>
        </details>
        <section class="card">
          <h2>特征显示名称</h2>
          <form class="actions" @submit.prevent="searchFeatures">
            <label
              >搜索 ID 或名称<input
                v-model="featureQuery"
                aria-label="搜索特征名称"
                maxlength="200" /></label
            ><label
              >名称状态<select v-model="nameFilter">
                <option value="all">全部</option>
                <option value="named">已有名称</option>
                <option value="unnamed">未命名</option>
              </select></label
            >
            <button class="preview" :disabled="store.busy">查找特征</button>
          </form>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>稳定 ID</th>
                  <th>显示名称</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in data.feature_rows" :key="row.id">
                  <td>{{ row.id }}</td>
                  <td>
                    <input
                      :value="featureDrafts[row.id] ?? row.name"
                      @input="featureDrafts[row.id] = ($event.target as HTMLInputElement).value"
                      maxlength="200"
                      :aria-label="`特征名称 ${row.id}`"
                      :disabled="store.busy"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="actions">
            <button :disabled="store.busy || featureOffset === 0" @click="featurePage(-1)">
              上一页特征</button
            ><span
              >{{ data.feature_total ? featureOffset + 1 : 0 }}–{{
                Math.min(featureOffset + 10, data.feature_total)
              }}
              / {{ data.feature_total }}</span
            ><button
              :disabled="store.busy || featureOffset + 10 >= data.feature_total"
              @click="featurePage(1)"
            >
              下一页特征</button
            ><button
              class="primary"
              :disabled="store.busy || !Object.keys(featureDrafts).length"
              @click="saveFeatures"
            >
              应用特征名称修改
            </button>
          </div>
          <details>
            <summary>特征名称修改记录</summary>
            <pre>{{ JSON.stringify(data.feature_history, null, 2) }}</pre>
          </details>
        </section>
        <SelectionLabels v-if="data.observations" />
        <section class="card">
          <h2>定量矩阵预览 · 只读</h2>
          <p>
            随机抽取最多 10 个观测，特征按{{
              data.preview_basis === 'absolute_total' ? '当前值绝对值总和' : '总强度'
            }}选取前 10 项。完整矩阵可在结果页下载。
          </p>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>观测 ID</th>
                  <th v-for="id in data.feature_ids" :key="id">{{ id }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in data.values" :key="i">
                  <td>{{ data.observation_ids[i] }}</td>
                  <td v-for="(value, j) in row" :key="j">
                    {{ value === null ? '—' : value.toExponential(1) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
      <RouterLink v-else class="button primary" to="/data-editor">编辑元数据与纳入范围</RouterLink>
    </template>
    <p v-else>请先选择数据来源。</p>
  </section>
</template>
