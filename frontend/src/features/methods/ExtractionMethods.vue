<script setup lang="ts">
import { computed } from 'vue'
import MethodFields from './MethodFields.vue'
import { useWorkspace } from '../../stores/workspace'
import type { PluginMethod, PluginValue } from '../../api/types'

defineProps<{ disabled: boolean }>()
const model = defineModel<Record<string, unknown>>({ required: true })
const emit = defineEmits<{ edited: [] }>()
const store = useWorkspace()
const phases = { cell_detection: '细胞识别方法', cell_extraction: '特征定量方法' } as const
type Phase = keyof typeof phases
type Choice = { id: string; version: string; options: Record<string, PluginValue> }
const selections = computed(
  () => (model.value.method_plugins ?? {}) as Partial<Record<Phase, Choice>>,
)
function methods(phase: Phase) {
  return store.configuration?.methods.filter((method) => method.kind === phase) ?? []
}
function installed(phase: Phase) {
  const chosen = selections.value[phase]
  return methods(phase).find(
    (method) => method.id === chosen?.id && method.version === chosen.version,
  )
}
const visible = computed(() =>
  (Object.keys(phases) as Phase[]).filter(
    (phase) => methods(phase).length || selections.value[phase],
  ),
)
function setMethod(phase: Phase, event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const next = { ...selections.value }
  const method: PluginMethod | undefined = methods(phase).find((item) => item.id === id)
  if (method) {
    next[phase] = {
      id,
      version: method.version,
      options: Object.fromEntries(method.parameters.map((field) => [field.key, field.default])),
    }
  } else delete next[phase]
  if (Object.keys(next).length) model.value.method_plugins = next
  else delete model.value.method_plugins
  emit('edited')
}
</script>

<template>
  <details v-if="visible.length" class="parameter-section" :open="!!model.method_plugins">
    <summary>提取方法（项目级）</summary>
    <p v-if="disabled" class="muted">请在应用范围选择「项目默认」后编辑方法。</p>
    <div v-for="phase in visible" :key="phase" class="actions">
      <label class="field">
        <FieldLabel :name="phases[phase]" />
        <select
          :aria-label="phases[phase]"
          :value="installed(phase)?.id ?? (selections[phase] ? 'unavailable' : '')"
          :disabled="disabled"
          @change="setMethod(phase, $event)"
        >
          <option v-if="selections[phase] && !installed(phase)" value="unavailable" disabled>
            {{ selections[phase]?.id }} {{ selections[phase]?.version }} · 当前不可用
          </option>
          <option value="">snr_v1</option>
          <option v-for="method in methods(phase)" :key="method.id" :value="method.id">
            {{ method.label }} · {{ method.version }}
          </option>
        </select>
      </label>
      <MethodFields
        v-if="installed(phase) && selections[phase]"
        v-model="selections[phase]!.options"
        :method="installed(phase)!"
        :disabled="disabled"
        @edited="emit('edited')"
      />
    </div>
  </details>
</template>
