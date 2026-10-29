<script setup lang="ts">
import { formatTime } from '../help/time'
import { ref, watch } from 'vue'
import { useReadScope } from '../api/readScope'
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
  trash = ref<{ entry: string; path: string; deleted_at: string; kind: string; status?: string }[]>(
    [],
  )
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
  policy_parameters: { min_age_days: number | null; keep_latest: number | null }
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
const intervalMinutes = ref<number | ''>('')
const retentionRunLabels: Record<string, string> = {
  completed: '已归档',
  retained: '全部保留',
  skipped: '本轮跳过',
  failed: '失败并停用',
  interrupted: '中断待核实',
  cancelled: '已停止本轮',
  running: '运行中',
}
type PolicyStatus = {
  policy: {
    enabled: boolean
    authorized_by: string
    interval_minutes: number
    next_at: number
    options: { min_age_days: number | null; keep_latest: number | null }
  } | null
  runs: { id: string; status: string; started_at: number; message: string }[]
  error: string | null
}
const policyStatus = ref<PolicyStatus>()
let policyStatusGeneration = 0
type RetentionPolicyReview = {
  token: string
  project: string
  interval_minutes: number
  authorization: string
  advice: RetentionPlan
}
const listScope = useReadScope(
  () => store.current?.workspace_id,
  () => void refresh(),
)
const policyScope = useReadScope(() => [store.current?.workspace_id, selected.value])
const planScope = useReadScope(() => [
  store.current?.workspace_id,
  selected.value,
  root.value,
  path.value,
])
const retentionScope = useReadScope(() => [
  store.current?.workspace_id,
  selected.value,
  minAgeDays.value,
  keepLatest.value,
  intervalMinutes.value,
])
const policyReview = ref<RetentionPolicyReview>()
type CleanupExecutionPlan = {
  token: string
  files: number
  bytes: number
  members: { path: string }[]
}
const cleanupPlan = ref<CleanupExecutionPlan>()
let retentionGeneration = 0
watch(
  [
    selected,
    minAgeDays,
    keepLatest,
    intervalMinutes,
    () => store.current?.workspace_id,
    () => store.current?.revision,
  ],
  () => {
    retentionGeneration++
    retention.value = undefined
    cleanupPlan.value = undefined
    policyReview.value = undefined
  },
)
watch([selected, () => store.current?.workspace_id], () => {
  policyStatusGeneration++
  policyStatus.value = undefined
  void loadPolicy()
})
async function loadPolicy() {
  if (!auth.admin || !selected.value || !store.current) return
  const project = selected.value
  const generation = ++policyStatusGeneration
  const ticket = policyScope.begin()
  const accept = () => ticket() && generation === policyStatusGeneration
  const workspace = store.current.workspace_id
  const value = await store.read<PolicyStatus>(
    '/saved/retention-policy/status',
    {
      revision: store.current.revision,
      root: '项目结果',
      path: project,
    },
    accept,
  )
  if (
    accept() &&
    generation === policyStatusGeneration &&
    selected.value === project &&
    store.current?.workspace_id === workspace
  )
    policyStatus.value = value
}
async function reviewPolicy() {
  const generation = ++retentionGeneration
  const ticket = retentionScope.begin()
  const accept = () => ticket() && generation === retentionGeneration
  policyReview.value = undefined
  const value = await store.inspect<RetentionPolicyReview>(
    '/saved/retention-policy/review',
    {
      root: '项目结果',
      path: selected.value,
      min_age_days: minAgeDays.value === '' ? null : minAgeDays.value,
      keep_latest: keepLatest.value === '' ? null : keepLatest.value,
      interval_minutes: intervalMinutes.value,
    },
    accept,
  )
  if (accept()) {
    policyReview.value = value
    retention.value = value?.advice
    cleanupPlan.value = undefined
  }
}
async function enablePolicy() {
  if (!policyReview.value) return
  const token = policyReview.value.token
  const generation = ++policyStatusGeneration
  policyReview.value = undefined
  const result = await store.inspect<PolicyStatus>('/saved/retention-policy/enable', { token })
  if (result && generation === policyStatusGeneration) {
    policyStatus.value = result
    store.notice = '已启用持续自动保留；首轮将在所设间隔后检查，仅移入回收区。'
  }
}
async function disablePolicy() {
  const generation = ++policyStatusGeneration
  const result = await store.inspect<PolicyStatus>('/saved/retention-policy/disable', {
    root: '项目结果',
    path: selected.value,
  })
  if (result && generation === policyStatusGeneration) {
    policyReview.value = undefined
    policyStatus.value = result
    store.notice = '已停用自动保留；当前复制会在安全检查点停止，已归档内容保留。'
  }
}
async function prepareCleanup() {
  const generation = ++retentionGeneration
  const ticket = retentionScope.begin()
  const accept = () => ticket() && generation === retentionGeneration
  cleanupPlan.value = undefined
  const value = await store.inspect<CleanupExecutionPlan>(
    '/saved/retention-plan',
    {
      root: '项目结果',
      path: selected.value,
      min_age_days: minAgeDays.value === '' ? null : minAgeDays.value,
      keep_latest: keepLatest.value === '' ? null : keepLatest.value,
    },
    accept,
  )
  if (accept()) cleanupPlan.value = value
}
async function executeCleanup() {
  if (!cleanupPlan.value) return
  const token = cleanupPlan.value.token
  const workspace = store.current?.workspace_id
  cleanupPlan.value = undefined
  const result = await store.inspect('/saved/retention-move', { token })
  if (workspace !== store.current?.workspace_id) return
  retention.value = undefined
  await refresh()
  if (result) {
    emit('changed')
    store.notice = '策略清单已移入共享回收区，尚未释放磁盘空间。'
  }
}
async function inspectRetention() {
  const generation = ++retentionGeneration
  const ticket = retentionScope.begin()
  const accept = () => ticket() && generation === retentionGeneration
  const project = selected.value
  const workspace = store.current?.workspace_id
  retention.value = undefined
  cleanupPlan.value = undefined
  const value = await store.inspect<RetentionPlan>(
    '/saved/retention',
    {
      root: '项目结果',
      path: project,
      min_age_days: minAgeDays.value === '' ? null : minAgeDays.value,
      keep_latest: keepLatest.value === '' ? null : keepLatest.value,
    },
    accept,
  )
  if (
    accept() &&
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
async function refresh() {
  const accept = listScope.begin()
  const value = await store.readResource<SavedProject[]>('/projects', { accept })
  if (!accept()) return
  if (value) {
    projects.value = value
    if (!value.some((project) => project.path === selected.value)) selected.value = ''
  }
  const entries = await store.read<typeof trash.value>('/saved/trash', undefined, accept)
  if (accept() && entries) trash.value = entries
}
watch(
  () => store.current?.workspace_id,
  () => void refresh(),
  { immediate: true },
)
watch([selected, root, path], () => (plan.value = undefined))
async function makePlan(project = false) {
  const accept = planScope.begin()
  const value = await store.inspect<NonNullable<typeof plan.value>>(
    '/saved/plan',
    {
      root: project ? '项目结果' : root.value,
      path: project ? selected.value : path.value,
    },
    accept,
  )
  if (accept()) plan.value = value
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
    retention.value = undefined
    cleanupPlan.value = undefined
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
defineExpose({ refresh })
</script>
<template>
  <section class="card">
    <div class="section-heading">
      <div>
        <h2>统一回收站与高级保留策略</h2>
        <p>先查看删除计划，再直接执行。当前打开项目、任务及被引用产物受到保护。</p>
      </div>
      <button :disabled="store.busy" @click="refresh" class="preview">刷新管理列表</button>
    </div>
    <details>
      <summary>高级：保留策略与外部结果</summary>
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
      <p class="muted">
        项目请在上方项目列表管理；批次、预览缓存、保存记录和独立导出在各自页面管理。这里保留跨项目保留策略与外部结果管理。
      </p>
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
      <details v-if="auth.admin" aria-label="持续自动保留">
        <summary>持续自动保留（默认关闭）</summary>
        <p>
          仅针对所选项目，沿用上方显式年龄/数量规则。审阅并启用后，每轮会重新选择未来符合规则的无引用产物；引用、工作区、任务及未知状态保护始终优先。仅移入回收区，不永久清空。服务重启后保留设置。
        </p>
        <label
          ><FieldLabel
            name="自动保留检查间隔（分钟）"
            help-key="interval_minutes"
            text="必须显式填写 1–525600 的整数分钟；首轮在该间隔后运行，错过的周期合并为一轮。"
          />
          <input
            v-model.number="intervalMinutes"
            aria-label="自动保留检查间隔（分钟）"
            type="number"
            min="1"
            max="525600"
            step="1"
            :disabled="store.busy"
            placeholder="请显式填写"
          />
        </label>
        <button
          class="preview"
          :disabled="store.busy || !selected || intervalMinutes === ''"
          @click="reviewPolicy"
        >
          审阅自动保留规则
        </button>
        <button class="preview" :disabled="store.busy || !selected" @click="loadPolicy">
          刷新自动保留状态
        </button>
        <div v-if="policyReview" class="alert" aria-label="自动保留规则审阅">
          <p>{{ policyReview.authorization }}</p>
          <p>
            {{ policyReview.project }} · 每 {{ policyReview.interval_minutes }} 分钟检查；最小年龄
            {{ policyReview.advice.policy_parameters?.min_age_days ?? '不限制' }} 天，每类保留最新
            {{ policyReview.advice.policy_parameters?.keep_latest ?? '不限制' }} 项。
          </p>
          <p>
            当前建议
            {{ (policyReview.advice.selected_bytes / 1024 / 1024).toFixed(2) }}
            MiB；开启后也适用于未来产物，并非只执行这次清单。
          </p>
          <button class="primary" :disabled="store.busy" @click="enablePolicy">
            启用持续自动保留
          </button>
        </div>
        <div v-if="policyStatus" aria-label="自动保留状态">
          <p>
            {{ policyStatus.policy?.enabled ? '已启用' : '已停用 / 尚未设置'
            }}<template v-if="policyStatus.policy?.enabled">
              · 每 {{ policyStatus.policy.interval_minutes }} 分钟检查；下次检查
              {{ formatTime(policyStatus.policy.next_at * 1000) }}（北京时间）</template
            >
          </p>
          <p v-if="policyStatus.policy">
            启用管理员：{{ policyStatus.policy.authorized_by }}。 已生效规则：最小年龄
            {{ policyStatus.policy.options.min_age_days ?? '不限制' }} 天，每类保留最新
            {{ policyStatus.policy.options.keep_latest ?? '不限制' }} 项；上方输入只是待审阅草稿。
          </p>
          <p v-if="policyStatus.error">{{ policyStatus.error }}</p>
          <button
            class="danger"
            :disabled="store.busy || !policyStatus.policy?.enabled"
            @click="disablePolicy"
          >
            停用自动保留
          </button>
          <ul>
            <li v-for="run in policyStatus.runs" :key="run.id">
              {{ formatTime(run.started_at * 1000) }}
              · {{ retentionRunLabels[run.status] ?? run.status }}：{{ run.message }}
            </li>
          </ul>
        </div>
      </details>
      <button
        class="preview"
        :disabled="store.busy || !retention?.selected_bytes"
        @click="prepareCleanup"
      >
        查看策略清理执行计划
      </button>
      <div v-if="cleanupPlan" class="alert" aria-label="策略清理执行计划">
        <p>
          仅处理下列清单：{{ cleanupPlan.files }} 文件 ·
          {{ (cleanupPlan.bytes / 1024 / 1024).toFixed(2) }}
          MiB。先完整复制并校验恢复副本，再移走原件；执行时重新核对状态，回收区仍占磁盘。
        </p>
        <ul>
          <li v-for="member in cleanupPlan.members" :key="member.path">{{ member.path }}</li>
        </ul>
        <button class="danger" :disabled="store.busy" @click="executeCleanup">
          将策略清单移入回收区
        </button>
      </div>
      <div v-if="retention" class="alert" aria-label="快照与缓存保留计划">
        <p>{{ retention.policy }}</p>
        <p>{{ retention.scope }}</p>
        <p>生成时间：{{ formatTime(retention.generated_at) }}（北京时间）</p>
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
                    {{ item.modified_at ? formatTime(item.modified_at) : '时间未知' }}
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
      <p class="muted">
        回收区仍占用磁盘。中断的策略清理须先恢复，完成前禁止永久清空。永久清空直接执行且不可恢复，不出现二次确认。
      </p>
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
              <td>
                {{ entry.kind }}
                <div v-if="entry.status === 'prepared' || entry.status === 'restoring'">
                  未完成，请先恢复
                </div>
              </td>
              <td>{{ entry.path }}</td>
              <td>
                {{ formatTime(entry.deleted_at) }}
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
