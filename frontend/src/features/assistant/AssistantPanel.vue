<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import AssistantMarkdown from './AssistantMarkdown.vue'
import { useAssistant } from './useAssistant'

const open = ref(false)
const helpOpen = ref(false)
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const conversation = ref<HTMLElement | null>(null)
const messageList = ref<HTMLElement | null>(null)
const following = ref(true)
const store = useWorkspace()
const {
  messages,
  input,
  busy,
  error,
  context,
  model,
  responseModel,
  configured,
  configStatus,
  historyStatus,
  historyIssue,
  historyReady,
  send,
  stop,
  clear,
} = useAssistant()

const blocked = computed(() => {
  if (configStatus.value === 'loading') return '正在读取 AI 配置…'
  if (configStatus.value === 'disabled') return '服务器尚未启用 AI 助手，请联系管理员。'
  if (configStatus.value === 'unavailable') return 'AI 配置读取失败，请刷新后重试。'
  if (!configured.value) return '请先配置个人 AI API。'
  if (!store.current || !historyReady.value) return historyIssue.value || historyStatus.value
  return ''
})
const documents = computed(() => {
  const items = context.value?.documents
  if (!Array.isArray(items)) return undefined
  return items.filter(
    (item) =>
      typeof item?.guide === 'string' &&
      typeof item.section === 'string' &&
      typeof item.excerpt === 'string',
  )
})
const workspaceSummary = computed(() => {
  if (!context.value) return ''
  const { documents: _documents, ...snapshot } = context.value
  return JSON.stringify(snapshot, null, 2)
})

function followConversation() {
  const view = conversation.value
  if (open.value && following.value && view) view.scrollTop = view.scrollHeight
}
function checkScroll() {
  const view = conversation.value
  if (view && open.value)
    following.value = view.scrollHeight - view.clientHeight - view.scrollTop <= 40
}
function jumpToLatest() {
  following.value = true
  followConversation()
}
function ask(question?: string) {
  if (blocked.value || busy.value) return
  jumpToLatest()
  void send(question)
}
watch(
  open,
  async (value) => {
    emit('update:open', value)
    if (!value) helpOpen.value = false
    await nextTick()
    followConversation()
  },
  { immediate: true },
)
watch(messages, async () => {
  following.value = true
  await nextTick()
  followConversation()
})
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(followConversation)
  if (messageList.value) observer.observe(messageList.value)
  if (conversation.value) observer.observe(conversation.value)
})
onBeforeUnmount(() => observer?.disconnect())

const questions = [
  '当前进行到哪一步了？',
  '当前结果说明什么？',
  '下一步建议做什么？',
  '查阅本页使用指南',
]
</script>

<template>
  <aside class="ai-assistant" aria-label="AI 分析助手">
    <button
      class="ai-toggle"
      :aria-expanded="open"
      aria-controls="assistant-content"
      @click="open = !open"
    >
      {{ open ? '收起 AI 助手' : 'AI 分析助手' }}<span v-if="busy"> · 生成中</span>
    </button>
    <section v-show="open" id="assistant-content" class="ai-body" aria-labelledby="assistant-title">
      <header class="ai-heading">
        <h2 id="assistant-title">AI 分析助手</h2>
        <span v-if="busy" class="muted" role="status">生成中</span>
        <button
          type="button"
          class="ai-help-toggle"
          :aria-expanded="helpOpen"
          aria-controls="assistant-help"
          @click="helpOpen = !helpOpen"
        >
          说明与上下文
        </button>
      </header>
      <div v-show="helpOpen" id="assistant-help" class="ai-help">
        <p>当前模型 {{ model || '未配置' }}</p>
        <p v-if="responseModel">本轮模型 {{ responseModel }}</p>
        <p class="muted" role="status">{{ historyStatus }}</p>
        <p>助手提供解释与建议。服务器按白名单提供工作区摘要和相关 scMM 使用指南摘录。</p>
        <p>对话按用户和工作区加密保存并可恢复。发送内容另受所选 AI 服务的数据留存规则约束。</p>
        <section v-if="documents" aria-label="本轮查阅的文档">
          <h3>本轮查阅的文档</h3>
          <p v-if="!documents.length" class="muted">未找到相关使用指南摘录。</p>
          <details v-for="document in documents" :key="`${document.guide} · ${document.section}`">
            <summary>《{{ document.guide }}》· {{ document.section }}</summary>
            <pre class="ai-excerpt">{{ document.excerpt }}</pre>
          </details>
        </section>
        <details v-if="context">
          <summary>本轮工作区摘要</summary>
          <pre class="ai-summary">{{ workspaceSummary }}</pre>
        </details>
      </div>
      <div class="ai-conversation">
        <div
          ref="conversation"
          class="ai-messages"
          role="log"
          aria-label="当前对话"
          :aria-live="busy ? 'off' : 'polite'"
          @scroll.passive="checkScroll"
        >
          <div ref="messageList" class="ai-message-list">
            <div v-if="!messages.length" class="ai-empty">
              <p>可以问当前步骤、结果含义，或查阅使用指南。</p>
              <div class="quick-questions">
                <button
                  v-for="question in questions"
                  :key="question"
                  type="button"
                  :disabled="!!blocked || busy"
                  @click="ask(question)"
                >
                  {{ question }}
                </button>
              </div>
            </div>
            <article v-for="(turn, i) in messages" :key="i" :class="turn.role">
              <strong>{{ turn.role === 'user' ? '你' : 'AI' }}</strong>
              <AssistantMarkdown
                v-if="turn.role === 'assistant' && turn.content"
                :content="turn.content"
                :streaming="busy && i === messages.length - 1"
              />
              <p v-else class="ai-plain">
                {{ turn.content || (busy ? '正在等待回答…' : '未收到回答') }}
              </p>
              <p
                v-if="turn.note && (i < messages.length - 1 || turn.note !== error)"
                class="ai-plain muted"
              >
                {{ turn.note }}
              </p>
            </article>
          </div>
        </div>
        <button v-if="!following" type="button" class="ai-jump" @click="jumpToLatest">
          回到最新消息
        </button>
      </div>
      <form class="ai-composer" @submit.prevent="ask()">
        <p v-if="configStatus === 'ready' && !configured" class="ai-status">
          <RouterLink to="/account">前往我的账号配置 API</RouterLink>
        </p>
        <p v-else-if="blocked" class="ai-status" role="status">{{ blocked }}</p>
        <p v-else-if="historyIssue" class="ai-status" role="alert">{{ historyIssue }}</p>
        <p v-if="error" class="ai-status" role="alert">{{ error }}</p>
        <label for="ai-question" class="ai-question-label">问题</label>
        <textarea
          id="ai-question"
          v-model="input"
          rows="2"
          maxlength="8000"
          :disabled="busy || !!blocked"
          aria-describedby="ai-message-privacy"
          placeholder="询问步骤、结果含义或下一步建议"
        />
        <div class="ai-actions">
          <button
            type="button"
            :disabled="!historyReady || (!messages.length && !input)"
            @click="clear"
          >
            清空对话
          </button>
          <button v-if="busy" type="button" class="restore" @click="stop()">停止生成</button>
          <button v-else class="primary" :disabled="!!blocked || !input.trim()">发送</button>
        </div>
        <p id="ai-message-privacy" class="muted">问题和近期对话会发给所选 AI，请避开敏感信息。</p>
      </form>
    </section>
  </aside>
</template>

<style scoped>
.ai-toggle[aria-expanded='true'] {
  background: #e7f4f4;
  border-color: #8cbebb;
  color: var(--teal);
}
.ai-body {
  position: fixed;
  top: calc(var(--topbar-height) + 9px);
  right: 18px;
  bottom: 18px;
  width: min(424px, calc(100vw - 36px));
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  overflow: hidden;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-raised);
  font-size: 0.88rem;
}
@media (max-width: 760px) {
  .ai-body {
    top: 132px;
  }
}
.ai-heading {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ai-heading h2 {
  margin: 0;
  font-size: 1rem;
}
.ai-help-toggle {
  margin-inline-start: auto;
}
.ai-help {
  flex: none;
  max-height: min(34dvh, 320px);
  overflow: auto;
  overscroll-behavior: contain;
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
  padding: 8px 10px;
  background: var(--panel-soft);
}
.ai-help h3 {
  font-size: 1em;
}
.ai-help p,
.ai-help h3,
.ai-help details {
  margin: 4px 0;
}
.ai-help :is(p, summary, pre) {
  overflow-wrap: anywhere;
}
.ai-help summary {
  cursor: pointer;
}
.ai-help pre {
  white-space: pre-wrap;
  margin: 5px 0 8px;
}
.ai-excerpt {
  font: inherit;
}
.ai-summary {
  font-size: 0.8rem;
}
.ai-conversation {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
}
.ai-messages {
  flex: 1 1 auto;
  min-width: 0;
  overflow: auto;
  overscroll-behavior: contain;
  overflow-anchor: none;
}
.ai-empty {
  padding: 8px 0;
}
.ai-empty p {
  margin: 0 0 6px;
}
.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.quick-questions button {
  font-size: 0.8rem;
}
.ai-messages article {
  border-radius: var(--control-radius);
  padding: 7px 9px;
  margin: 0 0 6px;
  background: #f0f5f3;
}
.ai-messages .user {
  background: #e5f2f6;
}
.ai-plain {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 4px 0 0;
}
.ai-jump {
  position: absolute;
  inset-inline-start: 50%;
  bottom: 8px;
  transform: translateX(-50%);
  box-shadow: var(--shadow-card);
}
.ai-composer {
  flex: none;
  display: grid;
  gap: 4px;
  border-top: 1px solid var(--border);
  padding-top: 7px;
}
.ai-composer p {
  margin: 0;
  overflow-wrap: anywhere;
}
.ai-question-label {
  width: 1px;
  height: 1px;
  clip-path: inset(50%);
  overflow: hidden;
  position: absolute;
}
.ai-composer textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 50px;
  max-height: 26dvh;
  resize: vertical;
}
.ai-actions {
  display: flex;
  justify-content: space-between;
  gap: 6px;
}
</style>
