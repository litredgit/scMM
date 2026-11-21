<script setup lang="ts">
import ScientificInput from '../../components/ScientificInput.vue'
import type { PluginMethod, PluginValue } from '../../api/types'

defineProps<{ method: PluginMethod; observations?: string[]; disabled?: boolean }>()
const model = defineModel<Record<string, PluginValue>>({ required: true })
const emit = defineEmits<{ edited: [] }>()
</script>

<template>
  <label v-for="field in method.parameters" :key="field.key" class="field">
    <FieldLabel :name="field.label" :text="field.help" />
    <select
      v-if="field.kind === 'choice' || field.kind === 'observation' || field.kind === 'boolean'"
      v-model="model[field.key]"
      :aria-label="field.label"
      :disabled="disabled"
      @change="emit('edited')"
    >
      <option :value="null" disabled>请选择</option>
      <template v-if="field.kind === 'boolean'">
        <option :value="true">是</option>
        <option :value="false">否</option>
      </template>
      <option
        v-for="choice in field.kind === 'observation' ? observations : field.choices"
        :key="choice"
        :value="choice"
      >
        {{ choice }}
      </option>
    </select>
    <ScientificInput
      v-else-if="field.kind === 'integer' || field.kind === 'number'"
      v-model="model[field.key]"
      :aria-label="field.label"
      :disabled="disabled"
      @update:model-value="emit('edited')"
    />
    <input
      v-else
      v-model="model[field.key]"
      :aria-label="field.label"
      :disabled="disabled"
      @input="emit('edited')"
    />
  </label>
</template>
