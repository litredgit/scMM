<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { fieldHelp } from '../help/fields'
import HelpTip from './HelpTip.vue'
import { displayName } from '../help/labels'
const props = defineProps<{ name: string; helpKey?: string; text?: string }>()
const store = useWorkspace()
const explanation = computed(
  () =>
    props.text ||
    fieldHelp[props.helpKey ?? props.name] ||
    [...(store.configuration?.processing ?? []), ...(store.configuration?.analysis ?? [])].find(
      (p) => p.name === (props.helpKey ?? props.name),
    )?.help ||
    '',
)
const tooltip = computed(() =>
  [props.helpKey ?? props.name, explanation.value].filter(Boolean).join(' · '),
)
</script>
<template>
  <span class="field-label">{{ displayName(name) }}<HelpTip :text="tooltip" :label="name" /></span>
</template>
