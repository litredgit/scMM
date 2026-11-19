<script setup lang="ts">
import { inject, nextTick, ref, watch } from 'vue'
import { analysisKey } from '../types'
import { useWorkspace } from '../../../stores/workspace'
const props = defineProps<{ hasResult: boolean; resultTarget?: string }>()
const context = inject(analysisKey, null)
const parametersPinned = context?.parametersPinned ?? ref(true)
const store = useWorkspace()
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
    <div class="calculation-heading actions" aria-label="计算参数工具">
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
<style scoped>
.calculation-heading {
  justify-content: flex-end;
  gap: 4px;
  margin-bottom: 12px;
  padding: 5px 7px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--panel-soft);
}
.calculation-heading button {
  min-height: 28px;
  padding: 4px 8px;
  border-color: transparent;
  background: transparent;
  font-size: 12px;
}
.calculation-heading button:hover {
  border-color: var(--border);
  background: white;
}
.calculation-heading .selected {
  border-color: #badce1;
  background: #e8f4f6;
  color: var(--teal);
}
.calculation-heading [role='status'] {
  margin-right: auto;
  color: var(--muted);
  font-size: 12px;
}
.calculation-body {
  min-width: 0;
}
.calculation-body :deep(> h2) {
  margin-bottom: 12px;
  font-size: 19px;
}
.calculation-body :deep(> h3) {
  margin-bottom: 10px;
  color: var(--muted);
  font-size: 13px;
}
@media (max-width: 600px) {
  .calculation-heading {
    justify-content: flex-start;
  }
}
</style>
