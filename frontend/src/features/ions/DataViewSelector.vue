<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { ionPath, type IonInfo } from '../../api/ions'
const store = useWorkspace()
const info = ref<IonInfo>()
const selected = ref('')
let generation = 0
async function refresh() {
  const token = ++generation
  const result = await store.read<IonInfo>(ionPath('info'), undefined, () => token === generation)
  if (result) {
    info.value = result
    selected.value = result.active_branch_id ?? ''
  }
}
watch(
  () => [store.current?.workspace_id, store.current?.revision],
  () => void refresh(),
  { immediate: true },
)
async function activate() {
  const branch = info.value?.branches.find((row) => row.id === selected.value)
  if (!branch || !info.value) return
  await store.command(ionPath('activate'), {
    view_id: branch.view_id,
    branch_id: branch.id,
    catalog_revision: info.value.catalog_revision,
  })
}
</script>
<template>
  <div v-if="info?.initialized" class="card analysis-input-bar">
    <label>
      <span>分析视图与分支</span>
      <select v-model="selected" aria-label="分析视图与分支" :disabled="store.busy">
        <option v-for="branch in info.branches" :key="branch.id" :value="branch.id">
          {{ info.views.find((row) => row.id === branch.view_id)?.level }} · {{ branch.cells }} 细胞
          × {{ branch.variables }} 变量 · {{ branch.id.slice(0, 8) }}
        </option>
      </select>
    </label>
    <HelpTip
      label="L0、L1 与 L2"
      text="L0 保留全部特征；L1 保留未知并按审阅去冗余；L2 使用固定代表离子。各分支独立预处理和保存结果。"
    />
    <button
      class="primary"
      :disabled="store.busy || !selected || selected === info.active_branch_id"
      @click="activate"
    >
      作为统计输入
    </button>
    <div class="actions">
      <RouterLink to="/annotation">回看测量峰与候选 →</RouterLink>
      <RouterLink v-if="$route.path !== '/ions'" to="/ions">定量视图 →</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.analysis-input-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px 10px;
  padding: 8px 12px;
  margin-bottom: 10px;
}
.analysis-input-bar > label {
  flex: 0 1 450px;
  flex-direction: row;
  align-items: center;
  min-width: 0;
  gap: 8px;
}
.analysis-input-bar label > span {
  flex-shrink: 0;
}
.analysis-input-bar > .actions {
  gap: 12px;
  margin: 0 0 0 auto;
  color: var(--teal);
}
.analysis-input-bar a:hover {
  text-decoration: underline;
}
</style>
