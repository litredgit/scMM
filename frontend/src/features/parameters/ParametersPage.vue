<script setup lang="ts">
import { computed, ref } from 'vue'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
const search = ref('')
const fields = computed(
  () =>
    store.configuration?.processing.filter((item) =>
      `${item.name} ${item.help}`.toLowerCase().includes(search.value.toLowerCase()),
    ) ?? [],
)
function format(value: unknown, name?: string) {
  if (name === 'extraction_method' && value === 'snr_v1') return 'snr'
  return Array.isArray(value) ? (value.length ? value.join(', ') : '空') : String(value)
}
</script>

<template>
  <section>
    <div class="page-title">
      <div>
        <p class="eyebrow">REFERENCE / 参数</p>
        <h1>参数参考</h1>
        <p>默认值和帮助从后端定义读取，已有项目保留创建时的参数。</p>
      </div>
    </div>
    <div class="card">
      <div class="section-heading">
        <h2>提取参数</h2>
        <input v-model="search" aria-label="搜索参数" placeholder="搜索参数名称或解释" />
      </div>
      <p class="muted">
        此页只读；在第二步编辑参数，在第三步检查实际提取参数。实验参考离子须按实际实验明确选择。
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>参数</th>
              <th>当前项目值</th>
              <th>新项目默认值</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in fields" :key="item.name">
              <td>
                <FieldLabel :name="item.name" :text="item.help" />
              </td>
              <td>
                {{
                  store.project
                    ? format(store.project.manifest.parameters[item.name], item.name)
                    : '—'
                }}
              </td>
              <td>{{ format(item.default, item.name) }}</td>
              <td>{{ item.help }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
