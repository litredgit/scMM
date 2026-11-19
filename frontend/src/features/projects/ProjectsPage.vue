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
  const result = await store.mutate(
    '/project',
    { name: name.value },
    'POST',
    '项目已创建，可以添加样本。',
  )
  if (result) {
    name.value = ''
    await router.push('/samples')
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
      <div>
        <h1>选择项目</h1>
      </div>
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
        <button class="primary" :disabled="store.busy || !name.trim()">
          创建并添加样本 <span aria-hidden="true">→</span>
        </button>
      </form>
    </section>
    <section class="card project-list">
      <div class="section-heading">
        <div>
          <h2>
            已保存项目 <span class="count">{{ projects.length }}</span>
          </h2>
          <p>打开项目继续已保存的工作；备注可在“添加原始文件”中编辑。</p>
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
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>项目名称</th>
              <th>项目备注</th>
              <th>样本数</th>
              <th>数据状态</th>
              <th>创建时间（北京时间）</th>
              <th>最后修改时间（北京时间）</th>
              <th><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filtered" :key="item.path">
              <td>
                <strong>{{ item.name }}</strong
                ><small class="path"
                  >{{ item.path }} <HelpTip :text="item.path" label="项目完整路径"
                /></small>
              </td>
              <td class="project-note">{{ item.description || '—' }}</td>
              <td>{{ item.samples }}</td>
              <td>
                <template v-if="item.data_state === 'saved'"
                  >已保存数据 · {{ item.cells }} 个观测 × {{ item.features }} 特征</template
                >
                <template v-else-if="item.data_state === 'unavailable'"
                  >快照不可读取，请检查文件</template
                >
                <template v-else>尚未保存数据集</template>
              </td>
              <td>{{ item.created_at ? date(item.created_at) : '未记录' }}</td>
              <td>{{ date(item.saved_at) }}</td>
              <td>
                <button :disabled="store.busy" @click="open(item.path)">打开项目 →</button>
                <TrashAction
                  :path="item.path"
                  :disabled="item.path === store.project?.path"
                  @changed="removed"
                />
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
  grid-template-columns: minmax(190px, 1fr) minmax(220px, 1.5fr) max-content;
  gap: 1.25rem;
  align-items: end;
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
