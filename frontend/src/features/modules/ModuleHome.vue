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
    <div class="module-intake-grid">
      <ModuleExchange :module="module" />
      <section class="card module-workflow">
        <h2>工作步骤</h2>
        <p v-if="quantitationMissing" id="matrix-required" class="muted">
          导入定量矩阵或审核纳入提取结果后，即可开始统计分析。
        </p>
        <ul class="module-workflow-list">
          <li v-for="step in current.steps.slice(1)" :key="step.path">
            <button v-if="quantitationMissing" disabled aria-describedby="matrix-required">
              {{ step.name }}
            </button>
            <RouterLink v-else :to="step.path">
              {{ step.name }} <span aria-hidden="true">→</span>
            </RouterLink>
          </li>
        </ul>
      </section>
    </div>
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
.module-intake-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(235px, 0.36fr);
  align-items: start;
  gap: 14px;
}
.module-context {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 1.5rem;
  margin: 0 0 12px;
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
  min-height: 36px;
  padding: 7px 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: left;
  font-size: var(--text-body);
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
  .module-context,
  .module-intake-grid {
    grid-template-columns: 1fr;
  }
}
</style>
