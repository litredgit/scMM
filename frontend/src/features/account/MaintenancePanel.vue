<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace(),
  resources = ref(''),
  status = ref<Record<string, unknown>>(),
  version = ref(''),
  closure = ref<{
    review_id: string
    unconfirmed_pages: number
    legacy_requests: boolean
    active_pages: number
  }>(),
  closureReason = ref('')
async function load() {
  await store.run(async () => {
    const result = await request<{ active: unknown; pending: unknown }>('/admin/resources')
    resources.value = JSON.stringify(result.pending || result.active, null, 2)
    status.value = await request('/admin/maintenance/status')
  })
}
async function save() {
  await store.run(
    () => request('/admin/resources', { method: 'PUT', body: JSON.parse(resources.value) }),
    '配置已检查并暂存，将在维护重启后生效。',
  )
}
async function action(name: string) {
  closure.value = undefined
  await store.run(async () => {
    status.value = await request('/admin/maintenance/' + name, {
      method: 'POST',
      body: name === 'execute' ? { action: 'restart' } : undefined,
    })
  })
}
async function reviewClosure() {
  await store.run(async () => {
    closure.value = await request('/admin/maintenance/closed-pages/review', { method: 'POST' })
  })
}
async function confirmClosure() {
  const reviewed = closure.value
  closure.value = undefined
  if (!reviewed) return
  await store.run(async () => {
    await request('/admin/maintenance/closed-pages/confirm', {
      method: 'POST',
      body: { review_id: reviewed.review_id, reason: closureReason.value },
    })
    status.value = await request('/admin/maintenance/status')
  }, '关闭依据已记录；工作区仍保留，请继续验证并暂存会话。')
}
async function update() {
  await store.run(() =>
    request('/admin/maintenance/execute', {
      method: 'POST',
      body: { action: 'update', version: version.value },
    }),
  )
}
onMounted(load)
</script>
<template>
  <div class="card">
    <h2>服务器资源与更新</h2>
    <p>
      目录变更只切换可访问资源，不迁移原始文件。维护会先收集各页面草稿、加密聊天和全部工作区，并验证数据与模型可恢复。失联页面或活动任务会阻止更新。
    </p>
    <label
      >资源目录配置<textarea
        aria-label="服务器资源配置"
        v-model="resources"
        rows="12"
        spellcheck="false"
      />
    </label>
    <div class="actions">
      <button class="save" :disabled="store.busy" @click="save">检查并暂存配置</button
      ><button
        class="primary"
        :disabled="store.busy"
        @click="
          store.run(
            () => request('/admin/database/update', { method: 'POST' }),
            '注释数据库已更新，旧版本已保留。',
          )
        "
      >
        更新官方注释数据库
      </button>
    </div>
    <div class="actions">
      <button class="primary" :disabled="store.busy" @click="action('prepare')">收集全部会话</button
      ><button class="save" :disabled="store.busy" @click="action('checkpoint')">
        验证并暂存会话</button
      ><button class="restore" :disabled="store.busy" @click="action('execute')">暂存后重启</button
      ><button :disabled="store.busy" @click="action('cancel')">取消维护</button
      ><button class="preview" :disabled="store.busy" @click="load">读取状态</button>
    </div>
    <pre>{{ JSON.stringify(status, null, 2) }}</pre>
    <h3>失联页面已确认关闭</h3>
    <p>
      浏览器可能漏发关闭回执。先收集会话，再读取失联记录；仅在已经核实对应页面全部关闭后填写依据并执行。
      只处理本轮失联记录和历史未登记请求，不清除正在连接的页面，不丢弃工作区或代替维护暂存。
    </p>
    <button class="preview" :disabled="store.busy" @click="reviewClosure">读取失联页面范围</button>
    <p v-if="closure">
      本轮失联 {{ closure.unconfirmed_pages }} 页；历史未登记请求：{{
        closure.legacy_requests ? '有' : '无'
      }}；仍连接 {{ closure.active_pages }} 页。审阅 5 分钟内有效，新活动会使范围失效。
    </p>
    <label
      >页面关闭依据<input aria-label="页面关闭依据" v-model="closureReason" maxlength="200"
    /></label>
    <button
      class="restore"
      :disabled="store.busy || !closure || !closureReason.trim()"
      @click="confirmClosure"
    >
      记录关闭确认并保留工作区
    </button>
    <label>已批准版本提交号<input v-model="version" /></label
    ><button class="primary" :disabled="store.busy || !version" @click="update">
      暂存后更新已批准版本
    </button>
  </div>
</template>
