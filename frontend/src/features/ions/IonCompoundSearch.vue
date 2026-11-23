<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ionPath, type IonTable } from '../../api/ions'
import DataTableView from '../../components/DataTable.vue'
import { useIonSource, useIonPolarity } from './useIonSource'
const { store, info, root, version, command, safely, download } = useIonSource()
const { polarity, ppm, species } = useIonPolarity()
const annotation = ref('')
const table = ref<IonTable>()
const tableKind = ref('candidates')
const offset = ref(0)
let tableGeneration = 0
const databaseFormat = ref('json'),
  fieldMapping = ref<Record<string, string>>({})
const compoundTarget = ref('features'),
  compoundFormulas = ref('[]')
const database = ref(''),
  namespace = ref('local')
const localVersions = computed(
  () =>
    info.value?.annotation_versions?.filter(
      (key) => info.value?.annotation_roots?.[key] === root.value,
    ) ?? [],
)
watch(
  localVersions,
  (versions) => {
    if (!versions.includes(annotation.value)) annotation.value = versions.at(-1) ?? ''
  },
  { immediate: true },
)
watch([annotation, offset, () => store.current?.revision], () => void loadTable())
async function loadTable() {
  if (!info.value?.initialized) return
  const key = ['candidates', 'unknown'].includes(tableKind.value) ? annotation.value : version.value
  if (
    ['relations', 'groups', 'diagnostics', 'candidates', 'unknown'].includes(tableKind.value) &&
    !key
  ) {
    table.value = undefined
    return
  }
  const token = ++tableGeneration
  const query = new URLSearchParams({
    version: key,
    kind: tableKind.value,
    offset: String(offset.value),
    limit: '100',
  })
  const result = await store.read<IonTable>(
    `${ionPath('table')}?${query}`,
    undefined,
    () => token === tableGeneration,
  )
  if (result) table.value = result
}
async function annotate() {
  const records = databaseFormat.value === 'json' ? JSON.parse(database.value) : []
  const result = (await command('annotate', {
    root_id: root.value,
    version: compoundTarget.value === 'group' ? version.value || null : null,
    target_mode: compoundTarget.value === 'group' ? 'ec' : 'feature',
    formula_targets: compoundTarget.value === 'group' ? JSON.parse(compoundFormulas.value) : [],
    polarity: polarity.value,
    ppm: ppm.value,
    species: species.value,
    namespace: namespace.value,
    records,
    content: databaseFormat.value === 'json' ? '' : database.value,
    format: databaseFormat.value,
    field_mapping: Object.fromEntries(
      Object.entries(fieldMapping.value).filter(([, column]) => column),
    ),
  })) as { version: string } | undefined
  if (result) {
    annotation.value = result.version
    tableKind.value = 'candidates'
    offset.value = 0
  }
}
async function fileText(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const text = await file.text()
  database.value = text
  databaseFormat.value = file.name.toLowerCase().split('.').at(-1) ?? 'json'
}
const mappingFields = {
  record_id: '库记录 ID',
  name: '名称',
  formula: '分子式',
  exact_mass: '精确质量',
}
const columnNames = computed(() => {
  const input = database.value.replace(/^\uFEFF/, '')
  if (databaseFormat.value === 'sdf')
    return [...new Set(Array.from(input.matchAll(/^>\s*<([^>]+)>/gm), (match) => match[1]))]
  if (databaseFormat.value === 'json') {
    try {
      const rows = JSON.parse(input)
      return Array.isArray(rows) && rows[0] ? Object.keys(rows[0]) : []
    } catch {
      return []
    }
  }
  const separator = databaseFormat.value === 'tsv' ? '\t' : ','
  const header = input.split(/\r?\n/, 1)[0] ?? ''
  return (
    header.match(
      databaseFormat.value === 'tsv' ? /"(?:""|[^"])*"|[^\t]+/g : /"(?:""|[^"])*"|[^,]+/g,
    ) ?? []
  )
    .map((field) => field.trim().replace(/^"|"$/g, '').replaceAll('""', '"'))
    .filter((field) => field !== separator)
})
watch(columnNames, () => {
  fieldMapping.value = Object.fromEntries(
    Object.keys(mappingFields).flatMap((key) => {
      const selected = fieldMapping.value[key] || key
      return columnNames.value.includes(selected) ? [[key, selected]] : []
    }),
  )
})
</script>
<template>
  <div v-if="info?.initialized" class="card">
    <h3>本地化合物库 · 峰质量或组中性质量</h3>
    <label
      >目标<select v-model="compoundTarget">
        <option value="features">测量峰 m/z</option>
        <option value="group">已审阅离子组中性质量与已有分子式</option>
      </select></label
    >
    <label v-if="compoundTarget === 'group'"
      >已有分子式目标 JSON<textarea v-model="compoundFormulas" rows="2" />
    </label>
    <label
      >质量容差（ppm）<input v-model.number="ppm" type="number" step="any" min="0.001"
    /></label>
    <label>数据库命名空间<input v-model="namespace" /></label
    ><label
      >化合物库文件（JSON / CSV / TSV / SDF）<input
        type="file"
        accept=".json,.csv,.tsv,.sdf"
        @change="fileText($event)"
    /></label>
    <label title="record_id/name/formula/exact_mass：formula 与 exact_mass 至少提供一个"
      >候选库内容<textarea
        v-model="database"
        aria-label="候选库内容"
        rows="4"
        placeholder='[{"record_id":"id1","name":"compound","formula":"C6H12O6"}]'
      />
    </label>
    <div v-if="columnNames.length" class="field-grid" aria-label="数据库字段映射">
      <label v-for="(text, key) in mappingFields" :key="key"
        >{{ text }}
        <select v-model="fieldMapping[key]">
          <option value="">使用原字段</option>
          <option v-for="column in columnNames" :key="column" :value="column">{{ column }}</option>
        </select>
      </label>
    </div>
    <button
      class="primary"
      :disabled="store.busy || !root || !database || (compoundTarget === 'group' && !version)"
      @click="safely(annotate)"
    >
      搜索质量与已有公式候选
    </button>
    <label
      >注释版本<select v-model="annotation">
        <option v-for="key in localVersions" :key="key">{{ key }}</option>
      </select></label
    >
    <button
      class="download"
      :disabled="store.busy || !annotation"
      @click="download('annotation', annotation)"
    >
      下载完整候选
    </button>
    <DataTableView
      v-if="table && tableKind === 'candidates'"
      :table="{
        ...table.table,
        columns: [
          'target_id',
          'target_kind',
          'name',
          'namespace',
          'record_id',
          'species_id',
          'ppm_error',
        ],
      }"
    />
  </div>
</template>
