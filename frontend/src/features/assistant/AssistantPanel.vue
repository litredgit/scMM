<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useAssistant } from './useAssistant'
import { useWorkspace } from '../../stores/workspace'
const open = ref(false)
const conversation = ref<HTMLElement | null>(null)
const store = useWorkspace()
const {
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
  clear,
} = useAssistant()
watch(
  () => messages.value.map((m) => m.content + (m.note ?? '')).join(''),
  async () => {
    await nextTick()
    if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight
  },
)
const questions = ['当前进行到哪一步了？', '当前结果说明什么？', '下一步建议做什么？']
</script>
<template>
  <aside class="ai-assistant" :class="{ open }" aria-label="AI 分析助手">
    <button class="ai-toggle primary" :aria-expanded="open" @click="open = !open">
      {{ open ? '收起 AI 助手' : 'AI 分析助手' }}<span v-if="busy"> · 生成中</span>
    </button>
    <section v-show="open" class="ai-body">
      <h2>AI 分析助手</h2>
      <p role="status">{{ historyStatus }}</p>
      <p>只读解释与建议 · 当前模型：{{ model || '未配置' }}</p>
      <p class="muted">
        自动发送当前步骤、已生效参数和匿名汇总，不发送原始谱、矩阵、样本名或路径。你输入的问题会原样发给所选
        AI，请自行排除敏感信息。
      </p>
      <p class="muted">
        对话按用户与工作区加密保存，刷新或服务维护后可恢复；切换项目分别保留。服务商的数据留存规则另行适用。AI
        建议须人工判断。
      </p>
      <p v-if="!configured"><RouterLink to="/account">前往我的账号配置 API</RouterLink></p>
      <div class="quick-questions">
        <button
          v-for="question in questions"
          :key="question"
          :disabled="busy || !historyReady || !configured || !store.current"
          @click="send(question)"
        >
          {{ question }}
        </button>
      </div>
      <div
        ref="conversation"
        class="ai-messages"
        aria-label="当前对话"
        aria-live="polite"
        aria-relevant="additions text"
      >
        <article v-for="(turn, i) in messages" :key="i" :class="turn.role">
          <strong>{{ turn.role === 'user' ? '你' : 'AI' }}</strong>
          <p>{{ turn.content || (busy ? '正在等待回答…' : '未收到回答') }}</p>
          <p v-if="turn.note" class="muted">{{ turn.note }}</p>
        </article>
      </div>
      <details v-if="context">
        <summary>本次发送的上下文</summary>
        <pre>{{ JSON.stringify(context, null, 2) }}</pre>
      </details>
      <p v-if="error" role="alert">{{ error }}</p>
      <form @submit.prevent="send()">
        <label for="ai-question">问题</label>
        <textarea
          id="ai-question"
          v-model="input"
          rows="3"
          maxlength="8000"
          :disabled="busy || !historyReady"
          placeholder="询问步骤、结果含义或下一步建议"
        />
        <div class="actions">
          <button
            class="primary"
            :disabled="busy || !historyReady || !configured || !store.current || !input.trim()"
          >
            发送
          </button>
          <button type="button" :disabled="!busy" @click="stop()" class="restore">停止生成</button>
          <button type="button" :disabled="!historyReady" @click="clear">清空对话</button>
        </div>
      </form>
    </section>
  </aside>
</template>
<style scoped>
.ai-assistant {
  position: fixed;
  right: 1.25rem;
  bottom: 1rem;
  z-index: 40;
  max-width: calc(100vw - 2rem);
}
.ai-toggle {
  float: right;
  box-shadow: 0 3px 16px #0002;
}
.ai-body {
  clear: both;
  width: 430px;
  max-width: calc(100vw - 2rem);
  max-height: calc(100dvh - 6rem);
  overflow: auto;
  padding: 1.2rem;
  background: var(--surface, white);
  color: var(--text, #172b32);
  border: 1px solid #d2dfdc;
  border-radius: 14px;
  box-shadow: 0 8px 35px #0002;
}
.ai-body h2 {
  margin-top: 0;
}
.ai-body p {
  font-size: 0.88rem;
}
.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.quick-questions button {
  font-size: 0.8rem;
}
.ai-messages {
  margin: 1rem 0;
  max-height: 42dvh;
  overflow: auto;
}
.ai-messages article {
  border-radius: 8px;
  padding: 0.7rem;
  margin: 0.6rem 0;
  background: #f0f5f3;
}
.ai-messages .user {
  background: #e5f2f6;
}
.ai-messages p,
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
pre {
  max-height: 240px;
  overflow: auto;
  font-size: 0.75rem;
}
textarea {
  width: 100%;
  box-sizing: border-box;
  margin: 0.5rem 0;
}
</style>
