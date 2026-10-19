<script setup lang="ts">
import { computed, onActivated, onDeactivated, onUnmounted, ref } from 'vue'
import { request } from '../../api/client'
import { useAuth } from '../../stores/auth'
import MonitorTrend from './MonitorTrend.vue'
type Decision = {
  state: 'ready' | 'blocked' | 'unknown'
  blockers?: string[]
  unknown?: string[]
  reason?: string
  active_pages?: number
  unconfirmed_pages?: number
  monitor_pages?: number
}
type Snapshot = {
  environment: string
  instance: string
  uptime: number
  sampled_at: number | null
  disks_at: number
  resources: Record<string, number | null>
  update_readiness: Decision
  production: Decision
  disks: { label: string; total?: number; free?: number; error?: string }[]
  pages: {
    username: string
    route: string
    visibility: string
    state: string
    monitor_only: boolean
    seen: number
  }[]
  workspaces: {
    id: string
    username: string
    project: string | null
    unsaved: boolean | null
    busy: boolean
    idle_seconds: number
  }[]
  users: {
    username: string
    role: string
    active: boolean
    pages: number
    last_seen: number | null
    last_activity: number | null
  }[]
  tasks: {
    id: string
    username: string
    project: string
    kind: string
    status: string
    completed: number
    total: number
    process_alive: boolean | null
  }[]
  requests: { username: string; kind: string; started_at: number }[]
}
type Point = {
  at: number
  instance: string
  metrics: Record<string, { mean: number; peak: number }>
}
const auth = useAuth()
const state = ref<Snapshot>()
const points = ref<Point[]>([])
const events = ref<
  { at: number; username: string | null; action: string; resource: string; status: number }[]
>([])
const counts = ref<{ action: string; count: number }[]>([])
const error = ref(''),
  eventError = ref(''),
  historyError = ref('')
const loading = ref(false)
const metric = ref('host_cpu'),
  tab = ref('pages'),
  username = ref(''),
  action = ref(''),
  offset = ref(0)
let timer: number | undefined,
  active = false,
  serial = 0,
  historyAt = 0
const now = ref(Date.now() / 1000)
const stale = computed(
  () => !!error.value || !state.value?.sampled_at || now.value - state.value.sampled_at > 15,
)
const label = (value?: Decision, unavailable = false) =>
  unavailable
    ? '无法确认'
    : { ready: '满足更新检查', blocked: '暂不可更新', unknown: '无法确认' }[
        value?.state ?? 'unknown'
      ]
const when = (value?: number | null) => (value ? new Date(value * 1000).toLocaleString() : '未记录')
const bytes = (value?: number | null) =>
  value == null ? '不可用' : `${(value / 1024 ** 3).toFixed(2)} GiB`
const percent = (value?: number | null) => (value == null ? '等待采样' : `${value.toFixed(1)}%`)
function showEvents(delta = 0) {
  offset.value = delta ? Math.max(0, offset.value + delta) : 0
  void loadEvents()
}
async function loadEvents() {
  eventError.value = ''
  try {
    const data = await request<{ items: typeof events.value; counts_24h: typeof counts.value }>(
      `/admin/monitor/events?username=${encodeURIComponent(username.value)}&action=${encodeURIComponent(action.value)}&offset=${offset.value}`,
    )
    if (!active) return
    events.value = data.items
    counts.value = data.counts_24h
  } catch (e) {
    eventError.value = (e as Error).message
  }
}
async function refresh() {
  if (!active || loading.value || !auth.admin) return
  loading.value = true
  const version = serial
  try {
    const data = await request<Snapshot>('/admin/monitor')
    if (!active || version !== serial) return
    state.value = data
    error.value = ''
    now.value = Date.now() / 1000
    if (now.value - historyAt >= 60) {
      try {
        const data = await request<{ points: Point[] }>('/admin/monitor/history')
        if (active && version === serial) {
          points.value = data.points
          historyAt = now.value
          historyError.value = ''
        }
      } catch (e) {
        historyError.value = (e as Error).message
      }
      await loadEvents()
    }
  } catch (e) {
    if (active && version === serial) error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onActivated(() => {
  active = true
  serial++
  void refresh()
  timer = window.setInterval(() => {
    now.value = Date.now() / 1000
    void refresh()
  }, 5000)
})
function stop() {
  active = false
  serial++
  clearInterval(timer)
}
onDeactivated(stop)
onUnmounted(stop)
</script>
<template>
  <section v-if="!auth.admin" class="card">
    <h1>管理员监控</h1>
    <p role="alert">此页面需要管理员权限。</p>
  </section>
  <section v-else class="monitor">
    <div class="heading">
      <div>
        <h1>管理员监控</h1>
        <p class="muted">只读 · 当前状态与最近 24 小时趋势 · 不占用实验工作区</p>
      </div>
      <button :disabled="loading" @click="refresh" class="preview">刷新监控</button>
    </div>
    <p v-if="error" class="alert error" role="alert">{{ error }}；保留上次数据，更新判断已失效。</p>
    <p v-if="!state && !error" role="status">等待首次监控采样…</p>
    <template v-if="state">
      <div class="readiness-grid">
        <article
          class="card readiness"
          :data-state="stale ? 'unknown' : state.update_readiness.state"
        >
          <h2>当前实例 · {{ state.environment }}</h2>
          <strong>{{ label(state.update_readiness, stale) }}</strong>
          <p>
            活动业务页面 {{ state.update_readiness.active_pages ?? '—' }} · 关闭待确认
            {{ state.update_readiness.unconfirmed_pages ?? '—' }} · 只读监控页
            {{ state.update_readiness.monitor_pages ?? '—' }}
          </p>
          <ul>
            <li
              v-for="reason in [
                ...(state.update_readiness.blockers ?? []),
                ...(state.update_readiness.unknown ?? []),
              ]"
              :key="reason"
            >
              {{ reason }}
            </li>
            <li v-if="stale">监控数据不可用或过期。</li>
          </ul>
        </article>
        <article class="card readiness" :data-state="stale ? 'unknown' : state.production.state">
          <h2>生产环境 · 独立检查</h2>
          <strong>{{ label(state.production, stale) }}</strong>
          <p>{{ state.production.reason }}</p>
          <ul>
            <li
              v-for="reason in [
                ...(state.production.blockers ?? []),
                ...(state.production.unknown ?? []),
              ]"
              :key="reason"
            >
              {{ reason }}
            </li>
          </ul>
        </article>
      </div>
      <p class="muted">
        所有前台、后台及未登录页面均计入检查。失联不等于关闭；页面关闭待确认、未保存修改、打开的项目、活动任务或未完成请求均不能给出可更新结论。只读监控页单独列出；发布前仍须重新检查。
      </p>
      <div class="metric-grid">
        <article class="card">
          <h3>服务</h3>
          <strong>{{ Math.floor(state.uptime / 60) }} 分钟</strong>
          <p>采样 {{ when(state.sampled_at) }}</p>
        </article>
        <article class="card">
          <h3>主机 CPU / 内存</h3>
          <strong
            >{{ percent(state.resources.host_cpu) }} /
            {{ percent(state.resources.host_memory) }}</strong
          >
          <p>
            可用内存 {{ bytes(state.resources.memory_available) }} · Swap
            {{ percent(state.resources.swap) }}
          </p>
        </article>
        <article class="card">
          <h3>API 与计算进程</h3>
          <strong
            >{{ percent(state.resources.process_cpu) }} ·
            {{ bytes(state.resources.process_rss) }}</strong
          >
          <p>
            {{ state.resources.processes ?? '—' }} 个进程；CPU 以单核 100% 计，RSS
            合计可能重复计算共享内存。
          </p>
        </article>
        <article class="card">
          <h3>最近 5 分钟业务请求</h3>
          <strong
            >{{ state.resources.requests_5m ?? '—' }} 次 ·
            {{ state.resources.errors_5m ?? '—' }} 次服务错误</strong
          >
          <p>平均耗时 {{ state.resources.latency_ms?.toFixed(1) ?? '—' }} ms</p>
        </article>
      </div>
      <article class="card">
        <div class="heading">
          <h2>资源趋势 · 最近 24 小时</h2>
          <label
            >指标
            <select v-model="metric">
              <option value="host_cpu">主机 CPU（%）</option>
              <option value="host_memory">主机内存（%）</option>
              <option value="process_cpu">服务 CPU（单核 %）</option>
              <option value="process_rss">服务内存（RSS）</option>
              <option value="swap">Swap（%）</option>
              <option value="load1">主机 1 分钟负载</option>
              <option
                v-for="disk in state.disks"
                :key="disk.label"
                :value="`disk_free:${disk.label}`"
              >
                {{ disk.label }}可用空间
              </option>
              <option value="latency_ms">业务请求平均耗时（ms）</option>
            </select></label
          >
        </div>
        <p v-if="historyError" role="alert">历史暂不可用：{{ historyError }}</p>
        <MonitorTrend
          :points="points"
          :metric="metric"
          :bytes="metric === 'process_rss' || metric.startsWith('disk_free:')"
        />
      </article>
      <article class="card">
        <h2>存储容量</h2>
        <p class="muted">
          每 60 秒检查；最近检查 {{ when(state.disks_at) }}。多个目录可能使用同一磁盘，容量不累加。
        </p>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>用途</th>
                <th>可用</th>
                <th>总容量</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="disk in state.disks" :key="disk.label">
                <td>{{ disk.label }}</td>
                <td>{{ bytes(disk.free) }}</td>
                <td>{{ bytes(disk.total) }}</td>
                <td>{{ disk.error ?? '可读' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
      <article class="card">
        <div class="tabs" role="tablist" aria-label="监控明细">
          <button
            v-for="(name, key) in {
              pages: '活动页面',
              users: '用户',
              workspaces: '工作区',
              tasks: '任务与请求',
              events: '安全事件',
            }"
            :key="key"
            role="tab"
            :aria-selected="tab === key"
            @click="tab = key"
          >
            {{ name }}
          </button>
        </div>
        <div class="table-scroll">
          <table v-if="tab === 'pages'">
            <thead>
              <tr>
                <th>用户</th>
                <th>页面</th>
                <th>状态</th>
                <th>最近心跳</th>
                <th>用途</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(page, i) in state.pages" :key="i">
                <td>{{ page.username }}</td>
                <td>{{ page.route }}</td>
                <td>
                  {{
                    page.state === 'unconfirmed'
                      ? '关闭待确认'
                      : page.visibility === 'hidden'
                        ? '后台标签页'
                        : '前台页面'
                  }}
                </td>
                <td>{{ when(page.seen) }}</td>
                <td>{{ page.monitor_only ? '只读监控' : '业务页面' }}</td>
              </tr>
            </tbody>
          </table>
          <table v-else-if="tab === 'users'">
            <thead>
              <tr>
                <th>用户</th>
                <th>角色</th>
                <th>启用</th>
                <th>在线页面</th>
                <th>最近访问</th>
                <th>实际操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in state.users" :key="u.username">
                <td>{{ u.username }}</td>
                <td>{{ u.role }}</td>
                <td>{{ u.active ? '是' : '否' }}</td>
                <td>{{ u.pages }}</td>
                <td>{{ when(u.last_seen) }}</td>
                <td>{{ when(u.last_activity) }}</td>
              </tr>
            </tbody>
          </table>
          <table v-else-if="tab === 'workspaces'">
            <thead>
              <tr>
                <th>用户</th>
                <th>项目</th>
                <th>状态</th>
                <th>保存状态</th>
                <th>空闲</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="w in state.workspaces" :key="w.id">
                <td>{{ w.username }}</td>
                <td>{{ w.project ?? '未打开 / 忙时待确认' }}</td>
                <td>{{ w.busy ? '繁忙' : '空闲' }}</td>
                <td>
                  {{ w.unsaved === null ? '待确认' : w.unsaved ? '未保存' : '已保存或空工作区' }}
                </td>
                <td>{{ Math.floor(w.idle_seconds) }} 秒</td>
              </tr>
            </tbody>
          </table>
          <template v-else-if="tab === 'tasks'"
            ><table>
              <thead>
                <tr>
                  <th>用户</th>
                  <th>项目</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>样本进度</th>
                  <th>进程</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in state.tasks" :key="t.id">
                  <td>{{ t.username }}</td>
                  <td>{{ t.project }}</td>
                  <td>{{ t.kind }}</td>
                  <td>{{ t.status }}</td>
                  <td>{{ t.total ? `${t.completed} / ${t.total}` : '—' }}</td>
                  <td>
                    {{
                      t.process_alive === true
                        ? '已确认运行'
                        : t.process_alive === false
                          ? '未发现对应进程'
                          : '待确认 / 不适用'
                    }}
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-for="(r, i) in state.requests" :key="i">
              {{ r.username }} · {{ r.kind }} · 开始 {{ when(r.started_at) }}
            </p>
            <p class="muted">
              最近 200
              个已结束任务及全部活动任务；历史任务提交人可能未记录。进度不表示预计完成时间。
            </p></template
          >
          <template v-else
            ><div class="filters">
              <label>用户 <input v-model="username" placeholder="全部" /></label
              ><label>事件 <input v-model="action" placeholder="全部" /></label
              ><button @click="showEvents()">筛选</button>
            </div>
            <p v-if="eventError" role="alert">{{ eventError }}</p>
            <p class="muted">
              24 小时计数：{{ counts.map((c) => `${c.action} ${c.count}`).join(' · ') || '无记录' }}
            </p>
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>用户</th>
                  <th>事件</th>
                  <th>资源</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(e, i) in events" :key="i">
                  <td>{{ when(e.at) }}</td>
                  <td>{{ e.username ?? '未认证' }}</td>
                  <td>{{ e.action }}</td>
                  <td>{{ e.resource }}</td>
                  <td>{{ e.status }}</td>
                </tr>
              </tbody>
            </table>
            <div class="filters">
              <button :disabled="offset === 0" @click="showEvents(-50)">上一页</button
              ><button :disabled="events.length < 50" @click="showEvents(50)">下一页</button>
            </div></template
          >
        </div>
        <p class="muted">账号停用、密码重置等操作请前往“账号与管理”。监控界面不提供处置操作。</p>
      </article>
    </template>
  </section>
</template>
<style scoped>
.monitor {
  min-width: 0;
}
.heading,
.filters,
.tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}
.readiness-grid,
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.metric-grid {
  margin: 1rem 0;
}
.card {
  min-width: 0;
  margin-bottom: 1rem;
}
.card strong {
  font-size: 1.15rem;
}
.readiness {
  border-top: 4px solid #a16207;
}
.readiness[data-state='blocked'] {
  border-color: #dc2626;
}
.readiness[data-state='ready'] {
  border-color: #15803d;
}
.table-scroll {
  overflow-x: auto;
  max-width: 100%;
}
table {
  width: 100%;
  font-size: 0.88rem;
}
td,
th {
  text-align: left;
  padding: 0.6rem;
  white-space: nowrap;
}
td {
  max-width: 24rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tabs {
  justify-content: flex-start;
  margin-bottom: 1rem;
}
.tabs [aria-selected='true'] {
  background: #dbeafe;
  color: #1d4ed8;
}
.filters {
  justify-content: flex-start;
  margin: 0.8rem 0;
}
@media (max-width: 900px) {
  .readiness-grid,
  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>
