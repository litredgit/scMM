<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ionPath, type IonView } from '../../api/ions'
import { saveBlob, workspaceBlob } from '../../api/workspaceDownload'
import DataTableView from '../../components/DataTable.vue'
import DataViewSelector from './DataViewSelector.vue'
import AnnotationHeader from '../annotation/AnnotationHeader.vue'
import CompoundSourcePanel from './CompoundSourcePanel.vue'
import { useIonSource, ids } from './useIonSource'
const { store, info, version, versions, command, safely, download } = useIonSource()
const mode = ref('reviewed_v1'),
  strategy = ref('isotope_representatives'),
  singletons = ref(true)
const availabilityView = ref(''),
  availabilityAxis = ref('cells'),
  availabilityIds = ref(''),
  availability = ref<Record<string, unknown>>()
const comparison = ref(''),
  compareResult = ref<Record<string, unknown>>(),
  comparisonMode = ref('independent'),
  sharedFactors = ref('{}')
const replicateKey = ref('sample_id'),
  replicateGroup = ref('')
const importKind = ref('source_l2')
const mergeViews = ref<string[]>([]),
  mergeAlignments = ref('[]')
const representation = ref<{
  views: Record<string, unknown>[]
  metadata: Record<string, unknown>
}>()
const representationOptions = computed(() => ({
  version: version.value,
  mode: mode.value,
  strategy: strategy.value,
  include_singletons: singletons.value,
}))
watch(representationOptions, () => {
  representation.value = undefined
})
watch(
  () => store.current?.revision,
  () => {
    representation.value = undefined
  },
)
async function previewRepresentation() {
  representation.value = await store.command(
    ionPath('represent/preview'),
    representationOptions.value,
  )
}

async function mergeCompounds() {
  await command('merge-compounds', {
    view_ids: mergeViews.value,
    alignments: JSON.parse(mergeAlignments.value),
  })
}
async function previewAvailability() {
  const selected = info.value?.views.find((row) => row.id === availabilityView.value)
  if (!selected) return
  const selection = ids(availabilityIds.value)
  availability.value = await store.command<Record<string, unknown>>(ionPath('availability'), {
    view_id: selected.id,
    ...(availabilityAxis.value === 'cells'
      ? { cell_ids: selection.length ? selection : selected.cell_ids }
      : {
          variable_ids: selection.length
            ? selection
            : (selected.variable_ids ?? selected.feature_ids),
        }),
  })
}
watch(
  () => [availabilityView.value, availabilityAxis.value, availabilityIds.value],
  () => {
    availability.value = undefined
  },
)
async function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 75_000_000) {
    store.error = '导入文件超过网页 75 MB 工程上限。'
    return
  }
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192)
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  await command('import', { kind: importKind.value, content_base64: btoa(binary) })
}
async function compare() {
  compareResult.value = await store.command<Record<string, unknown>>(ionPath('compare'), {
    branch_ids: ids(comparison.value),
    normalization_mode: comparisonMode.value,
    shared_factors: comparisonMode.value === 'shared' ? JSON.parse(sharedFactors.value) : null,
  })
}
async function replicates() {
  const snapshot = store.current
  if (!snapshot) return
  await store.run(
    async (scope) => {
      const blob = await workspaceBlob(ionPath('replicates'), {
        workspace: snapshot.workspace_id,
        method: 'POST',
        body: {
          revision: snapshot.revision,
          replicate_key: replicateKey.value,
          group_key: replicateGroup.value || null,
        },
        isCurrent: () =>
          scope.isCurrent() &&
          store.current?.workspace_id === snapshot.workspace_id &&
          store.current?.revision === snapshot.revision,
      })
      saveBlob(blob, 'replicate-summary.csv')
    },
    '',
    { label: '下载重复汇总', phase: 'downloading' },
  )
}
function label(view: IonView) {
  return `${view.level} · ${view.cell_ids.length} × ${(view.variable_ids ?? view.feature_ids).length} · ${view.id.slice(0, 8)}`
}
</script>
<template>
  <section>
    <AnnotationHeader title="定量视图" :grouping="version" />
    <div v-if="!store.project" class="card">请先创建或打开项目。</div>
    <template v-else>
      <DataViewSelector />
      <template v-if="info?.initialized">
        <CompoundSourcePanel :views="info.views" />
        <div class="card">
          <h2>L0 / L1 / L2 来源与定量</h2>
          <div class="actions">
            <RouterLink to="/annotation">返回测量峰审核 →</RouterLink>
            <RouterLink to="/preprocess">进入统计预处理</RouterLink>
            <RouterLink to="/analysis">进入分析</RouterLink>
          </div>
          <ul>
            <li v-for="view in info.views" :key="view.id">
              {{ label(view) }} · 来源 {{ view.root_id.slice(0, 8) }}
            </li>
          </ul>
          <label
            >构建依据<select v-model="version">
              <option value="">选择归组版本</option>
              <option v-for="item in versions" :key="item.id" :value="item.id">
                {{ item.id.slice(0, 8) }} · {{ item.complete ? '搜索完成' : '未完成' }}
              </option>
            </select></label
          >
          <div class="field-grid">
            <label
              >决策方式<select v-model="mode">
                <option value="reviewed_v1">仅人工接受且符合硬约束</option>
                <option value="exploratory_v1">探索规则自动（未实验校准）</option>
              </select></label
            ><label
              >去冗余表示<select v-model="strategy">
                <option value="isotope_representatives">每个离子形式保留同位素代表</option>
                <option value="ion_group_representatives">每个已选离子组保留代表</option>
              </select></label
            ><label
              >未归组信号<select v-model="singletons">
                <option :value="true">保留为未知单例</option>
                <option :value="false">L2 仅包含已选组</option>
              </select></label
            >
          </div>
          <div class="actions">
            <button
              class="preview"
              :disabled="store.busy || !version"
              @click="previewRepresentation"
            >
              预览 L1 / L2
            </button>
            <button
              class="primary"
              :disabled="store.busy || !version"
              @click="command('represent', representationOptions)"
            >
              建立来源视图与分析分支
            </button>
          </div>
          <details v-if="representation" open>
            <summary>预览结果与代表离子</summary>
            <DataTableView
              :table="{
                columns: ['level', 'cells', 'variables', 'omitted_features'],
                rows: representation.views,
                total: representation.views.length,
              }"
            />
            <details>
              <summary>完整预览映射</summary>
              <pre>{{ JSON.stringify(representation.metadata, null, 2) }}</pre>
            </details>
          </details>
          <p class="muted">
            L2
            仅使用固定代表离子，不加总不同离子。能归组但不能定量的实体保留原因；未知信号无需先鉴定即可参与分析。
          </p>
          <details>
            <summary>源 L2 可量化子集与导出</summary>
            <label
              >来源视图<select v-model="availabilityView">
                <option value="">请选择</option>
                <option
                  v-for="view in info.views.filter((row) => row.level === 'L2')"
                  :key="view.id"
                  :value="view.id"
                >
                  {{ label(view) }}
                </option>
              </select></label
            >
            <label
              >固定轴<select v-model="availabilityAxis">
                <option value="cells">固定细胞，选择共同可量化变量</option>
                <option value="variables">固定变量，选择共同可量化细胞</option>
              </select></label
            >
            <label>变量编号（留空使用全部变量）<textarea v-model="availabilityIds" /></label>
            <div class="actions">
              <button
                class="preview"
                :disabled="store.busy || !availabilityView"
                @click="previewAvailability"
              >
                预览可量化子集</button
              ><button
                class="primary"
                :disabled="store.busy || !availability"
                @click="
                  command('materialize', { view_id: availabilityView, preview: availability })
                "
              >
                物化新分析分支</button
              ><button
                class="download"
                :disabled="store.busy || !availabilityView"
                @click="download('source_l2', availabilityView)"
              >
                下载完整源 L2
              </button>
            </div>
            <pre v-if="availability">{{ JSON.stringify(availability, null, 2) }}</pre>
          </details>
        </div>
        <div class="card">
          <details>
            <summary>EC 来源显式合并</summary>
            <label
              >来源视图（多选）<select v-model="mergeViews" multiple>
                <option
                  v-for="view in info.views.filter((row) => row.level === 'L2')"
                  :key="view.id"
                  :value="view.id"
                >
                  {{ label(view) }}
                </option>
              </select></label
            ><label title="source_id/ec_id/target_ec_id/response_comparable/reason"
              >对应与定量可比性映射 JSON<textarea v-model="mergeAlignments" rows="4" />
            </label>
            <p class="muted">
              未映射 EC
              保持独立，跨来源不可量化记为缺测。同质量或同名称不自动对齐；不同定量离子需校准模型，当前拒绝合并。
            </p>
            <button
              class="primary"
              :disabled="store.busy || mergeViews.length < 2"
              @click="safely(mergeCompounds)"
            >
              建立合并来源 L2
            </button>
          </details>
          <h2>分析敏感性与重复汇总</h2>
          <label>参与比较的分析分支（编号，逗号分隔）<textarea v-model="comparison" /></label
          ><label
            >归一化基准<select v-model="comparisonMode">
              <option value="independent">各视图独立</option>
              <option value="shared">已应用同一分母</option>
            </select></label
          >
          <label v-if="comparisonMode === 'shared'"
            >逐细胞归一化分母 JSON<textarea v-model="sharedFactors" /><button
              class="primary"
              :disabled="store.busy"
              @click="
                safely(() =>
                  command('shared-normalization', { factors: JSON.parse(sharedFactors) }),
                )
              "
            >
              将分母应用到当前分支
            </button></label
          >
          <button class="preview" :disabled="store.busy" @click="safely(compare)">
            比较已有结果
          </button>
          <pre v-if="compareResult">{{ JSON.stringify(compareResult, null, 2) }}</pre>
          <div class="field-grid">
            <label>生物重复字段<input v-model="replicateKey" /></label
            ><label>分组字段（可选）<input v-model="replicateGroup" /></label>
          </div>
          <button class="download" :disabled="store.busy" @click="safely(replicates)">
            下载重复汇总 CSV
          </button>
          <p class="muted">
            现有差异检验以细胞为单位，细胞数不等于独立生物重复数。汇总导出不执行重复水平统计推断。
          </p>
        </div>
      </template>
      <div class="card">
        <h2>完整项目与来源导入</h2>
        <div class="actions">
          <button
            class="download"
            :disabled="store.busy || !info?.initialized"
            @click="download('bundle')"
          >
            下载完整离子项目包
          </button>
        </div>
        <p class="muted">
          完整包包含来源、分支、映射及托管证据，不含可执行模型或原始谱。完整包导入需空项目；源 L2
          可单独导入，不伪造测量根。
        </p>
        <label
          >导入类型<select v-model="importKind">
            <option value="source_l2">源 L2 H5AD</option>
            <option value="bundle">完整离子项目 ZIP</option></select
          ><input type="file" accept=".h5ad,.zip" :disabled="store.busy" @change="importFile"
        /></label>
      </div>
    </template>
  </section>
</template>
<style scoped>
textarea {
  width: 100%;
  max-width: 100%;
  font-family: monospace;
}
pre {
  max-height: 24rem;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.card {
  margin-bottom: 1rem;
}
label {
  overflow-wrap: anywhere;
}
</style>
