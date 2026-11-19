<script setup lang="ts">
import { computed } from 'vue'
import { modules, type ModuleKey } from './modules'
import ModuleExchange from './ModuleExchange.vue'
import { useWorkspace } from '../../stores/workspace'
const props = defineProps<{ module: ModuleKey }>()
const current = computed(() => modules.find((module) => module.key === props.module)!)
const store = useWorkspace()
const quantitationMissing = computed(
  () =>
    props.module === 'statistics' &&
    (!store.project?.dataset ||
      !store.project.dataset.cells ||
      store.project.dataset.quantitation_available === false),
)
</script>
<template>
  <section class="module-home">
    <div class="page-title">
      <div>
        <h1>{{ current.name }}</h1>
        <p>{{ current.subtitle }}</p>
      </div>
    </div>
    <dl class="module-context">
      <div>
        <dt>输入数据</dt>
        <dd>{{ current.input }}</dd>
      </div>
      <div>
        <dt>输出结果</dt>
        <dd>{{ current.output }}</dd>
      </div>
    </dl>
    <ModuleExchange :module="module" />
    <p v-if="quantitationMissing" class="state-note">
      统计分析需要定量矩阵。请在上方导入矩阵，或选择细胞提取板块中已审核纳入的数据；独立特征表可继续用于注释。
    </p>
    <section class="card module-workflow">
      <h2>工作步骤</h2>
      <ul class="module-workflow-list">
        <li v-for="step in current.steps.slice(1)" :key="step.path">
          <button v-if="quantitationMissing" disabled>
            <strong>{{ step.name }}</strong>
            <span>导入定量矩阵后可用</span>
          </button>
          <RouterLink v-else :to="step.path">
            <strong>{{ step.name }}</strong>
            <span>进入 <span aria-hidden="true">→</span></span>
          </RouterLink>
        </li>
      </ul>
    </section>
    <nav class="module-continue" aria-label="其他工作板块">
      <RouterLink
        v-for="item in modules.filter((item) => item.key !== module)"
        :key="item.key"
        :to="item.path"
        >{{ item.name }} <span aria-hidden="true">→</span></RouterLink
      ><RouterLink to="/results">结果与保存 <span aria-hidden="true">→</span></RouterLink>
    </nav>
  </section>
</template>

<style scoped>
.module-context {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 1.5rem;
  margin: 0 0 1rem;
  color: var(--muted);
  font-size: 0.86rem;
}
.module-context > div {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0.65rem;
}
.module-context dt {
  color: #45575c;
  font-weight: 600;
}
.module-context dd {
  margin: 0;
}
.module-workflow h2 {
  margin-bottom: 0.7rem;
}
.module-workflow-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.module-workflow-list li + li {
  border-top: 1px solid var(--border);
}
.module-workflow-list a,
.module-workflow-list button {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.8rem 0.5rem;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: left;
  font-size: 0.9rem;
}
.module-workflow-list a:hover {
  background: var(--panel-soft);
  color: var(--teal);
}
.module-workflow-list span {
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 400;
}
.module-continue {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.5rem;
  font-size: 0.86rem;
  color: var(--teal);
}
.module-continue a:hover {
  text-decoration: underline;
}
@media (max-width: 760px) {
  .module-context {
    grid-template-columns: 1fr;
  }
}
</style>
