<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FileBrowser from '../../components/FileBrowser.vue'
import { request } from '../../api/client'
import type { Mapping, Sample } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'

const store = useWorkspace()
const picker = ref<'raw' | 'results' | null>(null)
const fileRoot = ref('')
const paths = ref<string[]>([])
const manual = ref('')
const inspected = ref<{
  cells: number
  features: number
  layers: string[]
  samples: string[]
  groups: string[]
  missing_group: boolean
}>()
const inspectedPath = ref('')
const pendingProject = ref('')
const selected = ref<string[]>([])
const samples = ref<Sample[]>([])
const name = ref('')
const description = ref('')
const mapping = ref<Mapping | null>(null)
const mappingBusy = ref(false)
const mappingError = ref('')
const browser = ref<InstanceType<typeof FileBrowser> | null>(null)
const previousProject = ref('')
const sampleSearch = ref('')
const visibleSamples = computed(() =>
  samples.value.filter((sample) =>
    [sample.name, sample.group, sample.subject, sample.batch].some((value) =>
      value.toLocaleLowerCase().includes(sampleSearch.value.toLocaleLowerCase()),
    ),
  ),
)
let mappingGeneration = 0

async function loadMapping(sourceKey?: string) {
  const ticket = ++mappingGeneration
  if (!store.current || !store.project?.dataset) {
    mapping.value = null
    mappingBusy.value = false
    mappingError.value = ''
    return
  }
  const workspace = store.current.workspace_id
  const revision = store.current.revision
  mappingBusy.value = true
  mappingError.value = ''
  try {
    const result = await request<Mapping>(
      `/workspace/samples/mapping${sourceKey ? `?${new URLSearchParams({ source_key: sourceKey })}` : ''}`,
      { workspace },
    )
    if (ticket === mappingGeneration && revision === store.current?.revision) mapping.value = result
  } catch (cause) {
    if (ticket === mappingGeneration)
      mappingError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (ticket === mappingGeneration) mappingBusy.value = false
  }
}
watch(
  () => store.current,
  () => {
    const project = store.project
    name.value = project?.manifest.name ?? ''
    description.value = project?.manifest.description ?? ''
    samples.value = project?.manifest.samples.map((sample) => ({ ...sample })) ?? []
    selected.value = selected.value.filter((id) => samples.value.some((sample) => sample.id === id))
    if (previousProject.value !== project?.manifest.id) {
      previousProject.value = project?.manifest.id ?? ''
      picker.value = null
      paths.value = []
      selected.value = []
      manual.value = ''
      sampleSearch.value = ''
    }
    void loadMapping()
  },
  { immediate: true },
)

function togglePicker(kind: 'raw' | 'results') {
  picker.value = picker.value === kind ? null : kind
  paths.value = []
  manual.value = ''
  fileRoot.value =
    (kind === 'raw' ? store.configuration?.storage : store.configuration?.results)?.[0]?.label ?? ''
}
function selectFiles(root: string, values: string[]) {
  fileRoot.value = root
  paths.value = values
}
const chosen = computed(() => [
  ...new Set([
    ...paths.value,
    ...manual.value
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean),
  ]),
])
watch(
  () => JSON.stringify([fileRoot.value, chosen.value, store.project?.manifest.id]),
  () => {
    inspected.value = undefined
    inspectedPath.value = ''
  },
)
async function inspect() {
  const path = chosen.value[0]
  if (!path) return
  const source = JSON.stringify([fileRoot.value, path, store.project?.manifest.id])
  const value = await store.read<NonNullable<typeof inspected.value>>(
    `/dataset/inspect?${new URLSearchParams({ root: fileRoot.value, path })}`,
  )
  if (
    source === JSON.stringify([fileRoot.value, chosen.value[0], store.project?.manifest.id]) &&
    value
  ) {
    inspected.value = value
    inspectedPath.value = path
  }
}
async function openProject(path: string, decision?: 'save' | 'discard') {
  if (store.project?.unsaved && !decision) {
    pendingProject.value = path
    return
  }
  if (decision === 'save' && !(await store.mutate('/project/save', {}))) return
  if (await store.mutate('/project/open', { path })) pendingProject.value = ''
}
async function add() {
  const result = await store.mutate(
    '/samples',
    { root: fileRoot.value, paths: chosen.value },
    'POST',
    '原始文件已添加。',
  )
  if (result) {
    picker.value = null
    paths.value = []
    manual.value = ''
  }
}
async function importDataset() {
  if (!inspected.value || inspectedPath.value !== chosen.value[0]) return
  const result = await store.mutate(
    '/dataset/import',
    { root: fileRoot.value, path: chosen.value[0] },
    'POST',
    '结果已导入，请核对样本关联。',
  )
  if (result) {
    picker.value = null
    paths.value = []
    manual.value = ''
  }
}
async function saveSample(sample: Sample) {
  const { id, name, group, subject, batch } = sample
  await store.mutate(
    '/samples',
    { samples: [{ id, name, group, subject, batch }] },
    'PATCH',
    '样本信息已更新。',
  )
}
async function importCSV(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  try {
    if (file) {
      if (file.size > 5_000_000) throw new Error('CSV 文件不能超过 5 MB。')
      const csv = await file.text()
      await store.mutate('/samples/csv', { csv }, 'POST', 'CSV 样本信息已应用。')
    }
  } catch (cause) {
    store.error = cause instanceof Error ? cause.message : String(cause)
  } finally {
    input.value = ''
  }
}
function toggle(id: string) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((item) => item !== id)
    : [...selected.value, id]
}
async function applyMapping() {
  if (!mapping.value) return
  const values = Object.fromEntries(
    mapping.value.rows.filter((row) => row.sample_id).map((row) => [row.value, row.sample_id]),
  )
  await store.mutate(
    '/samples/mapping',
    { source_key: mapping.value.source_key, mapping: values },
    'PUT',
    '样本关联已更新。',
  )
}
</script>

<template>
  <section v-if="store.project">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 01 / 样本管理</p>
        <h1>项目与样本</h1>
        <p>建立样本清单，并标记实验分组、独立生物来源和采集批次。</p>
      </div>
      <span class="step-badge">01 / 06</span>
    </div>
    <div class="metric-strip">
      <div>
        <span>项目样本</span><strong>{{ samples.length }}<small>个</small></strong>
      </div>
      <div>
        <span>当前细胞</span
        ><strong>{{ store.project.dataset?.cells.toLocaleString() ?? '—' }}</strong>
      </div>
      <div>
        <span>当前特征</span
        ><strong>{{ store.project.dataset?.features.toLocaleString() ?? '—' }}</strong>
      </div>
      <div>
        <span>已保存修订</span><strong>r{{ store.project.manifest.revision }}</strong>
      </div>
    </div>
    <section class="card">
      <div class="section-heading">
        <div>
          <h2>样本清单</h2>
          <p>移出样本只修改清单，原始文件保留。</p>
        </div>
        <div class="actions">
          <button class="primary" :disabled="store.busy" @click="togglePicker('raw')">
            ＋ 添加原始文件</button
          ><button class="primary" :disabled="store.busy" @click="togglePicker('results')">
            导入独立结果</button
          ><button
            class="danger"
            :disabled="store.busy || !selected.length"
            @click="store.mutate('/samples/remove', { ids: selected }, 'POST', '样本已移出清单。')"
          >
            移出选中样本{{ selected.length ? `（${selected.length}）` : '' }}
          </button>
        </div>
      </div>
      <div v-if="picker" class="picker-panel">
        <div class="section-heading">
          <h3>{{ picker === 'raw' ? '选择原始文件' : '选择独立结果目录或 H5AD' }}</h3>
          <button :disabled="store.busy" @click="picker = null">收起</button>
        </div>
        <FileBrowser
          :key="`${picker}-${store.project.manifest.id}`"
          ref="browser"
          :roots="picker === 'raw' ? store.configuration!.storage : store.configuration!.results"
          :kind="picker"
          :disabled="store.busy"
          @selected="selectFiles"
          @project="(path) => openProject(path)"
        />
        <div v-if="pendingProject" class="picker-panel" role="status">
          <p>当前项目有未保存修改，请选择如何打开完整项目。</p>
          <button class="save" :disabled="store.busy" @click="openProject(pendingProject, 'save')">
            保存并打开
          </button>
          <button
            class="danger"
            :disabled="store.busy"
            @click="openProject(pendingProject, 'discard')"
          >
            放弃修改并打开
          </button>
          <button :disabled="store.busy" @click="pendingProject = ''">留在当前项目</button>
        </div>
        <details>
          <summary>直接输入服务器路径</summary>
          <label
            ><FieldLabel name="每行一个路径" /><textarea
              aria-label="每行一个路径"
              v-model="manual"
              rows="2"
              :disabled="store.busy"
              placeholder="相对当前存储根的路径，或根内绝对路径"
            />
          </label>
        </details>
        <div class="actions picker-actions">
          <template v-if="picker === 'raw'"
            ><button class="primary" :disabled="store.busy || !chosen.length" @click="add">
              添加 {{ chosen.length }} 个文件</button
            ><button
              :disabled="store.busy || selected.length !== 1 || chosen.length !== 1"
              @click="
                store.mutate(
                  '/samples/relocate',
                  { sample_id: selected[0], root: fileRoot, path: chosen[0] },
                  'POST',
                  '原始文件关联已更新。',
                )
              "
            >
              为选中样本重新定位
            </button></template
          ><template v-else
            ><button class="preview" :disabled="store.busy || chosen.length !== 1" @click="inspect">
              检查所选结果
            </button>
            <div v-if="inspected" role="status">
              <p>
                {{ inspected.cells }} 细胞 × {{ inspected.features }} 特征；分组：{{
                  inspected.groups.join('、') || '缺失'
                }}；样本：{{ inspected.samples.join('、') || '未记录 sample 列' }}。
              </p>
              <p>
                数据层：{{
                  inspected.layers.join('、') || '仅当前矩阵'
                }}。独立结果建立新的预处理起点，不恢复完整项目的原起点和全部视图。
              </p>
              <p v-if="inspected.missing_group">
                分组不完整，导入后请补齐样本关联及 group，再导出矩阵 CSV。
              </p>
            </div>
            <button
              class="primary"
              :disabled="store.busy || chosen.length !== 1 || !inspected"
              @click="importDataset()"
            >
              导入并替换当前数据
            </button>
            <p class="muted">
              继续已有实验请使用“打开完整项目”，无需再次导入。此入口仅用于独立 H5AD
              或兼容结果目录；旧 pickle
              请先离线转换。导入会替换当前矩阵和预处理起点，请先保存需要保留的修改。
            </p></template
          >
        </div>
      </div>
      <form
        class="project-form"
        @submit.prevent="
          store.mutate('/project', { name, description }, 'PATCH', '项目信息已应用。')
        "
      >
        <label
          ><FieldLabel name="项目名称" /><input
            aria-label="项目名称"
            v-model="name"
            required
            maxlength="200"
            :disabled="store.busy" /></label
        ><label class="grow"
          ><FieldLabel name="项目说明" /><input
            aria-label="项目说明"
            v-model="description"
            maxlength="20000"
            :disabled="store.busy"
            placeholder="记录实验目的与备注" /></label
        ><button
          class="primary"
          :disabled="
            store.busy ||
            (name === store.project.manifest.name &&
              description === store.project.manifest.description)
          "
        >
          应用项目信息
        </button>
      </form>
      <div class="sample-toolbar">
        <p class="muted">group：实验分组 · subject：独立生物来源 · batch：采集批次</p>
        <input v-model="sampleSearch" aria-label="搜索样本" placeholder="搜索样本或分组" />
      </div>
      <div v-if="!samples.length" class="empty-state">
        <span class="empty-symbol">▤</span>
        <h3>添加你的第一个样本</h3>
        <p>支持 Thermo profile RAW、mzML 和 mzXML，也可导入已有 H5AD。</p>
        <button class="primary" :disabled="store.busy" @click="togglePicker('raw')">
          选择原始文件
        </button>
      </div>
      <div v-else class="table-scroll">
        <table class="sample-table">
          <thead>
            <tr>
              <th><span class="sr-only">选择</span></th>
              <th>
                <FieldLabel
                  name="name"
                  text="样本显示名称，项目内唯一；修改后仍以稳定 sample_id 同步已有数据。"
                />
              </th>
              <th>
                <FieldLabel
                  name="group"
                  text="实验比较分组，例如处理组/对照组；相同组名的细胞归入同一组，不代表独立生物重复。"
                />
              </th>
              <th>
                <FieldLabel
                  name="subject"
                  text="独立生物来源，例如供体或独立培养物。同一来源的样本填写相同值，可用于分组验证；细胞数量不等于独立来源数量。"
                />
              </th>
              <th>
                <FieldLabel
                  name="batch"
                  text="采集或处理批次标签，用于识别技术批次；不自动执行批次校正，也不能代替独立生物来源。"
                />
              </th>
              <th>原始文件</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sample in visibleSamples" :key="sample.id">
              <td>
                <input
                  type="checkbox"
                  :checked="selected.includes(sample.id)"
                  :disabled="store.busy"
                  @change="toggle(sample.id)"
                  :aria-label="`选择样本 ${sample.name}`"
                />
              </td>
              <td v-for="key in ['name', 'group', 'subject', 'batch'] as const" :key="key">
                <input
                  v-model="sample[key]"
                  :aria-label="`${sample.name} ${key}`"
                  :disabled="store.busy"
                  @change="saveSample(sample)"
                />
              </td>
              <td>
                <span class="file-name">{{ sample.path.split('/').at(-1) || '仅结果数据' }}</span
                ><HelpTip
                  :text="sample.path || '该样本只有导入结果，尚未关联原始谱。'"
                  label="完整路径"
                /><small v-if="sample.metadata_unresolved?.length" class="inline-error"
                  >待核对：{{ sample.metadata_unresolved.join(' / ') }}</small
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="sample-footer">
        <label class="upload-control button"
          ><FieldLabel name="导入样本信息 CSV" /><input
            aria-label="导入样本信息 CSV"
            type="file"
            class="sr-only"
            accept=".csv,text/csv"
            :disabled="store.busy"
            @change="importCSV"
        /></label>
        <p class="muted">
          CSV 必须包含唯一 name 列，可含
          group、subject、batch；编辑样本字段后自动应用，仍需主动保存项目。
        </p>
      </div>
    </section>
    <section v-if="store.project.dataset" class="card mapping-panel">
      <div class="section-heading">
        <div>
          <h2>结果与样本关联</h2>
          <p>关联不明确时，选择结果中的样本字段并逐项映射到项目样本。</p>
        </div>
      </div>
      <p v-if="mappingError" role="alert" class="inline-error">{{ mappingError }}</p>
      <label
        ><FieldLabel name="结果样本字段" /><select
          aria-label="结果样本字段"
          :value="mapping?.source_key ?? ''"
          :disabled="store.busy || mappingBusy"
          @change="loadMapping(($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>请选择字段</option>
          <option v-for="column in store.project.dataset.observation_columns" :key="column">
            {{ column }}
          </option>
        </select></label
      >
      <div v-if="mapping?.rows.length" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>结果样本</th>
              <th>项目样本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in mapping.rows" :key="row.value">
              <td>{{ row.value }}</td>
              <td>
                <select
                  v-model="row.sample_id"
                  :disabled="store.busy || mappingBusy"
                  :aria-label="`映射 ${row.value}`"
                >
                  <option value="">尚未关联</option>
                  <option v-for="sample in samples" :key="sample.id" :value="sample.id">
                    {{ sample.name }}
                  </option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <button
        class="primary"
        :disabled="store.busy || mappingBusy || !mapping?.source_key"
        @click="applyMapping"
      >
        应用样本关联
      </button>
    </section>
    <div class="page-note">细胞数不等于生物重复数。同一独立来源的多个样本应填写相同 subject。</div>
  </section>
  <div v-else class="card empty-state">
    <h1>先选择一个项目</h1>
    <p>打开已有实验，或创建项目开始添加样本。</p>
    <RouterLink to="/projects" class="button primary">前往项目首页 →</RouterLink>
  </div>
</template>
