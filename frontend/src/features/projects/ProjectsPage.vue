<script setup lang="ts">
import { formatTime } from '../../help/time'
import { computed, onMounted, ref } from 'vue'
import TrashAction from '../../components/TrashAction.vue'
import { useRouter } from 'vue-router'
import { useReadScope } from '../../api/readScope'
import type { SavedProject } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'

const store = useWorkspace()
const router = useRouter()
async function removed() {
  await load()
}
const name = ref('')
const inputKind = ref('raw')
const search = ref('')
const projects = ref<SavedProject[]>([])
const loading = ref(false)
const filtered = computed(() =>
  projects.value.filter((item) =>
    [item.name, item.description].some((value) =>
      (value ?? '').toLocaleLowerCase().includes(search.value.toLocaleLowerCase()),
    ),
  ),
)
const listScope = useReadScope(
  () => store.current?.workspace_id,
  () => void load(),
)
async function load() {
  const accept = listScope.begin()
  if (!accept()) return
  loading.value = true
  try {
    const value = await store.readResource<SavedProject[]>('/projects', { accept })
    if (accept() && value) projects.value = value
  } finally {
    if (accept()) loading.value = false
  }
}
onMounted(load)
async function create() {
  const result = await store.mutate('/project', { name: name.value }, 'POST', '项目已创建。')
  if (result) {
    name.value = ''
    await router.push(
      inputKind.value === 'raw'
        ? '/samples'
        : inputKind.value === 'features'
          ? { path: '/annotation', query: { import: 'feature_csv' } }
          : { path: '/statistics', query: { import: 'matrix_csv' } },
    )
  }
}
async function open(path: string) {
  if (store.project?.unsaved) {
    pendingPath.value = path
    return
  }
  await finishOpen(path)
}
const pendingPath = ref('')
async function finishOpen(path: string, save = false) {
  if (save && !(await store.mutate('/project/save', {}))) return
  const result = await store.mutate('/project/open', { path })
  if (result) {
    pendingPath.value = ''
    const dataset = result.project?.dataset
    await router.push(
      dataset?.quantitation_available === false
        ? '/annotation'
        : dataset
          ? '/preprocess'
          : '/samples',
    )
  }
}
function date(value: string) {
  return formatTime(value)
}
</script>

<template>
  <section class="projects-home">
    <div class="page-title">
      <h1>选择项目</h1>
    </div>
    <section class="card project-start">
      <form class="create-project" @submit.prevent="create">
        <div class="project-create-heading">
          <h2>创建项目</h2>
          <small class="muted">原始文件保留在服务器原位置。</small>
        </div>
        <label
          ><FieldLabel name="项目名称" /><input
            aria-label="项目名称"
            v-model="name"
            required
            maxlength="200"
            placeholder="例如：细胞代谢实验 A"
            :disabled="store.busy"
        /></label>
        <label
          >已有数据
          <select v-model="inputKind" :disabled="store.busy">
            <option value="raw">原始谱</option>
            <option value="features">m/z 特征表</option>
            <option value="matrix">定量矩阵</option>
          </select>
        </label>
        <button class="primary" :disabled="store.busy || !name.trim()">
          {{
            { raw: '创建并添加样本', features: '创建并导入特征', matrix: '创建并导入矩阵' }[
              inputKind
            ]
          }}
          <span aria-hidden="true">→</span>
        </button>
      </form>
    </section>
    <section class="card project-list">
      <div class="section-heading">
        <div>
          <h2>
            已保存项目 <span class="count">{{ projects.length }}</span>
          </h2>
        </div>
        <div class="actions">
          <input v-model="search" aria-label="搜索项目" placeholder="搜索项目名称或备注" /><button
            @click="load"
            :disabled="store.busy || loading"
            class="preview"
          >
            刷新
          </button>
        </div>
      </div>
      <div v-if="pendingPath" class="picker-panel" role="status">
        <p>当前项目有未保存修改，请选择如何打开目标项目。</p>
        <div class="actions">
          <button class="save" :disabled="store.busy" @click="finishOpen(pendingPath, true)">
            保存并打开
          </button>
          <button class="danger" :disabled="store.busy" @click="finishOpen(pendingPath)">
            放弃修改并打开
          </button>
          <button :disabled="store.busy" @click="pendingPath = ''">留在当前项目</button>
        </div>
      </div>
      <p v-if="loading" class="muted">正在读取已保存项目…</p>
      <div v-else-if="!filtered.length" class="empty-state">
        <span class="empty-symbol">▤</span>
        <h3>{{ projects.length ? '没有匹配的项目' : '还没有保存的项目' }}</h3>
        <p>创建项目后，会在这里显示。</p>
      </div>
      <div v-else class="table-scroll project-table">
        <table>
          <thead>
            <tr>
              <th scope="col">项目名称</th>
              <th scope="col">项目备注</th>
              <th scope="col" class="project-sample-count">样本数</th>
              <th scope="col">数据状态</th>
              <th scope="col">最近保存（北京时间）</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in filtered"
              :key="item.path"
              :class="{ 'open-project': item.path === store.project?.path }"
            >
              <td>
                <strong>{{ item.name }}</strong>
                <small class="project-path muted">
                  <span>{{ item.path }}</span>
                  <HelpTip :text="item.path" label="项目完整路径" />
                </small>
              </td>
              <td class="project-note">{{ item.description || '—' }}</td>
              <td class="project-sample-count">{{ item.samples }}</td>
              <td>
                <template v-if="item.data_state === 'saved'"
                  >已保存数据 · {{ item.cells }} 个观测 × {{ item.features }} 特征</template
                >
                <template v-else-if="item.data_state === 'unavailable'"
                  >快照不可读取，请检查文件</template
                >
                <template v-else>尚未保存数据集</template>
              </td>
              <td>
                <span class="project-date">{{ date(item.saved_at) }}</span>
                <small class="muted project-date"
                  >创建于 {{ item.created_at ? date(item.created_at) : '未记录' }}</small
                >
              </td>
              <td>
                <div class="project-row-actions">
                  <button :disabled="store.busy" @click="open(item.path)">打开项目 →</button>
                  <TrashAction
                    :path="item.path"
                    :disabled="item.path === store.project?.path"
                    @changed="removed"
                  />
                </div>
                <small v-if="item.path === store.project?.path"
                  >当前项目，请先保存并关闭后管理。</small
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="storage-path">项目根目录：{{ store.configuration?.project_root }}</p>
    </section>
  </section>
</template>

<style scoped>
.project-start > .create-project {
  display: grid;
  grid-template-columns: minmax(150px, 220px) minmax(180px, 380px) minmax(120px, 160px) max-content;
  gap: 16px;
  align-items: end;
}
.project-start {
  padding: 18px;
  background: linear-gradient(105deg, #e9f5f8, var(--surface) 66%);
  border-color: #c9dce6;
}
.project-create-heading h2 {
  margin: 0 0 0.25rem;
}
.project-create-heading small {
  font-size: 0.79rem;
}
.create-project label,
.create-project button {
  margin: 0;
  width: auto;
}
.project-list > .section-heading {
  align-items: center;
}
.project-list > .section-heading h2 {
  margin: 0;
}
.project-table {
  max-height: 64vh;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
}
.project-table table {
  table-layout: fixed;
  min-width: 980px;
}
.project-table th {
  position: sticky;
  top: 0;
  z-index: 1;
}
.project-table th:first-child {
  width: 26%;
}
.project-table th:nth-child(3) {
  width: 75px;
}
.project-table th:nth-child(5) {
  width: 206px;
}
.project-table th:last-child {
  width: 218px;
}
.project-table td {
  vertical-align: middle;
  overflow-wrap: anywhere;
}
.project-table .open-project td:first-child {
  box-shadow: inset 3px 0 var(--teal);
}
.project-sample-count {
  text-align: center;
}
.project-path {
  display: flex;
  align-items: center;
  margin-top: 2px;
  gap: 4px;
}
.project-path > span:first-child {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.project-date {
  display: block;
  white-space: nowrap;
}
.project-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
@media (max-width: 1100px) {
  .project-start > .create-project {
    grid-template-columns: minmax(0, 1fr) max-content;
  }
  .project-create-heading {
    grid-column: 1 / -1;
  }
}
@media (max-width: 480px) {
  .project-start > .create-project {
    grid-template-columns: 1fr;
    gap: 0.75rem;
  }
  .create-project button {
    width: 100%;
  }
}
</style>
