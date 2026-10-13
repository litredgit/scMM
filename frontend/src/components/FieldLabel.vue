<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspace } from '../stores/workspace'
import { fieldHelp } from '../help/fields'
import HelpTip from './HelpTip.vue'
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
</script>
<template>
  <span class="field-label"
    >{{ name }}<HelpTip v-if="explanation" :text="explanation" :label="name"
  /></span>
</template>
