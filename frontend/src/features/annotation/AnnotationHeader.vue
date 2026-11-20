<script setup lang="ts">
import { useWorkspace } from '../../stores/workspace'
import { useAnnotationSource } from './useAnnotationSource'
import ModuleExchange from '../modules/ModuleExchange.vue'

defineProps<{ title: string; version?: string; grouping?: string }>()
const store = useWorkspace()
const { sourceId, sources } = useAnnotationSource()
</script>

<template>
  <div class="page-title">
    <h1>{{ title }}</h1>
  </div>
  <div v-if="store.project" class="card annotation-context">
    <label v-if="sources.length">
      谱图来源
      <select v-model="sourceId" aria-label="谱图来源" :disabled="store.busy">
        <option v-for="item in sources" :key="item.id" :value="item.id">
          {{ item.label }} · {{ item.features }} 峰
        </option>
      </select>
    </label>
    <span v-else>谱图来源：无实测峰</span>
    <span>
      统计输入
      <strong>{{
        store.project.annotation?.statistics?.level ??
        (store.project.dataset?.quantitation_available ? '当前矩阵' : '未启用')
      }}</strong>
      <span
        v-if="store.project.annotation?.statistics"
        :title="store.project.annotation.statistics.branch_id"
      >
        {{ store.project.annotation.statistics.branch_id.slice(0, 8) }}
      </span>
    </span>
    <span v-if="version" :title="version">注释版本 {{ version.slice(0, 8) }}</span>
    <span v-if="grouping" :title="grouping">归组版本 {{ grouping.slice(0, 8) }}</span>
  </div>
  <ModuleExchange module="annotation" compact />
</template>

<style scoped>
.annotation-context.card {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 18px;
  padding: 8px 12px;
  margin-bottom: 8px;
  color: var(--muted);
}
.annotation-context label {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.annotation-context strong {
  color: var(--text);
}
.annotation-context select {
  width: auto;
  min-height: 32px;
}
</style>
