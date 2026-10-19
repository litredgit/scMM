<script setup lang="ts">
import { computed } from 'vue'
import FieldLabel from './FieldLabel.vue'
import { displayName } from '../help/labels'
const props = defineProps<{ value: unknown }>()
const entries = computed(() =>
  props.value && typeof props.value === 'object' && !Array.isArray(props.value)
    ? Object.entries(props.value as Record<string, unknown>)
    : null,
)
</script>
<template>
  <dl v-if="entries" class="report-fields">
    <div v-for="[key, item] in entries" :key="key">
      <dt><FieldLabel :name="key" /></dt>
      <dd><ReportView :value="item" /></dd>
    </div>
  </dl>
  <span v-else-if="Array.isArray(value)">{{
    value.length > 100
      ? `${JSON.stringify(value.slice(0, 100))} … 共 ${value.length} 项，完整值见下载`
      : JSON.stringify(value)
  }}</span
  ><span v-else>{{ typeof value === 'string' ? displayName(value) : value }}</span>
</template>
<style scoped>
.report-fields {
  display: grid;
  gap: 0.5rem;
  min-width: 0;
}
.report-fields > div {
  display: grid;
  grid-template-columns: minmax(100px, 1fr) minmax(0, 3fr);
  gap: 0.6rem;
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
dt {
  font-weight: 600;
}
@media (max-width: 600px) {
  .report-fields > div {
    grid-template-columns: 1fr;
  }
}
</style>
