<script setup lang="ts">
import { useWorkspace } from '../stores/workspace'
defineProps<{ labels: string[] }>()
const store = useWorkspace()
</script>
<template>
  <div
    v-if="store.operation && labels.includes(store.operation.label)"
    class="operation-feedback"
    aria-live="polite"
  >
    <p v-if="store.busy" class="state-note">{{ store.operationMessage }}</p>
    <p v-else-if="store.error" class="inline-error">{{ store.error }}</p>
  </div>
</template>
