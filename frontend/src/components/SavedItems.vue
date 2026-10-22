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
interface RetentionPlan {
  project: string
  generated_at: string
  policy: string
  scope: string
  warnings: string[]
  candidate_bytes: number
  selected_bytes: number
  items: {
    kind: string
    paths: string[]
    status: 'candidate' | 'protected' | 'unknown'
    reasons: string[]
    files: number | null
    bytes: number | null
    modified_at: string | null
    selected_for_cleanup: boolean
    policy_reasons: string[]
  }[]
}
const retention = ref<RetentionPlan>()
const minAgeDays = ref<number | ''>('')
const keepLatest = ref<number | ''>('')
let retentionGeneration = 0
watch([selected, minAgeDays, keepLatest, () => store.current?.workspace_id], () => {
  retentionGeneration++
  retention.value = undefined
})
async function inspectRetention() {
  const generation = ++retentionGeneration
  const project = selected.value
  const workspace = store.current?.workspace_id
  retention.value = undefined
  const value = await store.inspect<RetentionPlan>('/saved/retention', {
    root: '项目结果',
    path: project,
    min_age_days: minAgeDays.value === '' ? null : minAgeDays.value,
    keep_latest: keepLatest.value === '' ? null : keepLatest.value,
  })
  if (
    generation === retentionGeneration &&
    project === selected.value &&
    workspace === store.current?.workspace_id
  )
    retention.value = value
}
function downloadRetention() {
  if (!retention.value) return
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(retention.value, null, 2)], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = 'scmm-retention-plan.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
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
      <button :disabled="store.busy" @click="refresh" class="preview">刷新管理列表</button>
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
      <button class="danger" :disabled="store.busy || !selected" @click="makePlan(true)">
        查看项目删除计划
      </button>
      <div class="field-grid">
        <label>
          <FieldLabel
            name="最小年龄（天）"
            help-key="min_age_days"
            text="按产物内最新修改时间计算；空白不按年龄筛选。"
          />
          <input
            v-model.number="minAgeDays"
            aria-label="最小年龄（天）"
            type="number"
            min="0"
            step="1"
            :disabled="store.busy"
            placeholder="空白：不按年龄筛选"
          />
        </label>
        <label>
          <FieldLabel
            name="每类至少保留最新数量"
            help-key="keep_latest"
            text="快照、预览、共同特征缓存分别排序；边界同时间项全部保留。空白不按数量筛选。"
          />
          <input
            v-model.number="keepLatest"
            aria-label="每类至少保留最新数量"
            type="number"
            min="0"
            step="1"
            :disabled="store.busy"
            placeholder="空白：不按数量筛选"
          />
        </label>
      </div>
      <p class="muted">
        均空白时全部保留；同时填写时，清理建议须同时满足年龄和数量规则。保护项始终保留，此处不执行删除。
      </p>
      <button class="preview" :disabled="store.busy || !selected" @click="inspectRetention">
        查看快照与缓存保留计划
      </button>
      <div v-if="retention" class="alert" aria-label="快照与缓存保留计划">
        <p>{{ retention.policy }}</p>
        <p>{{ retention.scope }}</p>
        <p>
          生成时间：{{
            new Date(retention.generated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
          }}（北京时间）
        </p>
        <p>
          只读检查，生成后状态仍可能变化。候选逻辑大小
          {{ (retention.candidate_bytes / 1024 / 1024).toFixed(2) }} MiB；本次释放 0 字节。
        </p>
        <p>
          其中符合策略的待审阅建议 {{ (retention.selected_bytes / 1024 / 1024).toFixed(2) }} MiB。
        </p>
        <p v-for="warning in retention.warnings" :key="warning">{{ warning }}</p>
        <div class="data-table">
          <table>
            <thead>
              <tr>
                <th>用途 / 路径</th>
                <th>结论</th>
                <th>原因</th>
                <th>策略判断 / 最新修改时间</th>
                <th>文件数 / 大小</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in retention.items" :key="item.paths.join('|')">
                <td>
                  {{ item.kind }}
                  <div v-for="value in item.paths" :key="value">{{ value }}</div>
                </td>
                <td>
                  {{
                    {
                      candidate: '人工审阅候选',
                      protected: '保留（受保护）',
                      unknown: '保留（待核实）',
                    }[item.status]
                  }}
                </td>
                <td>{{ item.reasons.join('；') }}</td>
                <td>
                  {{ item.selected_for_cleanup ? '待审阅清理建议' : '保留' }}：{{
                    item.policy_reasons.join('；')
                  }}
                  <div>
                    {{
                      item.modified_at
                        ? new Date(item.modified_at).toLocaleString('zh-CN', {
                            timeZone: 'Asia/Shanghai',
                          })
                        : '时间未知'
                    }}
                  </div>
                </td>
                <td>
                  {{ item.files ?? '—' }} /
                  {{ item.bytes === null ? '—' : `${(item.bytes / 1024 / 1024).toFixed(2)} MiB` }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!retention.items.length">当前没有快照或缓存条目。</p>
        <button class="download" :disabled="store.busy" @click="downloadRetention">
          下载只读保留计划
        </button>
      </div>
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
      <button class="danger" :disabled="store.busy || !path" @click="makePlan()">
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
