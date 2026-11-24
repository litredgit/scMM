<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef } from 'vue'
import {
  appendix,
  documentIndex,
  guideForPage,
  guides,
  loadDocument,
  sectionId,
  type DocumentLocation,
  type RenderedDocument,
} from './documentation'

const props = defineProps<{ page: string }>()
const dialog = ref<HTMLDialogElement>()
const content = ref<HTMLElement>()
const location = ref<DocumentLocation>(guideForPage(props.page))
const article = shallowRef<RenderedDocument>()
const failed = ref(false)
const inAppendix = computed(
  () =>
    ![documentIndex, 'README.md'].includes(location.value.file) &&
    !guides.some(({ file }) => file === location.value.file),
)
let pending: AbortController | undefined

function jumpTo(anchor?: string) {
  const pane = content.value
  if (!pane) return
  const heading = pane.querySelector<HTMLElement>(
    anchor ? `#${CSS.escape(sectionId(anchor))}` : 'h1',
  )
  pane.scrollTop = heading ? heading.offsetTop - 18 : 0
  heading?.focus({ preventScroll: true })
}

async function read(target: DocumentLocation) {
  pending?.abort()
  location.value = target
  if (article.value?.file === target.file) {
    jumpTo(target.anchor)
    return
  }

  const request = new AbortController()
  pending = request
  failed.value = false
  article.value = undefined
  try {
    const loaded = await loadDocument(target.file, request.signal)
    if (request.signal.aborted) return
    article.value = loaded
    await nextTick()
    if (!request.signal.aborted) jumpTo(target.anchor)
  } catch {
    if (!request.signal.aborted) failed.value = true
  }
}

function open() {
  dialog.value?.showModal()
  void read(guideForPage(props.page))
}

function followLink(event: MouseEvent) {
  if (!(event.target instanceof Element)) return
  const link = event.target.closest<HTMLAnchorElement>('a[data-document]')
  const file = link?.dataset.document
  if (!file) return
  event.preventDefault()
  void read({ file, anchor: link.dataset.section })
}

function stopReading() {
  pending?.abort()
}
onBeforeUnmount(stopReading)
</script>

<template>
  <button type="button" aria-haspopup="dialog" @click="open">项目文档</button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="project-docs"
      aria-labelledby="project-docs-heading"
      @close="stopReading"
    >
      <header class="docs-header">
        <h2 id="project-docs-heading">项目文档</h2>
        <button type="button" aria-label="关闭项目文档" autofocus @click="dialog?.close()">
          关闭
        </button>
      </header>
      <div class="docs-layout">
        <div class="docs-sidebar">
          <nav class="docs-nav" aria-label="文档目录">
            <button
              v-for="guide in guides"
              :key="guide.file"
              type="button"
              :aria-current="location.file === guide.file ? 'page' : undefined"
              @click="read({ file: guide.file })"
            >
              {{ guide.title }}
            </button>
            <button
              class="docs-appendix"
              type="button"
              :aria-current="inAppendix ? 'page' : undefined"
              @click="read({ file: appendix })"
            >
              附录
            </button>
          </nav>
          <nav v-if="article?.sections.length" class="docs-nav docs-sections" aria-label="本页章节">
            <h3>本页章节</h3>
            <button
              v-for="section in article.sections"
              :key="section.anchor"
              type="button"
              :aria-current="location.anchor === section.anchor ? 'location' : undefined"
              @click="read({ file: article.file, anchor: section.anchor })"
            >
              {{ section.title }}
            </button>
          </nav>
        </div>
        <section id="project-docs-content" ref="content" class="docs-content" aria-label="文档正文">
          <article v-if="article" v-html="article.html" @click="followLink"></article>
          <div v-else-if="failed" class="state-note">
            <p role="alert">文档加载失败。请检查连接后重试。</p>
            <button type="button" @click="read(location)">重试</button>
          </div>
          <p v-else role="status" class="muted">正在加载文档…</p>
        </section>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.project-docs {
  position: fixed;
  inset: 0 0 0 auto;
  width: min(100%, 1040px);
  height: 100%;
  max-width: none;
  max-height: none;
  margin: 0;
  padding: 0;
  border: 0;
  border-left: 1px solid var(--border);
  color: var(--text);
  background: var(--surface);
  box-shadow: var(--shadow-raised);
  font-size: var(--text-body);
}
.project-docs[open] {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}
.project-docs::backdrop {
  background: #172b3950;
}
:global(body:has(.project-docs[open])) {
  overflow: hidden;
}
.docs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: var(--topbar-height);
  padding: 8px 22px;
  border-bottom: 1px solid var(--border);
}
.docs-header h2 {
  margin: 0;
  font-size: var(--text-section);
}
.docs-layout {
  display: grid;
  grid-template-columns: 172px minmax(0, 1fr);
  min-height: 0;
}
.docs-sidebar,
.docs-content {
  overflow: auto;
  overscroll-behavior: contain;
}
.docs-sidebar {
  padding: 12px;
  background: var(--panel-soft);
  border-right: 1px solid var(--border);
}
.docs-nav {
  display: grid;
  gap: 2px;
}
.docs-nav button {
  padding: 4px 7px;
  border-color: transparent;
  background: transparent;
  text-align: left;
  justify-content: flex-start;
}
.docs-nav button[aria-current] {
  background: #e3eef7;
  color: var(--blue);
  font-weight: 650;
}
.docs-appendix {
  margin-top: 4px;
}
.docs-sections {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.docs-sections h3 {
  margin: 0 0 2px 7px;
  color: var(--muted);
  font-size: var(--text-small);
}
.docs-sections button {
  font-size: var(--text-small);
}
.docs-content {
  position: relative;
  padding: 18px 24px 26px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.docs-content :deep(h1) {
  margin: 0 0 10px;
  font-size: var(--text-title);
}
.docs-content :deep(h2) {
  margin-top: 22px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  font-size: var(--text-section);
}
.docs-content :deep(h3) {
  font-size: 14px;
}
.docs-content :deep(a[href]) {
  color: var(--blue);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.docs-content :deep(img) {
  display: block;
  max-width: 100%;
  height: auto;
}
.docs-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}
.docs-content :deep(th),
.docs-content :deep(td) {
  border: 1px solid var(--border);
  padding: 5px 8px;
  vertical-align: top;
}
.docs-content :deep(th) {
  background: var(--panel-soft);
  text-align: left;
}
.docs-content :deep(code) {
  padding: 1px 3px;
  border-radius: 3px;
  background: var(--panel-soft);
  font-size: 0.93em;
}
.docs-content :deep(pre) {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
  background: var(--panel-soft);
  overflow: auto;
}
.docs-content :deep(pre code) {
  padding: 0;
}
.docs-content :deep(blockquote) {
  margin: 10px 0;
  padding-left: 10px;
  border-left: 3px solid var(--border);
}
</style>
