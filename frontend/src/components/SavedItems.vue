<script setup lang="ts">
import { ref, watch, onActivated } from 'vue'
import { request } from '../api/client'
import { useWorkspace } from '../stores/workspace'
import { useAuth } from '../stores/auth'
import FileBrowser from './FileBrowser.vue'
import type { SavedProject } from '../api/types'
const store = useWorkspace()
const auth = useAuth()
const emit = defineEmits<{ changed: [] }>()
const projects = ref<SavedProject[]>([]),
  selected = ref(''),
  root = ref('项目结果'),
  path = ref(''),
  trash = ref<{ entry: string; path: string; deleted_at: string; kind: string }[]>([])
const plan = ref<{
  token: string
  path: string
  kind: string
  files: number
  bytes: number
  role?: string
  detail?: string
  project_name?: string
  protection?: string
}>()
onActivated(() => void refresh())
async function refresh() {
  try {
    projects.value = await request('/projects')
  } catch (cause) {
    store.error = String(cause)
  }
  const value = await store.read<typeof trash.value>('/saved/trash')
  if (value) trash.value = value
}
watch(
  () => store.current?.workspace_id,
  () => void refresh(),
  { immediate: true },
)
watch([selected, root, path], () => (plan.value = undefined))
async function makePlan(project = false) {
  plan.value = await store.inspect('/saved/plan', {
    root: project ? '项目结果' : root.value,
    path: project ? selected.value : path.value,
  })
}
async function move() {
  if (!plan.value) return
  const result = await store.inspect('/saved/move', { token: plan.value.token })
  if (result) {
    plan.value = undefined
    selected.value = ''
    path.value = ''
    await refresh()
    emit('changed')
    store.notice = '所选内容已移入共享回收区。'
  }
}
async function restore(entry: string) {
  const result = await store.inspect('/saved/restore', { entry })
  if (result) {
    await refresh()
    emit('changed')
    store.notice = '已恢复到原位置。'
  }
}
async function clear() {
  const result = await store.inspect<number>('/saved/clear')
  if (result !== undefined) {
    await refresh()
    store.notice = `已永久清空 ${result} 个回收条目。`
  }
}
</script>
<template>
  <section class="card">
    <div class="section-heading">
      <div>
        <h2>已保存内容与回收区</h2>
        <p>先查看删除计划，再直接执行。当前打开项目、任务及被引用产物受到保护。</p>
      </div>
      <button :disabled="store.busy" @click="refresh">刷新管理列表</button>
    </div>
    <details>
      <summary>管理已保存项目 / 结果</summary>
      <div class="field-grid">
        <label
          ><FieldLabel name="已保存项目" /><select
            v-model="selected"
            aria-label="已保存项目"
            :disabled="store.busy"
          >
            <option value="">请选择要管理的项目</option>
            <option v-for="p in projects" :key="p.path" :value="p.path">
              {{ p.name }} · {{ p.path.split('/').at(-1) }}
            </option>
          </select></label
        >
      </div>
      <button class="preview" :disabled="store.busy || !selected" @click="makePlan(true)">
        查看项目删除计划
      </button>
      <details>
        <summary>浏览并选择结果文件或目录</summary>
        <FileBrowser
          :roots="store.configuration?.results ?? []"
          kind="results"
          purpose="manage"
          :disabled="store.busy"
          @selected="
            (label, values) => {
              root = label
              path = values[0] ?? ''
            }
          "
        />
      </details>
      <div class="field-grid">
        <label
          ><FieldLabel name="结果存储" /><select
            aria-label="结果存储"
            v-model="root"
            :disabled="store.busy"
          >
            <option v-for="r in store.configuration?.results" :key="r.label">{{ r.label }}</option>
          </select></label
        ><label
          ><FieldLabel name="结果相对路径 / 完整路径" /><input
            aria-label="结果相对路径 / 完整路径"
            v-model="path"
            :disabled="store.busy"
            placeholder="仅已识别结果目录或 H5AD"
        /></label>
      </div>
      <button class="preview" :disabled="store.busy || !path" @click="makePlan()">
        查看结果删除计划
      </button>
      <div v-if="plan" class="alert">
        <p>
          {{ plan.project_name ? `${plan.project_name} · ` : '' }}{{ plan.role || plan.kind }} ·
          {{ plan.files }} 文件 · {{ (plan.bytes / 1024 / 1024).toFixed(2) }} MiB<br />{{
            plan.path
          }}
        </p>
        <p>{{ plan.detail }}</p>
        <button class="danger" :disabled="store.busy" @click="move">移入回收区</button>
      </div>
    </details>
    <details>
      <summary>共享回收区（{{ trash.length }}）</summary>
      <p class="muted">回收区仍占用磁盘。永久清空直接执行且不可恢复，不出现二次确认。</p>
      <div class="data-table">
        <table>
          <thead>
            <tr>
              <th>内容</th>
              <th>原路径</th>
              <th>时间（北京时间）</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in trash" :key="entry.entry">
              <td>{{ entry.kind }}</td>
              <td>{{ entry.path }}</td>
              <td>
                {{
                  new Date(entry.deleted_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
                }}
              </td>
              <td>
                <button class="restore" :disabled="store.busy" @click="restore(entry.entry)">
                  恢复
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <button
        v-if="auth.admin"
        class="danger"
        :disabled="store.busy || !trash.length"
        @click="clear"
      >
        永久清空全部共享回收条目
      </button>
    </details>
  </section>
</template>
