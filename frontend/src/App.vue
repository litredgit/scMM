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
import { modules, moduleForPath } from './features/modules/modules'

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
const stages = [
  { path: '/raw', name: '预览' },
  { path: '/extraction', name: '提取' },
  { path: '/preprocess', name: '预处理' },
  { path: '/analysis', name: '分析' },
]
const workflow = [
  { path: '/samples', name: '添加原始文件' },
  ...stages,
  { path: '/results', name: '结果与保存' },
]
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
      '展开参数组查看详细选项。信号强度以科学计数法显示，聚焦输入框可查看完整数值。图形显示范围与提取范围分别设置。',
    ],
    '/extraction': [
      '检查逐样本参数，执行提取并审核纳入结果。',
      '在参数表内修改单个样本，或将一行、一个字段复制到全部样本。参数修改后重新检查输入。每行的查看信号按钮打开对应样本的提取信号。',
    ],
    '/annotation': [
      '选择注释数据库，在谱图中检查候选与关联峰。',
      '点击峰查看同位素和加合关系、注释名称及当前数据库的二级匹配状态。人工审核修改同步到关联峰，并保留审核记录。',
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
  activeModule,
  (value) => {
    if (value) expandedModule.value = value.key
  },
  { immediate: true },
)
const workflowPolling = serialPolling(
  async () => {
    if (!standalone.value && !store.busy && route.path !== '/extraction')
      await store.refreshBatches()
  },
  5000,
  (cause) => {
    store.error = cause instanceof Error ? cause.message : String(cause)
  },
)
watch(
  () => route.path,
  () => {
    navigationOpen.value = false
  },
)
watch(
  () => store.project?.path,
  () => {
    resetScrollPositions()
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
  return `提取 ${finished}/${batch.samples.length} · ${batch.message || batch.stage || '运行中'}`
})
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
    const info = await store.readResource<typeof workflowState.value>('/analysis/workflow-status', {
      accept,
    })
    if (accept() && info) workflowState.value = info
  },
)
function stepCompleted(path: string) {
  if (!store.project) return false
  if (path === '/data-check') return checkedDatasets.value.has(checkIdentity.value)
  if (path === '/samples') return !!store.project.manifest.samples.length
  if (path === '/raw') return !!store.project.manifest.manual_parameters
  if (path === '/extraction')
    return !!store.batches?.some((batch) =>
      batch.samples.some((sample) => sample.status === 'succeeded'),
    )
  if (path in workflowState.value) return workflowState.value[path]
  if (['/cell-extraction', '/statistics'].includes(path)) return !!store.project.dataset
  return false
}
const stepIndex = computed(() => workflow.findIndex((step) => step.path === route.path))
const previousStep = computed(() =>
  stepIndex.value === 0 ? { path: '/projects', name: '项目首页' } : workflow[stepIndex.value - 1],
)
const nextStep = computed(() => workflow[stepIndex.value + 1])
const nextBlocked = computed(
  () =>
    !store.project ||
    (['/preprocess', '/analysis'].includes(nextStep.value?.path ?? '') &&
      !store.project.dataset?.cells),
)
const nextHelp = computed(() =>
  !store.project
    ? '请先创建或打开项目。'
    : nextBlocked.value
      ? '请先审核纳入提取结果，或导入已有 H5AD，建立当前数据集。'
      : '',
)
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
    <aside class="sidebar" :class="{ 'navigation-open': navigationOpen }">
      <RouterLink to="/projects" class="brand" aria-label="scMM 项目首页">
        <span class="brand-mark" aria-hidden="true">s</span
        ><span>scMM<small>单细胞质谱工作台</small></span>
      </RouterLink>
      <button
        class="mobile-nav-toggle"
        :aria-expanded="navigationOpen"
        aria-controls="workflow-menu"
        @click="navigationOpen = !navigationOpen"
      >
        {{ navigationOpen ? '收起导航' : '流程与账号' }}
      </button>
      <p class="nav-caption">{{ activeModule ? `${activeModule.name}工作流程` : '工作板块' }}</p>
      <nav id="workflow-menu" aria-label="工作流程">
        <RouterLink to="/projects" class="nav-home">项目首页</RouterLink>
        <div v-for="module in modules" :key="module.key" class="nav-module">
          <button
            :aria-label="module.name"
            :aria-expanded="expandedModule === module.key"
            :aria-controls="`steps-${module.key}`"
            @click="expandedModule = expandedModule === module.key ? '' : module.key"
          >
            <span>{{ module.name }}</span
            ><span aria-hidden="true">{{ expandedModule === module.key ? '▾' : '▸' }}</span>
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
                'current-step': route.fullPath === step.path,
                'step-completed': stepCompleted(step.path),
              }"
              :to="step.path"
              >{{ step.name
              }}<small v-if="step.path === '/extraction'" class="nav-step-state">{{
                extractionStatus
              }}</small></RouterLink
            >
            <div v-if="module.key === 'statistics'" id="method-menu"></div>
          </div>
        </div>
        <RouterLink to="/results">结果与保存</RouterLink>
      </nav>
      <p
        class="task-note progress-panel"
        :title="store.busy ? store.operationMessage : activeBatch ? batchProgress : store.task"
        :class="{ running: store.busy || activeBatch }"
        role="status"
        aria-live="polite"
      >
        {{ store.busy ? store.operationMessage : activeBatch ? batchProgress : store.task }}
      </p>
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

    <div class="main-shell" :class="{ 'assistant-expanded': assistantOpen }">
      <header class="topbar">
        <div class="project-heading">
          <span class="eyebrow">当前项目</span
          ><strong>{{ store.project?.manifest.name ?? '尚未打开项目' }}</strong>
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
          <details class="account-menu">
            <summary>{{ auth.user.username }} · 账号</summary>
            <div class="account-menu-body">
              <RouterLink to="/account">我的账号</RouterLink
              ><button :disabled="store.busy" @click="logout">退出登录</button>
            </div>
          </details>
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
        </div>
      </header>
      <main
        :inert="store.maintenancePaused && !standalone"
        id="main-content"
        :aria-busy="!standalone && store.busy"
      >
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
        <div v-if="store.notice" role="status" class="alert success workspace-feedback">
          {{ store.notice }}
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
            <p>
              {{ pageGuide[0]
              }}<template v-if="store.project?.dataset">
                · {{ store.project.dataset.cells }} 个观测 ×
                {{ store.project.dataset.features }} 特征</template
              >
            </p>
            <details>
              <summary>查看本页使用说明</summary>
              <p>{{ pageGuide[1] }}</p>
            </details>
          </section>
          <RouterView v-slot="{ Component }"
            ><KeepAlive><component :is="Component" /></KeepAlive
          ></RouterView>
          <nav v-if="stepIndex >= 0" class="workflow-navigation" aria-label="步骤切换">
            <button v-if="previousStep" @click="router.push(previousStep.path)">
              ← 上一步：{{ previousStep.name }}
            </button>
            <span class="muted">{{ stepIndex + 1 }} / {{ workflow.length }}</span>
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
      <AssistantPanel
        v-if="route.path !== '/admin/monitor'"
        @update:open="assistantOpen = $event"
      />
      <footer>scMM · CyESI 单细胞质谱分析<span>离开或刷新前请主动保存项目</span></footer>
    </div>
  </div>
</template>

<style scoped>
.workflow-navigation {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1.5rem;
}
.workflow-next {
  max-width: 100%;
  text-align: right;
}
.workflow-next p {
  margin-bottom: 0;
}
</style>
