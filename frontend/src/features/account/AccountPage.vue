<script setup lang="ts">
import SectionNav from '../../components/SectionNav.vue'
import { formatTime } from '../../help/time'
import { onMounted, ref } from 'vue'
import MaintenancePanel from './MaintenancePanel.vue'
import AISettings from '../assistant/AISettings.vue'
import { request } from '../../api/client'
import { useAuth } from '../../stores/auth'
import { useWorkspace } from '../../stores/workspace'
const auth = useAuth()
const store = useWorkspace()
type Account = { id: string; username: string; role: string; active: boolean; must_change: boolean }
type Audit = {
  at: number
  username: string | null
  action: string
  resource: string
  status: number
}
const users = ref<Account[]>([])
const audit = ref<Audit[]>([])
const name = ref('')
const role = ref('member')
const credential = ref('')
const current = ref('')
const next = ref('')
async function refresh() {
  if (!auth.admin) return
  users.value = await request<Account[]>('/admin/users')
  audit.value = await request<Audit[]>('/admin/audit')
}
async function create() {
  await store.run(
    async (scope) => {
      const result = await request<{ initial_credential: string }>('/admin/users', {
        method: 'POST',
        body: { username: name.value, role: role.value },
      })
      credential.value = result.initial_credential
      name.value = ''
      scope.update({ phase: 'refreshing' })
      await refresh()
    },
    '',
    { label: '创建团队账号', phase: 'submitting' },
  )
}
async function update(user: Account, reset: boolean) {
  await store.run(
    async (scope) => {
      const result = await request<{ initial_credential: string | null }>(
        `/admin/users/${user.id}`,
        {
          method: 'PATCH',
          body: reset ? { reset_password: true } : { active: !user.active },
        },
      )
      credential.value = result.initial_credential ?? ''
      scope.update({ phase: 'refreshing' })
      await refresh()
    },
    '',
    { label: reset ? '重置账号密码' : '更新账号状态', phase: 'submitting' },
  )
}
async function change() {
  if (await auth.changePassword(current.value, next.value)) {
    current.value = ''
    next.value = ''
  }
}
onMounted(() => store.run(refresh, '', { label: '读取账号信息', phase: 'reading' }))
</script>
<template>
  <section>
    <h1>我的账号</h1>
    <p>
      当前账号：{{
        auth.user?.username
      }}。团队共享全部项目和指定原始数据；退出登录不会自动保存项目。
    </p>
    <SectionNav
      :items="[
        { id: 'personal-settings', label: '个人设置' },
        { id: 'personal-ai', label: '个人 AI' },
        ...(auth.admin
          ? [
              { id: 'team-management', label: '团队管理' },
              { id: 'server-maintenance', label: '服务器维护' },
            ]
          : []),
      ]"
    />
    <section id="personal-settings" class="task-section" aria-label="个人设置">
      <h2>个人设置</h2>
      <form class="card" @submit.prevent="change">
        <h2>修改密码</h2>
        <p>修改后所有设备需要重新登录。请先保存当前项目。</p>
        <label
          >当前密码<input
            v-model="current"
            type="password"
            autocomplete="current-password"
            required
            maxlength="128"
        /></label>
        <label
          >新密码<input
            v-model="next"
            type="password"
            autocomplete="new-password"
            required
            minlength="15"
            maxlength="128"
        /></label>
        <p v-if="auth.error" role="alert">{{ auth.error }}</p>
        <button class="primary" :disabled="auth.busy || store.busy">修改密码</button>
      </form>
    </section>
    <section id="personal-ai" class="task-section" aria-label="个人 AI">
      <h2>个人 AI</h2>
      <AISettings />
    </section>
    <section v-if="auth.admin" id="team-management" class="task-section" aria-label="团队管理">
      <h2>团队管理</h2>
      <form class="card" @submit.prevent="create">
        <h2>创建账号</h2>
        <label
          >新账号名称<input v-model="name" required minlength="3" maxlength="64" autocomplete="off"
        /></label>
        <label
          >角色<select v-model="role">
            <option value="member">普通成员</option>
            <option value="admin">管理员</option>
          </select></label
        >
        <button class="primary" :disabled="store.busy">创建账号</button>
      </form>
      <div v-if="credential" class="card">
        <h2>一次性登录凭据</h2>
        <p>24 小时内有效，首次登录后设置密码。请通过可信渠道交给对应用户；关闭后不再显示。</p>
        <label>一次性凭据<input :value="credential" readonly autocomplete="off" /></label>
        <button @click="credential = ''" class="preview">关闭凭据显示</button>
      </div>
      <div class="card table-scroll">
        <h2>团队账号</h2>
        <table>
          <thead>
            <tr>
              <th>账号</th>
              <th>角色</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.username }}</td>
              <td>{{ user.role === 'admin' ? '管理员' : '普通成员' }}</td>
              <td>{{ !user.active ? '已停用' : user.must_change ? '待设置密码' : '正常' }}</td>
              <td>
                <button
                  :disabled="store.busy || user.id === auth.user?.id"
                  @click="update(user, true)"
                  class="restore"
                >
                  重置密码
                </button>
                <button :disabled="store.busy" @click="update(user, false)">
                  {{ user.active ? '停用' : '启用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card table-scroll">
        <h2>最近安全记录</h2>
        <table>
          <thead>
            <tr>
              <th>时间（北京时间 UTC+8）</th>
              <th>账号</th>
              <th>操作</th>
              <th>范围</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, i) in audit" :key="i">
              <td>{{ formatTime(item.at * 1000) }}</td>
              <td>{{ item.username ?? '匿名/离线管理' }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.resource }}</td>
              <td>{{ item.status }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section v-if="auth.admin" id="server-maintenance" class="task-section" aria-label="服务器维护">
      <h2>服务器维护</h2>
      <MaintenancePanel />
    </section>
  </section>
</template>
<style scoped>
label {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
</style>
