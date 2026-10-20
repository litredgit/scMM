import { nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { authenticatedFetch, request, sessionVersion, ensureSession } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
import { useAuth } from '../../stores/auth'

type Turn = { role: 'user' | 'assistant'; content: string; note?: string | null }
type Configuration = { configured: boolean; model: string; available: boolean }
export function useAssistant() {
  const store = useWorkspace()
  const auth = useAuth()
  const route = useRoute()
  const messages = ref<Turn[]>([])
  const input = ref('')
  const busy = ref(false)
  const error = ref('')
  const context = ref<unknown>(null)
  const model = ref('')
  const configured = ref(false)
  let controller: AbortController | undefined
  let epoch = 0
  let configGeneration = 0
  let historyKey = '',
    historyOwner = '',
    historyGeneration = 0
  const historyReady = ref(false)
  let historyTimer: ReturnType<typeof setTimeout> | undefined
  let writes: Promise<unknown> = Promise.resolve()
  const revisions = new Map<string, number>()
  const historyStatus = ref('')
  function snapshot() {
    return JSON.parse(
      JSON.stringify({
        messages: messages.value,
        draft: input.value,
        streaming: busy.value,
        summary: context.value && typeof context.value === 'object' ? context.value : null,
        model: model.value,
      }),
    )
  }
  function persist(key = historyKey, owner = historyOwner, payload = snapshot()) {
    if (!key || !owner || !historyReady.value) return writes
    const session = sessionVersion()
    historyStatus.value = '正在保存聊天'
    writes = writes
      .catch(() => {})
      .then(async () => {
        if (auth.user?.id !== owner || session !== sessionVersion()) return
        const value = await request<{ revision: number }>('/ai/history', {
          method: 'PUT',
          body: {
            context: key,
            revision: revisions.get(key) ?? 0,
            ...payload,
          },
        })
        revisions.set(key, value.revision)
        if (key === historyKey) historyStatus.value = '聊天已加密保存'
      })
      .catch((cause) => {
        if (auth.user?.id === owner && key === historyKey)
          historyStatus.value = `聊天未保存：${String(cause)}`
        throw cause
      })
    return writes
  }
  watch(
    [messages, input, busy, context],
    () => {
      if (!historyReady.value) return
      if (historyTimer) clearTimeout(historyTimer)
      historyTimer = setTimeout(() => void persist().catch(() => {}), 250)
    },
    { deep: true },
  )
  async function restoreHistory(generation: number) {
    const key = historyKey,
      owner = historyOwner
    const current = () => generation === historyGeneration && auth.user?.id === owner
    try {
      await writes.catch(() => {})
      if (!current()) return
      const session = sessionVersion()
      const currentSession = () => current() && session === sessionVersion()
      const value = await request<{
        revision: number
        messages: Turn[]
        draft: string
        streaming: boolean
        summary: unknown
        model?: string
      }>(`/ai/history?${new URLSearchParams({ context: key })}`)
      if (!currentSession()) return
      revisions.set(key, value.revision)
      messages.value = value.messages
      input.value = value.draft
      context.value = value.summary
      if (value.model) model.value = value.model
      if (value.streaming && messages.value.at(-1)?.role === 'assistant')
        messages.value.at(-1)!.note = '上次生成已中断，已恢复接收内容；未自动重新发送。'
      await nextTick()
      if (!currentSession()) return
      historyReady.value = true
      historyStatus.value = '聊天已恢复'
    } catch (cause) {
      if (generation === historyGeneration) historyStatus.value = `聊天恢复不可用：${String(cause)}`
    }
  }
  function stop(note = '已停止生成；已接收部分仅供参考。') {
    epoch++
    controller?.abort()
    controller = undefined
    if (busy.value) {
      const last = messages.value.at(-1)
      if (last?.role === 'assistant') last.note = note
    }
    busy.value = false
  }
  function clear(stored = true) {
    stop()
    messages.value = []
    input.value = ''
    context.value = null
    error.value = ''
    if (stored) void persist().catch(() => {})
  }
  async function loadConfig() {
    const session = sessionVersion(),
      generation = ++configGeneration
    try {
      const value = await request<Configuration>('/ai/config')
      ensureSession(session)
      if (generation !== configGeneration) return
      configured.value = value.configured
      model.value = value.model
    } catch {
      if (session !== sessionVersion() || generation !== configGeneration) return
      configured.value = false
      model.value = ''
    }
  }
  const configChanged = () => {
    stop('API 配置已改变，请重新提问。')
    void loadConfig()
  }
  window.addEventListener('scmm-ai-config-changed', configChanged)
  watch(
    () => [auth.user?.id, store.current?.workspace_id, store.project?.path],
    () => {
      if (historyReady.value && auth.user?.id === historyOwner) void persist().catch(() => {})
      historyReady.value = false
      historyStatus.value = store.current ? '正在恢复聊天…' : '进入项目首页后可开始对话'
      if (historyTimer) clearTimeout(historyTimer)
      ++historyGeneration
      clear(false)
      historyOwner = auth.user?.id ?? ''
      historyKey = store.current
        ? JSON.stringify([store.current.workspace_id, store.project?.path ?? ''])
        : ''
      if (auth.user && !auth.user.must_change) {
        void loadConfig()
        if (historyKey) void restoreHistory(historyGeneration)
      }
    },
    { immediate: true, flush: 'sync' },
  )
  watch(
    () => [store.project?.dataset?.id, store.project?.dataset?.revision, store.current?.revision],
    () => {
      if (busy.value) stop('项目或数据版本已改变，本回答依据已过期，请重新提问。')
    },
    { flush: 'sync' },
  )
  onUnmounted(() => {
    stop()
    if (historyTimer) clearTimeout(historyTimer)
    void persist().catch(() => {})
    window.removeEventListener('scmm-ai-config-changed', configChanged)
  })
  async function send(question = input.value) {
    if (!historyReady.value) {
      error.value = '聊天持久化尚未就绪，请稍后重试或刷新页面。'
      return
    }
    if (busy.value || !configured.value || !store.current || !question.trim()) return
    if (question.length > 8000) {
      error.value = '单条问题最多 8000 字符。'
      return
    }
    stop()
    const token = epoch
    const session = sessionVersion()
    controller = new AbortController()
    busy.value = true
    error.value = ''
    context.value = null
    // Incomplete/stale answers are displayed but never reused as model history.
    const history = messages.value
      .filter((m) => !m.note && m.content)
      .map(({ role, content }) => ({ role, content }))
    messages.value.push({ role: 'user', content: question.trim() })
    const answer: Turn = { role: 'assistant', content: '' }
    messages.value.push(answer)
    const index = messages.value.length - 1
    input.value = ''
    let ended = false
    const current = () => {
      ensureSession(session)
      return token === epoch
    }
    try {
      const response = await authenticatedFetch('/api/v1/ai/chat', {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          'X-SCMM-Workspace': store.current.workspace_id,
        },
        body: JSON.stringify({
          page: route.path.slice(1) || 'projects',
          messages: [...history.slice(-22), { role: 'user', content: question.trim() }],
        }),
      })
      if (!current()) return
      if (!response.ok) {
        const body = await response.json()
        throw new Error(body.error?.message ?? 'AI 请求失败。')
      }
      if (!response.body) throw new Error('浏览器无法读取事件流。')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (!current()) return
          buffer += decoder.decode(value, { stream: !done }).replace(/\r/g, '')
          if (buffer.length > 150000) throw new Error('AI 事件超过长度限制。')
          let split: number
          while ((split = buffer.indexOf('\n\n')) >= 0) {
            const event = buffer.slice(0, split)
            buffer = buffer.slice(split + 2)
            const name = event
              .split('\n')
              .find((line) => line.startsWith('event:'))
              ?.slice(6)
              .trim()
            const raw = event
              .split('\n')
              .filter((line) => line.startsWith('data:'))
              .map((line) => line.slice(5).trimStart())
              .join('\n')
            if (!raw) continue
            const data = JSON.parse(raw)
            if (name === 'context') {
              context.value = data.context
              model.value = data.model
            } else if (name === 'delta') messages.value[index]!.content += data.text
            else if (name === 'error') throw new Error(data.message)
            else if (name === 'done') ended = true
          }
          if (done || ended) break
        }
      } finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
      if (!ended) throw new Error('回答连接已中断；请手动重试。')
    } catch (cause) {
      if (token !== epoch) return
      const message = cause instanceof Error ? cause.message : 'AI 请求失败，请手动重试。'
      error.value = message
      messages.value[index]!.note = message
    } finally {
      if (token === epoch) {
        busy.value = false
        controller = undefined
        await persist().catch(() => {})
      }
    }
  }
  const maintenance = (event: Event) => {
    stop('服务维护前停止生成；已接收内容已保存。')
    ;(event as CustomEvent<{ waits: Promise<unknown>[] }>).detail.waits.push(persist())
  }
  window.addEventListener('scmm-before-maintenance', maintenance)
  onUnmounted(() => window.removeEventListener('scmm-before-maintenance', maintenance))
  return {
    messages,
    input,
    busy,
    error,
    context,
    model,
    configured,
    historyStatus,
    historyReady,
    send,
    stop,
    clear: () => clear(true),
  }
}
