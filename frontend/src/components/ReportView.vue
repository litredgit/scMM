<script setup lang="ts">
import { computed } from 'vue'
import FieldLabel from './FieldLabel.vue'
import { displayName } from '../help/labels'
const props = defineProps<{ value: unknown; observationKind?: string }>()
const entries = computed(() =>
  props.value && typeof props.value === 'object' && !Array.isArray(props.value)
    ? Object.entries(props.value as Record<string, unknown>)
    : null,
)
const observationKind = computed(() => {
  const value = props.value as { statistical_unit?: string } | null
  return value?.statistical_unit ?? props.observationKind
})
const sampleLabels: Record<string, string> = {
  all_source_support: '全部已标记样本与来源组',
  train_source_support: '训练集样本与来源组',
  test_source_support: '留出集样本与来源组',
  cv_source_support: '逐折样本与来源组',
  excluded_unlabelled_cells: '未标记而排除的样本数',
  cells: '样本数',
}
</script>
<template>
  <dl v-if="entries" class="report-fields">
    <div v-for="[key, item] in entries" :key="key">
      <dt>
        <FieldLabel :name="observationKind === 'sample' ? (sampleLabels[key] ?? key) : key" />
      </dt>
      <dd><ReportView :value="item" :observation-kind="observationKind" /></dd>
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
