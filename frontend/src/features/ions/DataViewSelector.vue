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
  <div v-if="info?.initialized" class="card">
    <div class="field-grid">
      <label
        >分析视图与分支<select v-model="selected" aria-label="分析视图与分支">
          <option v-for="branch in info.branches" :key="branch.id" :value="branch.id">
            {{ info.views.find((row) => row.id === branch.view_id)?.level }} ·
            {{ branch.cells }} 细胞 × {{ branch.variables }} 变量 · {{ branch.id.slice(0, 8) }}
          </option>
        </select></label
      >
      <button
        class="primary"
        :disabled="store.busy || selected === info.active_branch_id"
        @click="activate"
      >
        切换分析分支
      </button>
    </div>
    <p class="muted">
      L0 保留全部特征；L1 保留未知并按审阅去冗余；L2 使用固定代表离子。各分支独立预处理和保存结果。
    </p>
    <RouterLink to="/ions">离子归组、化合物候选与证据</RouterLink>
  </div>
</template>
