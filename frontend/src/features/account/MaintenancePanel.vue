<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace(),
  resources = ref(''),
  status = ref<Record<string, unknown>>(),
  version = ref('')
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
  await store.run(async () => {
    status.value = await request('/admin/maintenance/' + name, {
      method: 'POST',
      body: name === 'execute' ? { action: 'restart' } : undefined,
    })
  })
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
    <label>已批准版本提交号<input v-model="version" /></label
    ><button class="primary" :disabled="store.busy || !version" @click="update">
      暂存后更新已批准版本
    </button>
  </div>
</template>
