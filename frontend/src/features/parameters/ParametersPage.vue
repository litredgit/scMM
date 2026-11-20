<script setup lang="ts">
import { computed, ref } from 'vue'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
const search = ref('')
const fields = computed(
  () =>
    store.configuration?.processing.filter(
      (item) =>
        item.name !== 'extraction_method' &&
        `${item.name} ${item.help}`.toLowerCase().includes(search.value.toLowerCase()),
    ) ?? [],
)
function format(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number')
    return value.toLocaleString('en-US', { useGrouping: false, maximumSignificantDigits: 21 })
  return Array.isArray(value) ? (value.length ? value.map(format).join(', ') : '空') : String(value)
}
</script>

<template>
  <section>
    <div class="page-title">
      <div>
        <h1>参数参考</h1>
        <p>默认值和帮助从后端定义读取，已有项目保留创建时的参数。</p>
      </div>
    </div>
    <div class="card parameter-reference">
      <div class="section-heading">
        <h2>提取参数</h2>
        <input v-model="search" aria-label="搜索参数" placeholder="搜索参数名称或解释" />
      </div>
      <p class="muted">
        在<RouterLink to="/raw">预览</RouterLink>中编辑参数，在<RouterLink to="/extraction"
          >提取</RouterLink
        >中核对逐样本生效值。参考离子须按实际实验选择。
      </p>
      <p v-if="search.trim() && !fields.length" class="muted">没有匹配的提取参数。</p>
      <div v-else class="table-scroll parameter-reference-table">
        <table>
          <thead>
            <tr>
              <th scope="col">参数</th>
              <th scope="col" class="parameter-value">当前项目值</th>
              <th scope="col" class="parameter-value">新项目默认值</th>
              <th scope="col">说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in fields" :key="item.name">
              <td>
                <FieldLabel :name="item.name" :text="item.help" />
              </td>
              <td class="parameter-value">
                {{ store.project ? format(store.project.manifest.parameters[item.name]) : '—' }}
              </td>
              <td class="parameter-value">{{ format(item.default) }}</td>
              <td>{{ item.help }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.parameter-reference .section-heading {
  align-items: center;
  margin-bottom: 8px;
}
.parameter-reference .section-heading h2 {
  margin: 0;
}
.parameter-reference .section-heading input {
  width: min(100%, 320px);
}
.parameter-reference a {
  color: var(--teal);
  text-decoration: underline;
}
.parameter-reference-table {
  max-height: calc(100dvh - 230px);
  min-height: 100px;
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
  overflow: auto;
}
.parameter-reference-table th {
  position: sticky;
  top: 0;
  z-index: 1;
}
.parameter-value {
  text-align: right;
}
</style>
