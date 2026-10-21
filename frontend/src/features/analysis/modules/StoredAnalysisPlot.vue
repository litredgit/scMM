<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import { useViewState } from '../../../api/viewState'
import PlotView from '../../../components/PlotView.vue'
import type { Figure } from '../../../api/types'
const props = withDefaults(
  defineProps<{
    kind: string
    title: string
    options: Record<string, unknown>
    ready?: boolean
  }>(),
  { ready: true },
)
const { store, info, refreshAnalysis } = useAnalysisContext()
const figure = ref<Figure>()
let generation = 0
const identity = () =>
  JSON.stringify([store.current?.workspace_id, store.project?.path, store.project?.dataset?.id])
watch(identity, () => {
  generation++
  figure.value = undefined
})
watch(
  () => info.value?.figures,
  (value) => {
    if (value && !value.includes(props.kind)) figure.value = undefined
  },
)
const metadata = computed(
  () =>
    (figure.value?.layout.meta ?? {}) as { notes?: string[]; parameters?: Record<string, unknown> },
)
const edited = computed(() => {
  const saved = metadata.value.parameters
  return (
    saved &&
    [...new Set([...Object.keys(saved), ...Object.keys(props.options)])].some(
      (key) => JSON.stringify(saved[key]) !== JSON.stringify(props.options[key]),
    )
  )
})
async function draw(saved = false) {
  const target = identity(),
    token = ++generation
  await store.analysisTransaction(async (api) => {
    const value = saved
      ? await api.read<Figure>(`/analysis/figures/${props.kind}`)
      : await api.command<Figure>('/analysis/plot', { kind: props.kind, options: props.options })
    if (value && target === identity() && token === generation && api.isCurrent?.() !== false) {
      figure.value = value
      await refreshAnalysis(api)
    }
  })
}
useViewState(props.kind, { figure })
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>{{ title }}</h2>
      <slot />
      <div class="actions">
        <button class="primary" :disabled="store.busy || ready === false" @click="draw()">
          生成{{ title }}
        </button>
        <button
          v-if="info?.figures.includes(kind)"
          class="preview"
          :disabled="store.busy"
          @click="draw(true)"
        >
          读取已保存{{ title }}
        </button>
      </div>
      <p class="muted">
        编辑草稿不自动重算。主动保存保留只读图及完整导出表；相关输入改变后须重新计算。
      </p>
    </section>
    <section class="analysis-visualization">
      <h3>图形与说明</h3>
      <p v-if="edited">参数已编辑，重新生成后生效。</p>
      <p v-for="note in metadata.notes ?? []" :key="note">{{ note }}</p>
      <PlotView v-if="figure" :figure="figure" :name="kind" />
      <p v-else class="empty-state">设置输入后生成，或读取已保存的只读图。</p>
    </section>
  </div>
</template>
