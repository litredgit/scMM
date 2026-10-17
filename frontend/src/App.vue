<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspace } from './stores/workspace'
import { useAuth } from './stores/auth'
import { startPresence, updatePresence } from './api/presence'
import LoginPanel from './components/LoginPanel.vue'
import AssistantPanel from './features/assistant/AssistantPanel.vue'

const store = useWorkspace()
const auth = useAuth()
const route = useRoute()
const router = useRouter()
const standalone = computed(() => ['/admin/monitor', '/account'].includes(route.path))
let presence: ReturnType<typeof startPresence> | undefined
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
  await store.run(async () => {
    store.release()
    await auth.logout()
    store.reset()
  })
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
  void presence.ready.then(() => auth.refresh())
  window.addEventListener('pagehide', store.release)
})
onUnmounted(() => {
  window.removeEventListener('pagehide', store.release)
  presence?.stop()
})
const stages = [
  { path: '/raw', name: '原始谱与参数' },
  { path: '/extraction', name: '提取与审核' },
  { path: '/preprocess', name: '预处理' },
  { path: '/analysis', name: '分析' },
]
const workflow = [
  { path: '/samples', name: '项目与样本' },
  ...stages,
  { path: '/results', name: '结果与保存' },
]
const stepIndex = computed(() => workflow.findIndex((step) => step.path === route.path))
const previousStep = computed(() =>
  stepIndex.value === 0 ? { path: '/projects', name: '项目首页' } : workflow[stepIndex.value - 1],
)
const nextStep = computed(() => workflow[stepIndex.value + 1])
const nextBlocked = computed(
  () =>
    !store.project ||
    (['/preprocess', '/analysis'].includes(nextStep.value?.path ?? '') && !store.project.dataset),
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
  <div v-else class="workbench" :key="auth.user.id">
    <aside class="sidebar">
      <RouterLink to="/projects" class="brand" aria-label="scMM 项目首页">
        <span class="brand-mark">s</span><span>scMM<small>单细胞质谱工作台</small></span>
      </RouterLink>
      <p class="nav-caption">实验工作流</p>
      <nav aria-label="工作流程">
        <RouterLink to="/projects"><span class="nav-number">⌂</span>项目首页</RouterLink>
        <RouterLink to="/samples"><span class="nav-number">1</span>项目与样本</RouterLink>
        <RouterLink v-for="(stage, i) in stages" :key="stage.path" :to="stage.path"
          ><span class="nav-number">{{ i + 2 }}</span
          >{{ stage.name }}</RouterLink
        >
        <RouterLink to="/results"><span class="nav-number">6</span>结果与保存</RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <RouterLink v-if="auth.admin" to="/admin/monitor">管理员监控</RouterLink>
        <RouterLink to="/account">{{ auth.admin ? '账号与管理' : '我的账号' }}</RouterLink>
        <RouterLink to="/parameters">参数参考 <span>↗</span></RouterLink>
        <div class="connection">
          <i :class="{ connected: store.current }"></i
          >{{ store.current ? '工作区已连接' : '工作区未连接' }}
        </div>
        <p class="task-note">{{ store.busy ? '正在执行操作…' : store.task }}</p>
        <p>Vue / FastAPI 工作台<br />六步实验流程</p>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <div class="project-heading">
          <span class="eyebrow">当前项目</span
          ><strong>{{ store.project?.manifest.name ?? '尚未打开项目' }}</strong>
        </div>
        <div class="topbar-actions">
          <span>{{ auth.user.username }}</span>
          <button :disabled="store.busy" @click="logout">退出登录</button>
          <span v-if="store.project" class="save-state" :class="{ dirty: store.project.unsaved }">{{
            store.project.unsaved ? '有未保存修改' : '已保存'
          }}</span>
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
      <main id="main-content" :aria-busy="!standalone && store.busy">
        <div v-if="store.error" role="alert" class="alert error">
          <span>{{ store.error }}</span>
          <div class="actions">
            <button v-if="store.current" @click="store.refresh()" :disabled="store.busy">
              刷新状态</button
            ><button @click="store.error = ''" aria-label="清除错误">×</button>
          </div>
        </div>
        <div v-if="store.notice" role="status" class="alert success">{{ store.notice }}</div>
        <div v-if="!store.current && !standalone" class="card empty-state">
          <h1>连接实验工作区</h1>
          <p>服务重启或页面刷新后，请重新打开已保存的项目。</p>
          <button class="primary" :disabled="store.busy" @click="store.start()">
            {{ store.busy ? '正在连接…' : '重新连接' }}
          </button>
        </div>
        <template v-else>
          <RouterView v-slot="{ Component }"
            ><KeepAlive><component :is="Component" /></KeepAlive
          ></RouterView>
          <nav v-if="stepIndex >= 0" class="workflow-navigation" aria-label="步骤切换">
            <button
              v-if="previousStep"
              :disabled="store.busy"
              @click="router.push(previousStep.path)"
            >
              ← 上一步：{{ previousStep.name }}
            </button>
            <span class="muted">{{ stepIndex + 1 }} / {{ workflow.length }}</span>
            <div v-if="nextStep" class="workflow-next">
              <button
                class="primary"
                :disabled="store.busy || nextBlocked"
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
      <AssistantPanel v-if="route.path !== '/admin/monitor'" />
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
