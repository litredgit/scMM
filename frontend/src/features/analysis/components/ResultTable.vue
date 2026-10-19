<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ResultName } from '../types'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import DataTableView from '../../../components/DataTable.vue'
const props = defineProps<{ name: ResultName; heading?: boolean }>()
const { tables, has } = useAnalysisContext()
const negative = ref(false)
const shown = computed(() => {
  const table = tables.value[props.name]
  return table && props.name === 'markers' && !negative.value
    ? { ...table, rows: table.rows.filter((r) => r.weight === undefined || Number(r.weight) > 0) }
    : table
})
</script>
<template>
  <template v-if="has(name) && tables[name]"
    ><h3 v-if="heading">{{ name }}</h3>
    <label v-if="name === 'markers'"
      ><input type="checkbox" v-model="negative" />同时显示负权重</label
    >
    <DataTableView v-if="shown" :table="shown"
  /></template>
</template>
