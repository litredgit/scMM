<script setup lang="ts">
import type { ResultName } from '../types'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import DataTableView from '../../../components/DataTable.vue'
defineProps<{ name: ResultName; heading?: boolean }>()
const { tables, has } = useAnalysisContext()
</script>
<template>
  <template v-if="has(name) && tables[name]"
    ><h3 v-if="heading">{{ name }}</h3>
    <DataTableView :table="tables[name]!"
  /></template>
</template>
