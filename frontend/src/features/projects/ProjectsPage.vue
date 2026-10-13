<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'
import SavedItems from '../../components/SavedItems.vue'
import { useRouter } from 'vue-router'
import { request } from '../../api/client'
import type { SavedProject } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'

const store = useWorkspace()
const router = useRouter()
const name = ref('')
const search = ref('')
const projects = ref<SavedProject[]>([])
const loading = ref(false)
const filtered = computed(() =>
  projects.value.filter((item) =>
    item.name.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()),
  ),
)
async function load() {
  loading.value = true
  try {
    projects.value = await request<SavedProject[]>('/projects')
  } catch (cause) {
    store.error = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}
onActivated(load)
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
  const result = await store.mutate('/project/open', { path })
  if (result) await router.push('/samples')
}
function date(value: string) {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
</script>

<template>
  <section>
    <div class="page-title">
      <div>
        <p class="eyebrow">PROJECTS / 项目</p>
        <h1>从一个实验项目开始</h1>
        <p>组织样本、检查原始谱，并将每一步分析保存在同一个项目中。</p>
      </div>
    </div>
    <div class="overview-grid">
      <form class="card create-project" @submit.prevent="create">
        <span class="section-tag">新实验</span>
        <h2>创建项目</h2>
        <p>原始文件仅引用，保留在服务器原位置。</p>
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
          创建并添加样本 <span>→</span>
        </button>
      </form>
      <div class="card workflow-note">
        <span class="section-tag">工作流程</span>
        <h2>从原始谱到可追溯的结果</h2>
        <ol>
          <li>添加样本与实验分组</li>
          <li>检查原始谱，设置提取参数</li>
          <li>审核提取结果，再进行预处理与分析</li>
          <li>主动保存项目，下载需要的结果</li>
        </ol>
        <p class="muted">六步工作流共用同一个数据集；提取后人工审核，项目由你主动保存。</p>
      </div>
    </div>
    <section class="card project-list">
      <div class="section-heading">
        <div>
          <h2>
            已保存项目 <span class="count">{{ projects.length }}</span>
          </h2>
          <p>打开项目继续工作，当前未保存修改会被放弃。</p>
        </div>
        <div class="actions">
          <input v-model="search" aria-label="搜索项目" placeholder="搜索项目名称" /><button
            @click="load"
            :disabled="store.busy || loading"
          >
            刷新
          </button>
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
              <th>样本数</th>
              <th>保存时间（北京时间）</th>
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
              <td>{{ item.samples }}</td>
              <td>{{ date(item.saved_at) }}</td>
              <td><button :disabled="store.busy" @click="open(item.path)">打开项目 →</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="storage-path">项目根目录：{{ store.configuration?.project_root }}</p>
    </section>
    <SavedItems @changed="load" />
  </section>
</template>
