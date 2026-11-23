<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ionPath } from '../../api/ions'
import { useIonSource } from './useIonSource'
const { store, info, root, selectedTarget, command, safely } = useIonSource()
const evidenceLinks = ref('{}')
const linkResult = ref<unknown>()
const scheme = ref('MSI')
const version = ref('')
const level = ref('')
const criteria = ref('')
const scope = ref('')
const structure = ref('unresolved')
const evidenceIds = ref<string[]>([])
const target = computed(() => {
  const selected = selectedTarget.value
  if (!selected || !root.value) return
  const targetVersion = selected.kind === 'feature' ? root.value : selected.version
  if (targetVersion) return { kind: selected.kind, id: selected.id, version: targetVersion }
})
watch(
  () => [store.project?.path, root.value],
  () => {
    evidenceIds.value = []
    linkResult.value = undefined
  },
)
async function linkEvidence() {
  linkResult.value = await store.command(
    ionPath('evidence/preview'),
    JSON.parse(evidenceLinks.value),
  )
}
async function saveAssertion() {
  if (!target.value) return
  const result = await command('assertion', {
    target: target.value,
    scheme: scheme.value,
    version: version.value.trim(),
    level: level.value.trim(),
    criteria: { statement: criteria.value.trim() },
    evidence_ids: evidenceIds.value,
    scope: { root_id: root.value, description: scope.value.trim() },
    structure_level: structure.value.trim(),
  })
  if (result) store.notice = '鉴定声明已登记，请主动保存项目。'
}
</script>
<template>
  <div v-if="info?.initialized" class="card">
    <details>
      <summary>外部证据匹配预览</summary>
      <label title="evidence_ids/targets/mapping/ppm：目标包含 kind/id/version/mz/scope"
        >匹配请求 JSON<textarea v-model="evidenceLinks" rows="4" /></label
      ><button class="preview" :disabled="store.busy" @click="safely(linkEvidence)">
        预览版本与作用域匹配
      </button>
      <pre v-if="linkResult">{{ JSON.stringify(linkResult, null, 2) }}</pre>
    </details>
    <details>
      <summary>鉴定标准与脂质结构层级声明</summary>
      <p v-if="target">当前对象 {{ target.kind }} · {{ target.id }}</p>
      <p v-else>先在候选与关系审核中选中测量峰、候选或离子组。</p>
      <div class="field-grid">
        <label
          >标准<select v-model="scheme">
            <option v-for="item in ['MSI', 'Schymanski', 'LSI', 'custom']" :key="item">
              {{ item }}
            </option>
          </select></label
        >
        <label>标准版本<input v-model="version" /></label>
        <label>鉴定等级<input v-model="level" /></label>
        <label>结构层级<input v-model="structure" /></label>
        <label>适用范围<input v-model="scope" /></label>
        <label>采用的判据<textarea v-model="criteria" rows="2" /></label>
        <label
          >已导入证据<select v-model="evidenceIds" multiple>
            <option v-for="item in info.evidence" :key="item.id" :value="item.id">
              {{ item.label }} · {{ item.id.slice(0, 8) }}
            </option>
          </select></label
        >
      </div>
      <p class="muted">由审核人声明，保留标准版本、判据、作用域和证据引用。</p>
      <button
        class="primary"
        :disabled="
          store.busy ||
          !target ||
          !version.trim() ||
          !level.trim() ||
          !criteria.trim() ||
          !scope.trim() ||
          !evidenceIds.length
        "
        @click="safely(saveAssertion)"
      >
        保存鉴定声明
      </button>
    </details>
  </div>
</template>
