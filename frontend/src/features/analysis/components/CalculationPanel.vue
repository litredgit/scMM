<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
const props = defineProps<{ hasResult: boolean; resultTarget?: string }>()
const { parametersPinned, store } = useAnalysisContext()
const open = ref(!props.hasResult)
function toggle() {
  open.value = !(open.value || parametersPinned.value)
  parametersPinned.value = false
}
const element = ref<HTMLElement>()
let requested = false
function track(event: MouseEvent) {
  if ((event.target as Element).closest('button.primary')) requested = true
}
watch(
  () => props.hasResult,
  async (value) => {
    if (!value) {
      open.value = true
      return
    }
    if (!parametersPinned.value) {
      open.value = false
      await nextTick()
      if (requested && element.value?.getClientRects().length) {
        const target =
          (props.resultTarget && document.getElementById(props.resultTarget)) || element.value
        const header = document.querySelector('.topbar')?.getBoundingClientRect().height ?? 0
        window.scrollTo({
          top: Math.max(0, scrollY + target.getBoundingClientRect().top - header - 12),
        })
      }
    }
    requested = false
  },
)
watch(
  () => store.busy,
  (busy) => {
    if (!busy && store.error) open.value = true
  },
)
</script>
<template>
  <section
    ref="element"
    @click.capture="track"
    class="analysis-calculation"
    :class="{ 'parameters-pinned': parametersPinned, 'has-result': hasResult }"
  >
    <div class="calculation-heading actions">
      <button :aria-expanded="open || parametersPinned" @click="toggle">
        {{ open || parametersPinned ? '收起计算参数' : '展开计算参数' }}
      </button>
      <button
        :class="{ selected: parametersPinned }"
        :aria-pressed="parametersPinned"
        @click="parametersPinned = !parametersPinned"
      >
        {{ parametersPinned ? '取消固定参数区' : '固定参数区' }}
      </button>
      <span v-if="store.busy" role="status">{{ store.operationMessage }}</span>
    </div>
    <div v-show="open || parametersPinned" class="calculation-body"><slot /></div>
  </section>
</template>
