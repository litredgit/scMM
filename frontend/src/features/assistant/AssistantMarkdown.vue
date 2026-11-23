<script lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, linkify: false }).disable('autolink')
const httpsLink = /^https:\/\//i
markdown.validateLink = (value) => {
  if (!httpsLink.test(value)) return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password
  } catch {
    return false
  }
}
markdown.renderer.rules.image = (tokens, index) => markdown.utils.escapeHtml(tokens[index].content)
markdown.renderer.rules.link_open = (tokens, index, options, _env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}

function renderMessage(content: string) {
  if (!DOMPurify.isSupported) return markdown.utils.escapeHtml(content)
  return DOMPurify.sanitize(markdown.render(content), {
    ALLOWED_TAGS: [
      'a',
      'blockquote',
      'br',
      'code',
      'em',
      'h1',
      'h2',
      'h3',
      'h4',
      'h5',
      'h6',
      'hr',
      'li',
      'ol',
      'p',
      'pre',
      's',
      'strong',
      'table',
      'thead',
      'tbody',
      'tr',
      'th',
      'td',
      'ul',
    ],
    ALLOWED_ATTR: ['href', 'rel', 'start', 'target', 'title'],
    ADD_URI_SAFE_ATTR: ['rel', 'start', 'target'],
    ALLOWED_URI_REGEXP: httpsLink,
    ALLOW_ARIA_ATTR: false,
    ALLOW_DATA_ATTR: false,
  })
}
</script>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ content: string; streaming: boolean }>()
const html = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
function render() {
  timer = undefined
  html.value = renderMessage(props.content)
}
watch(
  () => [props.content, props.streaming] as const,
  ([, streaming]) => {
    if (!streaming) {
      clearTimeout(timer)
      render()
    } else if (timer === undefined) {
      timer = setTimeout(render, 80)
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="ai-markdown" v-html="html"></div>
</template>

<style scoped>
.ai-markdown {
  min-width: 0;
  overflow-wrap: anywhere;
  line-height: 1.45;
}
.ai-markdown :deep(p),
.ai-markdown :deep(ul),
.ai-markdown :deep(ol),
.ai-markdown :deep(blockquote),
.ai-markdown :deep(pre),
.ai-markdown :deep(table) {
  margin: 0.4rem 0;
}
.ai-markdown :deep(:is(h1, h2, h3, h4, h5, h6)) {
  font-size: 1em;
  line-height: 1.4;
  margin: 0.55rem 0 0.3rem;
}
.ai-markdown :deep(ul),
.ai-markdown :deep(ol) {
  padding-inline-start: 1.3rem;
}
.ai-markdown :deep(blockquote) {
  border-inline-start: 2px solid var(--border);
  padding-inline-start: 0.65rem;
}
.ai-markdown :deep(code),
.ai-markdown :deep(pre) {
  background: var(--surface);
  border-radius: var(--control-radius);
}
.ai-markdown :deep(code) {
  padding: 0 0.2em;
}
.ai-markdown :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
  padding: 0.45rem;
}
.ai-markdown :deep(pre code) {
  padding: 0;
}
.ai-markdown :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
}
.ai-markdown :deep(th),
.ai-markdown :deep(td) {
  padding: 0.2rem 0.35rem;
  border: 1px solid var(--border);
}
</style>
