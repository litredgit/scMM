<script setup lang="ts">
import { onActivated, ref } from 'vue'
import { request } from '../../api/client'
type Configuration = { available: boolean; configured: boolean; base_url: string; model: string }
const config = ref<Configuration | null>(null)
const baseURL = ref('')
const model = ref('')
const key = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
async function act(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '操作失败，请重试。'
  } finally {
    busy.value = false
  }
}
async function load() {
  config.value = await request<Configuration>('/ai/config')
  baseURL.value = config.value.base_url
  model.value = config.value.model
  key.value = ''
}
onActivated(() => void act(load))
async function save() {
  // Clear the transient input even on failure. Never use browser persistence.
  const apiKey = key.value
  key.value = ''
  await act(async () => {
    config.value = await request<Configuration>('/ai/config', {
      method: 'PUT',
      body: {
        base_url: baseURL.value,
        model: model.value,
        api_key: apiKey,
      },
    })
    notice.value = '个人 API 配置已保存。'
    window.dispatchEvent(new Event('scmm-ai-config-changed'))
  })
}
async function remove() {
  await act(async () => {
    await request('/ai/config', { method: 'DELETE' })
    await load()
    notice.value = '个人 API 配置已删除。'
    window.dispatchEvent(new Event('scmm-ai-config-changed'))
  })
}
async function testConnection() {
  await act(async () => {
    await request('/ai/test', { method: 'POST' })
    notice.value = '连接测试通过（使用已保存配置，不附带实验上下文）。'
  })
}
</script>
<template>
  <form class="card" @submit.prevent="save" aria-label="个人 AI API 配置">
    <h2>AI 分析助手 · 个人 API</h2>
    <p>
      支持 OpenAI 兼容 Chat Completions。API Key 在服务器加密保存，按账号隔离，下次登录继续使用。
    </p>
    <p v-if="config && !config.available" role="status">
      服务器尚未启用个人 AI 配置，请联系管理员。
    </p>
    <p v-else role="status">
      API Key：{{ config?.configured ? '已配置，可替换或删除' : '未配置' }}
    </p>
    <label
      >Base URL<input
        v-model="baseURL"
        type="url"
        placeholder="https://api.openai.com/v1"
        required
        maxlength="2048"
        autocomplete="off"
    /></label>
    <label>Model<input v-model="model" required maxlength="200" autocomplete="off" /></label>
    <label
      >API Key<input
        v-model="key"
        type="password"
        required
        maxlength="4096"
        autocomplete="new-password"
        placeholder="保存或替换时输入新 Key"
    /></label>
    <p class="muted">
      保存时请同时输入地址、模型和
      Key；测试连接使用已保存配置，会发送最小测试问题，可能产生费用。内网或本机服务须管理员明确放行。
    </p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="actions">
      <button class="primary" :disabled="busy || !config?.available">保存 API 配置</button>
      <button type="button" :disabled="busy || !config?.configured" @click="testConnection">
        测试连接
      </button>
      <button type="button" :disabled="busy || !config?.configured" @click="remove">
        删除 API 配置
      </button>
    </div>
  </form>
</template>
<style scoped>
label {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
</style>
