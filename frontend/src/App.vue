<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { resetScrollPositions } from './router'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspace } from './stores/workspace'
import { useAuth } from './stores/auth'
import { startMaintenance } from './api/maintenance'
import { useReadScope } from './api/readScope'
import { serialPolling } from './api/polling'
import { startPresence, updatePresence } from './api/presence'
import LoginPanel from './components/LoginPanel.vue'
import AssistantPanel from './features/assistant/AssistantPanel.vue'
import DocumentationPanel from './features/documentation/DocumentationPanel.vue'
import { modules, moduleForPath } from './features/modules/modules'
import { workspaceBlob, saveBlob } from './api/workspaceDownload'
import CsvExportDialog from './components/CsvExportDialog.vue'
import { clearPendingViews } from './api/viewState'
import type { Job } from './api/types'
import type { IonTask } from './api/ions'

const store = useWorkspace()
const auth = useAuth()
const route = useRoute()
const router = useRouter()
const navigationOpen = ref(false)
const assistantOpen = ref(false)
const standalone = computed(() => ['/admin/monitor', '/account'].includes(route.path))
let presence: ReturnType<typeof startPresence> | undefined
let stopMaintenance: (() => void) | undefined
let workspaceUser = ''
async function connect() {
  if (!auth.user || auth.user.must_change) return
  await presence?.ready
  if (workspaceUser !== auth.user.id) store.reset()
  workspaceUser = auth.user.id
  if (standalone.value) return
  if (store.current) await store.refresh()
  if (!store.current) await store.start()
}
watch(
  () => (auth.user && !auth.user.must_change ? auth.user.id : null),
  (identity) => {
    if (identity) void connect()
  },
)
async function logout() {
  await store.run(
    async () => {
      store.release()
      await auth.logout()
      store.reset()
    },
    '',
    { label: '退出登录', phase: 'submitting' },
  )
}
watch(
  () => route.path,
  () => {
    if (!standalone.value && auth.user && !store.current) void connect()
  },
)
watch(
  () => [route.path, auth.user?.id, auth.user?.must_change, store.current?.workspace_id],
  () => {
    updatePresence(route.path, !!auth.user && !auth.user.must_change, store.current?.workspace_id)
  },
)
onMounted(() => {
  presence = startPresence()
  stopMaintenance = startMaintenance(router)
  void presence.ready.then(() => auth.refresh())
  workflowPolling.start()
})
onUnmounted(() => {
  workflowPolling.stop()
  presence?.stop()
  stopMaintenance?.()
})
const activeModule = computed(() => moduleForPath(route.path))
const pageGuide = computed(() => {
  const guides: Record<string, [string, string]> = {
    '/cell-extraction': [
      '选择原始文件或提取交换包，进入细胞提取。',
      '交换包保留提取来源与参数。导入后可在左侧导航继续预览和提取。',
    ],
    '/samples': [
      '添加原始文件，填写样本名称与实验分组。',
      '文件保留在授权原始目录。名称、分组、受试者和批次可在此修改。',
    ],
    '/raw': [
      '预览当前样本的色谱与质谱，设置提取参数。',
      '参数以十进制显示。切换信号全宽可查看 TIC、EIC、合并谱、单扫描及细胞窗口。图形与提取范围分别设置。',
    ],
    '/extraction': [
      '检查逐样本参数，执行提取并审核纳入结果。',
      '逐样本编辑完整参数，也可按组对照。应用草稿后重新检查输入。每行的信号可展开和收起。',
    ],
    '/annotation': [
      '选择注释数据库，在谱图中检查候选与关联峰。',
      '可先看完整特征谱并点峰。右侧核对候选、关系和证据，定量分支在定量视图显式启用。',
    ],
    '/annotation/evidence': [
      '查看注释证据，或导入外部注释与实测二级谱。',
      '选中证据可查看匹配碎片，并关联到指定峰、候选或离子组。',
    ],
    '/ions': [
      '查看测量来源、离子关系及其定量表示。',
      '预览后可明确选择统计输入。查看测量峰时仍可回到候选与关系审核。',
    ],
    '/statistics': [
      '选择定量矩阵来源，进入统计分析。',
      '可使用当前项目数据或导入交换包、H5AD、开放矩阵表。特征注释随定量数据提供时可用于结果展示。',
    ],
    '/data-check': [
      '检查矩阵维度、样本信息与数据完整性。',
      '检查包括非有限值、全零观测或特征、重复标识及缺失分组。查看提示后可在数据编辑器补充元数据或进入预处理。',
    ],
    '/data-editor': [
      '编辑样本信息、特征显示名和分析纳入范围。',
      '定量矩阵以只读表格预览。样本信息和特征显示名的修改保留记录，筛选标签用于调整分析范围。',
    ],
    '/preprocess': [
      '依次处理异常值、筛选和归一化／标准化。',
      '选择步骤展开对应参数。完成筛选后默认跳过零值插补，也可主动选择插补。运行前检查当前矩阵与处理参数。',
    ],
    '/analysis': [
      '选择分析方法，设置参数并查看结果。',
      '方法按用途分组。计算结果与输入数据及参数关联，图表旁可下载当前视图或相应数值。',
    ],
  }
  return (
    guides[route.path] ?? [
      activeModule.value?.subtitle ?? '',
      activeModule.value?.description ?? '',
    ]
  )
})
const expandedModule = ref('')
watch(
  () => route.path,
  () => {
    if (activeModule.value) expandedModule.value = activeModule.value.key
    navigationOpen.value = false
  },
  { immediate: true },
)
const ionTask = ref<Pick<IonTask, 'id' | 'status'>>()
const previewTask = ref<Job>()
const taskReads = useReadScope(() => [
  store.current?.workspace_id,
  store.project?.path,
  store.current?.revision,
])
async function refreshTasks() {
  if (standalone.value || store.busy || !store.project) return
  const accept = taskReads.begin()
  const [tasks] = await Promise.all([
    store.read<{ ion: Pick<IonTask, 'id' | 'status'> | null; preview: Job | null }>(
      '/tasks/active',
      undefined,
      accept,
    ),
    route.path === '/extraction' ? undefined : store.refreshBatches(),
  ])
  if (!accept()) return
  ionTask.value = tasks?.ion ?? undefined
  previewTask.value = tasks?.preview ?? undefined
}
const workflowPolling = serialPolling(refreshTasks, 2000, (cause) => {
  store.error = cause instanceof Error ? cause.message : String(cause)
})
watch(
  () => store.project?.path,
  () => {
    resetScrollPositions()
    ionTask.value = undefined
    previewTask.value = undefined
    if (!standalone.value) void store.refreshBatches()
  },
)
const extractionStatus = computed(() => {
  if (!store.project) return ''
  if (store.batches?.some((batch) => ['queued', 'running'].includes(batch.status))) return '运行中'
  if (store.project.dataset) return '已有数据'
  if (store.batches?.some((batch) => batch.samples.some((sample) => sample.status === 'succeeded')))
    return '待审核'
  return '未开始'
})
const activeBatch = computed(() =>
  store.batches?.find((batch) => ['queued', 'running'].includes(batch.status)),
)
const batchProgress = computed(() => {
  const batch = activeBatch.value
  if (!batch) return ''
  const finished = batch.samples.filter((sample) =>
    ['succeeded', 'failed'].includes(sample.status),
  ).length
  return `提取 ${finished}/${batch.samples.length} · ${batch.stop_requested ? '处理完当前样本后停止' : batch.message || batch.stage || '运行中'}`
})
const activeProgress = computed(() =>
  store.busy
    ? store.operationMessage
    : ionTask.value
      ? '离子归组正在运行'
      : previewTask.value
        ? `细胞预览 · ${previewTask.value.message}`
        : activeBatch.value
          ? batchProgress.value
          : store.task,
)
const stoppable = computed(() => !!(ionTask.value || previewTask.value || activeBatch.value))
const stopping = computed(
  () =>
    !ionTask.value &&
    (previewTask.value
      ? previewTask.value.status === 'stopping'
      : activeBatch.value?.stop_requested),
)
async function stopCurrent() {
  if (store.busy || stopping.value) return
  if (ionTask.value) {
    await store.command('/ions/cancel', { job_id: ionTask.value.id })
  } else if (previewTask.value) {
    await store.command('/raw/preview/stop', { job_id: previewTask.value.id })
  } else if (activeBatch.value) {
    await store.mutate(
      '/extraction/stop',
      { path: activeBatch.value.path },
      'POST',
      '提取将在当前样本结束后停止。',
    )
    await store.refreshBatches()
  }
  await refreshTasks()
}
const checkedDatasets = ref(new Set<string>())
const checkIdentity = computed(() =>
  JSON.stringify([
    store.current?.workspace_id,
    store.project?.path,
    store.project?.dataset?.id,
    store.project?.dataset?.revision,
  ]),
)
watch(
  () => [route.path, checkIdentity.value],
  () => {
    if (route.path === '/data-check' && store.project?.dataset)
      checkedDatasets.value.add(checkIdentity.value)
  },
  { immediate: true },
)
const workflowState = ref<Record<string, boolean>>({})
const workflowReads = useReadScope(() => [
  store.current?.workspace_id,
  store.current?.revision,
  store.project?.path,
  store.project?.dataset?.id,
  store.project?.dataset?.revision,
])
watch(
  () =>
    JSON.stringify([
      store.current?.workspace_id,
      store.current?.revision,
      store.project?.path,
      store.project?.dataset?.id,
      store.project?.dataset?.revision,
    ]),
  async () => {
    workflowState.value = {}
    if (!store.project?.dataset) return
    const accept = workflowReads.begin()
    const info = await store.read<typeof workflowState.value>(
      '/analysis/workflow-status',
      undefined,
      accept,
    )
    if (accept() && info) workflowState.value = info
  },
)
function stepCompleted(path: string) {
  if (!store.project) return false
  if (path === '/data-check') return checkedDatasets.value.has(checkIdentity.value)
  if (path === '/samples') return store.project.manifest.samples.some((sample) => !!sample.path)
  if (path === '/raw') return !!store.project.manifest.manual_parameters
  if (path === '/extraction')
    return !!store.batches?.some((batch) =>
      batch.samples.some((sample) => sample.status === 'succeeded'),
    )
  if (path in workflowState.value) return workflowState.value[path]
  if (path === '/cell-extraction')
    return store.project.manifest.samples.some((sample) => !!sample.path)
  if (path === '/statistics') return !!store.project.dataset?.cells
  return false
}
const workflow = computed(() => activeModule.value?.steps ?? [])
const stepIndex = computed(() => workflow.value.findIndex((step) => step.path === route.path))
const previousStep = computed(() =>
  stepIndex.value === 0
    ? { path: '/projects', name: '项目首页' }
    : workflow.value[stepIndex.value - 1],
)
const nextStep = computed(
  () =>
    workflow.value[stepIndex.value + 1] ??
    (activeModule.value?.key === 'extraction'
      ? { path: '/statistics', name: '选择统计分析数据' }
      : { path: '/results', name: '结果与保存' }),
)
const nextBlocked = computed(
  () =>
    !store.project ||
    (['/data-check', '/data-editor', '/preprocess', '/analysis'].includes(nextStep.value.path) &&
      !store.project.dataset?.cells),
)
const nextHelp = computed(() =>
  !store.project
    ? '请先创建或打开项目。'
    : nextBlocked.value
      ? '请先审核纳入提取结果，或导入已有定量矩阵，建立当前数据集。'
      : '',
)
async function exportConflictingProject() {
  const current = store.current
  const module = activeModule.value?.key ?? 'statistics'
  if (!current?.project) return
  await store.run(
    async (operation) => {
      const blob = await workspaceBlob(
        `/exchange/${module}/export?format=package&revision=${current.revision}`,
        {
          workspace: current.workspace_id,
          isCurrent: () => operation.isCurrent() && store.current === current,
        },
      )
      saveBlob(blob, 'current-workspace.scmm-exchange.zip')
    },
    '已下载当前工作区。',
    { label: '导出当前工作区', phase: 'reading' },
  )
}
const viewGeneration = ref(0)
async function openDiskProject() {
  const path = store.project?.path
  if (!path) return
  const result = await store.mutate('/project/open', { path }, 'POST', '已打开磁盘上的项目版本。')
  if (!result) return
  clearPendingViews()
  store.drafts = {}
  store.analysisDraft = null
  viewGeneration.value++
  const data = result.project?.dataset
  await router.push(
    data?.quantitation_available === false ? '/annotation' : data ? '/preprocess' : '/samples',
  )
}
</script>

<template>
  <main v-if="!auth.ready" class="card">正在检查登录状态…</main>
  <LoginPanel v-else-if="!auth.user || auth.user.must_change" />
  <div
    v-else
    class="workbench"
    :class="activeModule ? `module-${activeModule.key}` : 'module-overview'"
    :key="auth.user.id"
  >
    <a class="skip-to-content" href="#main-content">跳到工作内容</a>
    <aside class="sidebar" :class="{ 'navigation-open': navigationOpen }">
      <RouterLink to="/projects" class="brand" aria-label="scMM 项目首页">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        <span>scMM<small>单细胞质谱工作台</small></span>
      </RouterLink>
      <button
        class="mobile-nav-toggle"
        :aria-expanded="navigationOpen"
        aria-controls="workflow-menu"
        @click="navigationOpen = !navigationOpen"
      >
        {{ navigationOpen ? '收起导航' : '流程与账号' }}
      </button>
      <p class="nav-caption">工作流程</p>
      <nav id="workflow-menu" aria-label="工作流程">
        <RouterLink to="/projects" class="nav-home">项目首页</RouterLink>
        <div
          v-for="module in modules"
          :key="module.key"
          class="nav-module"
          :class="[`nav-${module.key}`, { 'nav-module-current': activeModule?.key === module.key }]"
        >
          <button
            :aria-label="module.name"
            :aria-expanded="expandedModule === module.key"
            :aria-controls="`steps-${module.key}`"
            @click="expandedModule = expandedModule === module.key ? '' : module.key"
          >
            <span class="nav-module-name">{{ module.name }}</span>
            <span class="nav-chevron" aria-hidden="true"></span>
          </button>
          <div
            v-show="expandedModule === module.key"
            :id="`steps-${module.key}`"
            class="module-steps"
          >
            <RouterLink
              v-for="step in module.steps"
              :key="step.path"
              :class="{
                'current-step': route.path === step.path,
                'step-completed': stepCompleted(step.path),
              }"
              :to="step.path"
              >{{ step.name
              }}<small v-if="step.path === '/extraction'" class="nav-step-state">{{
                extractionStatus
              }}</small></RouterLink
            >
          </div>
        </div>
        <RouterLink to="/results">结果与保存</RouterLink>
      </nav>
      <div
        class="task-note progress-panel"
        :title="activeProgress"
        :class="{ running: store.busy || stoppable }"
      >
        <strong>任务进度</strong>
        <span role="status" aria-live="polite">{{ activeProgress }}</span>
        <button
          v-if="stoppable"
          class="restore stop-current"
          :disabled="store.busy || stopping"
          :title="
            store.busy
              ? '正在处理请求，完成后可提交停止'
              : activeBatch && !ionTask && !previewTask
                ? '当前样本处理完毕后停止'
                : ''
          "
          @click="stopCurrent"
        >
          {{ stopping ? '正在停止' : '停止当前任务' }}
        </button>
      </div>
      <div class="sidebar-bottom">
        <RouterLink v-if="auth.admin" to="/admin/monitor">管理员监控</RouterLink>
        <RouterLink to="/account">{{ auth.admin ? '账号与管理' : '我的账号' }}</RouterLink>
        <RouterLink to="/parameters">参数参考 <span>↗</span></RouterLink>
        <div class="connection">
          <i :class="{ connected: store.current }"></i
          >{{ store.current ? '工作区已连接' : '工作区未连接' }}
        </div>
      </div>
    </aside>

    <div
      class="main-shell"
      :class="{ 'assistant-expanded': assistantOpen && route.meta.assistantPage }"
    >
      <header class="topbar">
        <div class="project-heading">
          <span v-if="store.project" class="project-context-label">当前项目</span>
          <strong :title="store.project?.manifest.name">{{
            store.project?.manifest.name ?? '尚未打开项目'
          }}</strong>
          <small v-if="store.project?.dataset" class="muted"
            ><template v-if="store.project.dataset.quantitation_available === false"
              >{{ store.project.dataset.features.toLocaleString() }} 个特征 ·
              未提供定量矩阵</template
            ><template v-else
              >{{ store.project.dataset.cells.toLocaleString() }}
              {{ store.project.dataset.observation_kind === 'sample' ? '样本' : '细胞' }} ×
              {{ store.project.dataset.features.toLocaleString() }} 特征</template
            ></small
          >
        </div>
        <div class="topbar-actions">
          <span v-if="store.project" class="save-state" :class="{ dirty: store.project.unsaved }">{{
            store.project.unsaved ? '已应用未保存' : '已保存'
          }}</span>
          <span v-if="store.draftNames.length" class="draft-state" role="status">
            未应用草稿：{{ store.draftNames.join('、') }}
          </span>
          <button
            v-if="store.project"
            class="save"
            :disabled="store.busy"
            @click="store.mutate('/project/save', {}, 'POST', '项目已保存。')"
          >
            {{ store.busy ? '正在处理…' : '保存项目' }}
          </button>
          <button
            v-if="store.project"
            :disabled="store.busy"
            @click="store.mutate('/project/close')"
          >
            关闭项目
          </button>
          <div class="topbar-utilities">
            <DocumentationPanel :page="route.path" />
            <AssistantPanel v-if="route.meta.assistantPage" @update:open="assistantOpen = $event" />
            <details class="account-menu" :key="route.path">
              <summary>{{ auth.user.username }} · 账号</summary>
              <div class="account-menu-body">
                <RouterLink to="/account">我的账号</RouterLink>
                <p v-if="store.project?.unsaved" class="muted">退出前请保存当前项目。</p>
                <button :disabled="store.busy" @click="logout">退出登录</button>
              </div>
            </details>
          </div>
        </div>
      </header>
      <main
        :inert="store.maintenancePaused && !standalone"
        id="main-content"
        tabindex="-1"
        :aria-busy="!standalone && store.busy"
      >
        <div v-if="store.saveConflict && store.project" class="state-note" role="status">
          <p>磁盘上的项目已被其他会话保存。可先导出本工作区，再打开磁盘上的版本。</p>
          <div class="actions">
            <button class="save" :disabled="store.busy" @click="exportConflictingProject">
              导出当前工作区交换包
            </button>
            <button class="restore" :disabled="store.busy" @click="openDiskProject">
              打开磁盘版本
            </button>
          </div>
        </div>
        <div v-if="store.error" role="alert" class="alert error workspace-feedback">
          <span>{{ store.error }}</span>
          <div class="actions">
            <button
              v-if="store.current"
              @click="store.refresh()"
              :disabled="store.busy"
              class="preview"
            >
              刷新状态</button
            ><button @click="store.error = ''" aria-label="清除错误">×</button>
          </div>
        </div>
        <div v-if="!store.current && !standalone" class="card empty-state">
          <h1>连接实验工作区</h1>
          <p>服务重启或页面刷新后，请重新打开已保存的项目。</p>
          <button class="primary" :disabled="store.busy" @click="store.start()">
            {{ store.busy ? '正在连接…' : '重新连接' }}
          </button>
        </div>
        <template v-else>
          <section v-if="activeModule" class="page-overview" aria-label="本页概况">
            <div class="workspace-path">
              <RouterLink to="/projects">项目首页</RouterLink>
              <span aria-hidden="true">/</span>
              <RouterLink v-if="route.path !== activeModule.path" :to="activeModule.path">{{
                activeModule.name
              }}</RouterLink>
              <strong v-else>{{ activeModule.name }}</strong>
            </div>
            <details :key="route.path">
              <summary>使用说明</summary>
              <div class="page-guide">
                <strong>{{ pageGuide[0] }}</strong>
                <p>{{ pageGuide[1] }}</p>
              </div>
            </details>
          </section>
          <RouterView v-slot="{ Component }"
            ><KeepAlive :key="viewGeneration"><component :is="Component" /></KeepAlive
          ></RouterView>
          <nav v-if="stepIndex >= 0" class="workflow-navigation" aria-label="步骤切换">
            <button v-if="previousStep" @click="router.push(previousStep.path)">
              ← 上一步：{{ previousStep.name }}
            </button>
            <div v-if="nextStep" class="workflow-next">
              <button
                class="primary"
                :disabled="nextBlocked"
                :title="nextHelp"
                :aria-describedby="nextHelp ? 'workflow-next-help' : undefined"
                @click="router.push(nextStep.path)"
              >
                下一步：{{ nextStep.name }} →
              </button>
              <p v-if="nextHelp" id="workflow-next-help" class="muted">{{ nextHelp }}</p>
            </div>
          </nav>
        </template>
      </main>
      <div v-if="store.notice" class="alert success workspace-notice">
        <span class="workspace-feedback" role="status">{{ store.notice }}</span>
        <button type="button" aria-label="关闭操作提示" @click="store.notice = ''">×</button>
      </div>
    </div>
  </div>
  <CsvExportDialog />
</template>

<style scoped>
.progress-panel {
  display: grid;
  gap: 4px;
}
.stop-current {
  justify-self: start;
  padding: 4px 8px;
  font-size: 12px;
}
.workflow-navigation {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1.25rem;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.workflow-next {
  max-width: 100%;
  text-align: right;
}
.workflow-next p {
  margin-bottom: 0;
}
.workspace-notice {
  position: fixed;
  z-index: 45;
  right: 24px;
  bottom: 18px;
  width: max-content;
  max-width: min(460px, calc(100vw - 48px));
  margin: 0;
  padding: 8px 10px 8px 14px;
  box-shadow: var(--shadow-raised);
  pointer-events: none;
}
.workspace-notice > button {
  min-height: 26px;
  border: 0;
  background: transparent;
  color: inherit;
  pointer-events: auto;
}
</style>
