<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { useReadScope } from '../../api/readScope'
import { workspaceBlob, saveBlob } from '../../api/workspaceDownload'
import { base64File, type ModuleStatus } from '../../api/moduleExchange'
import type { ModuleKey } from './modules'

const props = defineProps<{ module: ModuleKey; compact?: boolean }>()
const store = useWorkspace()
const status = ref<ModuleStatus>()
const source = ref('current')
const format = ref('package')
const orientation = ref('observations_rows')
const observationKind = ref('cell')
const upload = ref<File>()
const metadata = ref<File>()
const features = ref<File>()
const exportFormat = ref('package')
const localError = ref('')
const lastImport = ref('')
const preview = ref('')
const preparing = ref(false)
watch(
  () => [store.current?.workspace_id, store.project?.path],
  () => {
    upload.value = undefined
    metadata.value = undefined
    features.value = undefined
    lastImport.value = ''
    preview.value = ''
    localError.value = ''
    source.value = 'current'
  },
)
const reads = useReadScope(
  () => [store.current?.workspace_id, store.project?.path, store.current?.revision, props.module],
  () => void refresh(),
)
async function refresh() {
  const accept = reads.begin()
  if (!accept()) return
  status.value = undefined
  if (!store.project) return
  const value = await store.read<ModuleStatus>(
    `/exchange/${props.module}/status`,
    undefined,
    accept,
  )
  if (accept()) status.value = value
}
watch(
  () => [store.current?.workspace_id, store.project?.path, store.current?.revision, props.module],
  () => void refresh(),
  { immediate: true },
)
const unit = computed(() => (status.value?.observation_kind === 'sample' ? '样本' : '细胞'))
const currentAvailable = computed(() => !!status.value?.features)
const canImport = computed(
  () => !!store.project && !!upload.value && !store.busy && !preparing.value,
)
async function selected(event: Event, target: 'main' | 'metadata' | 'features') {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (target === 'main') {
    upload.value = file
    preview.value = ''
    if (file && ['matrix_csv', 'feature_csv'].includes(format.value)) {
      const text = await file.slice(0, 12000).text()
      if (upload.value === file) preview.value = text.split(/\r?\n/).slice(0, 8).join('\n')
    }
  } else if (target === 'metadata') metadata.value = file
  else features.value = file
  localError.value = ''
}
function template(kind: 'matrix' | 'features' | 'observations') {
  const values = {
    matrix: 'Sample,Label,100.1,200.2\ncell_1,Group A,10,20\ncell_2,Group B,30,40\n',
    features: 'feature_id,mz\nf1,100.1\nf2,200.2\n',
    observations:
      'observation_id,sample,group,subject,batch\ncell_1,Sample A,Group A,,Batch 1\ncell_2,Sample A,Group B,,Batch 1\n',
  }
  saveBlob(new Blob([values[kind]], { type: 'text/csv;charset=utf-8' }), `${kind}-template.csv`)
}
async function importData() {
  if (!canImport.value || !upload.value) return
  preparing.value = true
  localError.value = ''
  const file = upload.value
  const workspace = store.current?.workspace_id
  const project = store.project?.path
  const revision = store.current?.revision
  try {
    const body: Record<string, unknown> = {
      format: format.value,
      filename: file.name,
      orientation: orientation.value,
      observation_kind: observationKind.value,
    }
    if (['matrix_csv', 'feature_csv'].includes(format.value)) {
      body.matrix_csv = await file.text()
      if (metadata.value) body.observations_csv = await metadata.value.text()
      if (features.value) body.features_csv = await features.value.text()
    } else body.file_base64 = await base64File(file)
    if (
      store.current?.workspace_id !== workspace ||
      store.project?.path !== project ||
      store.current?.revision !== revision
    ) {
      localError.value = '项目或数据已改变，请重新检查导入文件。'
      return
    }
    const value = await store.mutate(
      `/exchange/${props.module}/import`,
      body,
      'POST',
      '导入已完成，请检查数据摘要。',
    )
    if (value) {
      lastImport.value = file.name
      source.value = 'current'
      await refresh()
    }
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    preparing.value = false
  }
}
async function download() {
  const current = store.current
  if (!current || !store.project || store.busy) return
  const identity = [current.workspace_id, current.revision, store.project.path]
  await store.run(
    async (scope) => {
      const blob = await workspaceBlob(
        `/exchange/${props.module}/export?format=${exportFormat.value}&revision=${current.revision}`,
        {
          workspace: current.workspace_id,
          isCurrent: () =>
            scope.isCurrent() &&
            JSON.stringify(identity) ===
              JSON.stringify([
                store.current?.workspace_id,
                store.current?.revision,
                store.project?.path,
              ]),
        },
      )
      const suffix =
        { package: 'scmm-exchange.zip', csv: 'tables.zip', h5ad: 'h5ad', features: 'features.csv' }[
          exportFormat.value
        ] ?? 'zip'
      saveBlob(blob, `${props.module}.${suffix}`)
    },
    '',
    { label: '导出板块数据', phase: 'reading' },
  )
}
const exportChoices = computed(() =>
  [
    { value: 'package', label: '完整交换包（来源、关系与审核）' },
    { value: 'csv', label: '开放表格包（矩阵与元数据）' },
    { value: 'h5ad', label: '当前矩阵 H5AD' },
    { value: 'features', label: '特征表 CSV' },
  ].filter((item) => !status.value || status.value.exports.includes(item.value)),
)
watch(exportChoices, (choices) => {
  if (!choices.some((item) => item.value === exportFormat.value))
    exportFormat.value = choices[0]?.value ?? 'package'
})
</script>

<template>
  <section class="card module-exchange" :class="{ compact }" aria-label="板块数据导入与导出">
    <h2 v-if="!compact">选择本板块的数据</h2>
    <p v-if="!store.project" class="state-note">
      请先<RouterLink to="/projects">创建或打开项目</RouterLink
      >，导入的数据和审核记录将保存在该项目中。
    </p>
    <template v-else>
      <div class="module-exchange-tools">
        <div class="module-source-tabs" role="group" aria-label="数据来源">
          <button
            type="button"
            :class="{ active: source === 'current' }"
            :aria-pressed="source === 'current'"
            @click="source = 'current'"
          >
            使用当前项目数据
          </button>
          <button
            type="button"
            :class="{ active: source === 'import' }"
            :aria-pressed="source === 'import'"
            @click="source = 'import'"
          >
            导入外部数据
          </button>
        </div>
        <div class="module-export">
          <label
            >导出内容<select
              v-model="exportFormat"
              :disabled="store.busy || !currentAvailable"
              aria-label="板块导出格式"
            >
              <option v-for="choice in exportChoices" :key="choice.value" :value="choice.value">
                {{ choice.label }}
              </option>
            </select></label
          >
          <button
            class="save"
            :disabled="store.busy || !currentAvailable || !exportChoices.length"
            @click="download"
          >
            导出本板块数据
          </button>
        </div>
      </div>
      <div
        v-if="
          source === 'current' && (!compact || !currentAvailable || lastImport || status?.notice)
        "
        class="module-data-summary"
      >
        <div v-if="compact && currentAvailable" class="compact-data-summary">
          <p v-if="status?.feature_only" class="muted">
            独立特征表可用于注释，统计分析需要定量矩阵。
          </p>
          <p v-if="lastImport" role="status">已导入：{{ lastImport }}</p>
        </div>
        <template v-else-if="currentAvailable">
          <strong
            >{{ status?.features.toLocaleString() }} 个特征<span v-if="!status?.feature_only">
              · {{ status?.observations.toLocaleString() }} 个{{ unit }}</span
            ></strong
          >
          <p>{{ status?.source || '当前项目数据' }}</p>
          <p class="muted">
            {{
              status?.feature_only
                ? '独立特征表可用于注释，统计分析需要定量矩阵。'
                : '当前数据可继续用于其他板块。'
            }}
          </p>
          <p v-if="status?.has_catalogue" class="muted">包含独立来源视图与分析分支。</p>
        </template>
        <p v-else-if="!status">正在读取数据状态…</p>
        <p v-else>当前项目尚无可用数据。可导入已有数据，或在细胞提取中处理原始谱并审核纳入。</p>
        <p v-if="status?.notice" class="muted">{{ status.notice }}</p>
        <p v-if="lastImport && (!compact || !currentAvailable)" role="status">
          已导入：{{ lastImport }}
        </p>
      </div>
      <form v-else-if="source === 'import'" class="module-import" @submit.prevent="importData">
        <fieldset :disabled="store.busy || preparing" class="module-import-fields">
          <div class="field-grid">
            <label
              >文件格式<select v-model="format" :disabled="store.busy" aria-label="板块导入格式">
                <option value="package">scMM 完整交换包</option>
                <option value="h5ad">H5AD 矩阵</option>
                <option value="matrix_csv">定量矩阵 CSV</option>
                <option v-if="module === 'annotation'" value="feature_csv">
                  独立 m/z 特征表 CSV
                </option>
              </select></label
            >
            <label
              >数据文件<input
                type="file"
                :accept="format === 'package' ? '.zip' : format === 'h5ad' ? '.h5ad' : '.csv,.txt'"
                :disabled="store.busy"
                aria-label="板块数据文件"
                @change="selected($event, 'main')"
            /></label>
          </div>
          <div v-if="['matrix_csv', 'feature_csv'].includes(format)" class="actions">
            <button
              type="button"
              class="save"
              @click="template(format === 'feature_csv' ? 'features' : 'matrix')"
            >
              下载格式模板
            </button>
            <button
              v-if="format === 'matrix_csv'"
              type="button"
              class="save"
              @click="template('observations')"
            >
              下载观测元数据模板
            </button>
          </div>
          <details v-if="preview" open class="import-preview">
            <summary>文件内容预览（前 8 行）</summary>
            <pre>{{ preview }}</pre>
          </details>
          <template v-if="format === 'matrix_csv'">
            <div class="field-grid">
              <label
                >矩阵方向<select v-model="orientation" aria-label="矩阵方向">
                  <option value="observations_rows">细胞 / 样本在行，特征在列</option>
                  <option value="observations_columns">特征在行，细胞 / 样本在列</option>
                </select></label
              >
              <label
                >每行观测对象<select v-model="observationKind" aria-label="观测单位">
                  <option value="cell">单细胞</option>
                  <option value="sample">普通样本</option>
                </select></label
              >
              <label
                >观测元数据（可选）<input
                  type="file"
                  accept=".csv,.txt"
                  aria-label="观测元数据文件"
                  @change="selected($event, 'metadata')"
              /></label>
              <label
                >特征元数据（可选）<input
                  type="file"
                  accept=".csv,.txt"
                  aria-label="特征元数据文件"
                  @change="selected($event, 'features')"
              /></label>
            </div>
            <p class="muted">
              以稳定 ID 对齐矩阵与元数据。支持 MetaboAnalyst 分组布局；细胞数与生物重复数分别记录。
            </p>
          </template>
          <p v-if="format === 'feature_csv'" class="muted">
            特征表需包含 feature_id 和 mz；只建立注释输入，不生成定量观测。
          </p>
          <p v-if="format === 'package'" class="state-note">
            完整包将替换当前全部数据来源、分支、处理起点与报告。请先保存需要保留的当前状态，导入完成后可主动保存新状态。
          </p>
          <p v-else-if="format === 'feature_csv' || format === 'h5ad'" class="muted">
            导入仅特征表时将替换当前数据集合，定量数据及其关联来源可通过已保存项目重新打开。完整校验通过后生效。
          </p>
          <p v-else class="muted">
            导入将替换当前活动数据，完整校验通过后生效。请先保存需要保留的当前状态。
          </p>
          <button class="primary" :disabled="!canImport">
            {{
              preparing
                ? '正在读取与检查文件…'
                : format === 'package'
                  ? '导入并替换全部数据来源'
                  : '检查并导入本板块'
            }}
          </button>
        </fieldset>
      </form>
      <p v-if="localError" role="alert" class="state-note">{{ localError }}</p>
    </template>
  </section>
</template>

<style scoped>
.module-exchange.compact {
  padding: 8px 12px;
  margin-bottom: 10px;
}
.module-exchange-tools,
.module-source-tabs,
.module-export {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.module-exchange-tools {
  justify-content: space-between;
  gap: 8px 16px;
}
.module-source-tabs button {
  min-height: 32px;
  padding: 5px 10px;
}
.module-source-tabs button.active {
  border-color: #91beb8;
  background: #e8f5f2;
  color: var(--teal);
  font-weight: 650;
}
.module-data-summary,
.module-import {
  margin: 8px 0 0;
  padding: 6px 0;
}
.module-data-summary p {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}
.compact .module-data-summary {
  margin-top: 4px;
  padding: 0;
}
.compact-data-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}
.module-import {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
  background: var(--panel-soft);
}
.module-import-fields {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}
.module-import .actions {
  margin: 8px 0;
}
.module-export label {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  color: var(--muted);
}
.module-export select {
  width: auto;
  max-width: 100%;
  min-height: 32px;
}
.module-export button {
  min-height: 32px;
}
.import-preview {
  margin: 0.75rem 0;
  min-width: 0;
}
.import-preview pre {
  max-width: 100%;
  overflow: auto;
  font-size: 0.8rem;
  background: white;
  padding: 0.65rem;
}
@media (max-width: 560px) {
  .module-export,
  .module-export label,
  .module-export select,
  .module-export button {
    width: 100%;
    max-width: none;
  }
  .module-export label {
    flex-direction: column;
    align-items: start;
  }
}
</style>
