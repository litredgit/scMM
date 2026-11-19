<script setup lang="ts">
import ModuleExchange from './ModuleExchange.vue'
import LipidPanel from '../preprocess/LipidPanel.vue'
import DataViewSelector from '../ions/DataViewSelector.vue'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
</script>
<template>
  <section class="module-home">
    <div class="page-title">
      <div>
        <h1>特征注释</h1>
        <p>选择数据库，核对谱图候选并完成人工审核。</p>
      </div>
      <nav class="annotation-links" aria-label="注释关联工作">
        <RouterLink to="/ions">离子归组与来源视图 →</RouterLink
        ><RouterLink to="/statistics">使用当前矩阵进行统计分析 →</RouterLink>
      </nav>
    </div>
    <ModuleExchange module="annotation" />
    <DataViewSelector v-if="store.project?.dataset" />
    <LipidPanel v-if="store.project?.dataset" />
  </section>
</template>

<style scoped>
.annotation-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.4rem 1.25rem;
  color: var(--teal);
  font-size: 0.85rem;
}
.annotation-links a:hover {
  text-decoration: underline;
}
@media (max-width: 760px) {
  .annotation-links {
    justify-content: flex-start;
  }
}
</style>
