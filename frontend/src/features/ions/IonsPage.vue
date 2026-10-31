<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { ionPath, type IonInfo, type IonTable, type IonView } from '../../api/ions'
import { saveBlob, workspaceBlob } from '../../api/workspaceDownload'
import { serialPolling } from '../../api/polling'
import DataTableView from '../../components/DataTable.vue'
import DataViewSelector from './DataViewSelector.vue'
const store = useWorkspace()
const info = ref<IonInfo>()
const root = ref(''),
  version = ref(''),
  annotation = ref(''),
  tableKind = ref('relations')
const table = ref<IonTable>(),
  offset = ref(0)
const polarity = ref('pos'),
  ppm = ref(5),
  linearity = ref('unknown')
const species = ref(['[M+H]+', '[M+Na]+', '[M+K]+', '[M+NH4]+', '[M+H-H2O]+'])
const resolution = ref<number>(),
  formulaHypotheses = ref('[]')
const mode = ref('reviewed_v1'),
  strategy = ref('isotope_representatives'),
  singletons = ref(true)
const groupId = ref(''),
  hypothesisId = ref(''),
  relationIds = ref(''),
  quantifier = ref(''),
  reason = ref('')
const databaseFormat = ref('json'),
  fieldMapping = ref('{}')
const database = ref(''),
  namespace = ref('local'),
  evidence = ref('[]'),
  evidenceFormat = ref('json'),
  sourceName = ref('manual evidence')
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
const evidenceLinks = ref('{}'),
  linkResult = ref<unknown>(),
  assertion = ref('{}'),
  mergeViews = ref<string[]>([]),
  mergeAlignments = ref('[]'),
  overlayTarget = ref('')
let generation = 0
const availableSpecies = computed(
  () => info.value?.species.filter((row) => row.polarity === polarity.value) ?? [],
)
watch(polarity, (value) => {
  species.value =
    value === 'pos'
      ? ['[M+H]+', '[M+Na]+', '[M+K]+', '[M+NH4]+', '[M+H-H2O]+']
      : ['[M-H]-', '[M-2H]2-', '[2M-H]-']
})
function ids(text: string) {
  return text.split(/[\s,;]+/).filter(Boolean)
}
async function refresh() {
  const token = ++generation
  const result = await store.read<IonInfo>(ionPath('info'), undefined, () => token === generation)
  if (!result) return
  info.value = result
  if (!result.roots?.some((row) => row.id === root.value)) root.value = result.roots?.[0]?.id ?? ''
  if (!result.versions?.some((row) => row.id === version.value))
    version.value = result.versions?.at(-1)?.id ?? ''
  if (!result.annotation_versions?.includes(annotation.value))
    annotation.value = result.annotation_versions?.at(-1) ?? ''
}
watch(
  () => [store.current?.workspace_id, store.current?.revision],
  () => void refresh(),
  { immediate: true },
)
watch(
  () => [version.value, annotation.value, tableKind.value, offset.value],
  () => void loadTable(),
)
watch(
  () => [version.value, tableKind.value],
  () => {
    offset.value = 0
    groupId.value = ''
    hypothesisId.value = ''
    relationIds.value = ''
  },
)
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
  const query = new URLSearchParams({
    version: key,
    kind: tableKind.value,
    offset: String(offset.value),
    limit: '100',
  })
  const signature = query.toString()
  const result = await store.read<IonTable>(
    `${ionPath('table')}?${query}`,
    undefined,
    () =>
      signature ===
      new URLSearchParams({
        version: ['candidates', 'unknown'].includes(tableKind.value)
          ? annotation.value
          : version.value,
        kind: tableKind.value,
        offset: String(offset.value),
        limit: '100',
      }).toString(),
  )
  if (result) table.value = result
}
async function command(action: string, body: Record<string, unknown> = {}) {
  const result = await store.command(ionPath(action), body)
  await refresh()
  await loadTable()
  return result
}
async function safely(action: () => Promise<unknown>) {
  try {
    await action()
  } catch (cause) {
    store.error = cause instanceof Error ? cause.message : String(cause)
  }
}
async function run() {
  await command('run', {
    root_id: root.value,
    request_id: crypto.randomUUID(),
    options: {
      polarity: polarity.value,
      ppm: ppm.value,
      species: species.value,
      resolution_200: resolution.value ?? null,
      formula_hypotheses: JSON.parse(formulaHypotheses.value),
    },
  })
}
async function acceptGroup(decision: string) {
  await command('review', {
    version: version.value,
    kind: 'group',
    target_id: groupId.value,
    hypothesis_id: hypothesisId.value || null,
    relation_ids: ids(relationIds.value),
    quantifier_feature_id: quantifier.value || null,
    decision,
    reason: reason.value,
    scope: { root_id: root.value },
  })
}
function chooseGroup(row: Record<string, unknown>) {
  groupId.value = String(row.ec_id)
  // Selecting a group never accepts an interpretation. The operator selects the exact role ID below.
  hypothesisId.value = ''
}
const selectedGroup = computed(() =>
  tableKind.value === 'groups'
    ? table.value?.table.rows.find((row) => row.ec_id === groupId.value)
    : undefined,
)
const hypotheses = computed<
  { hypothesis_id: string; members: Record<string, unknown>; neutral_mass: number | null }[]
>(() => {
  const value = selectedGroup.value?.hypotheses
  return typeof value === 'string' ? JSON.parse(value) : []
})
async function annotate() {
  const records = databaseFormat.value === 'json' ? JSON.parse(database.value) : []
  await command('annotate', {
    root_id: root.value,
    version: version.value || null,
    polarity: polarity.value,
    ppm: ppm.value,
    species: species.value,
    namespace: namespace.value,
    records,
    content: databaseFormat.value === 'json' ? '' : database.value,
    format: databaseFormat.value,
    field_mapping: JSON.parse(fieldMapping.value),
  })
  tableKind.value = 'candidates'
}
async function importEvidence() {
  await command('evidence', {
    source_name: sourceName.value,
    format: evidenceFormat.value,
    records: evidenceFormat.value === 'json' ? JSON.parse(evidence.value) : [],
    content: evidenceFormat.value === 'json' ? '' : evidence.value,
  })
  tableKind.value = 'evidence'
}
async function linkEvidence() {
  linkResult.value = await store.command(
    ionPath('evidence/preview'),
    JSON.parse(evidenceLinks.value),
  )
}
async function saveAssertion() {
  await command('assertion', JSON.parse(assertion.value))
}
async function mergeCompounds() {
  await command('merge-compounds', {
    view_ids: mergeViews.value,
    alignments: JSON.parse(mergeAlignments.value),
  })
}
async function reviewOverlay(decision: string) {
  await command('review', {
    version: tableKind.value === 'candidates' ? annotation.value : version.value,
    kind: tableKind.value === 'candidates' ? 'candidate' : 'evidence',
    target_id: overlayTarget.value,
    decision,
    reason: reason.value,
    scope: { root_id: root.value },
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
async function download(kind: string, key = '') {
  const snapshot = store.current
  if (!snapshot) return
  await store.run(
    async (scope) => {
      const query = new URLSearchParams({ kind, key, revision: String(snapshot.revision) })
      const blob = await workspaceBlob(`${ionPath('download')}?${query}`, {
        workspace: snapshot.workspace_id,
        isCurrent: () =>
          scope.isCurrent() &&
          store.current?.workspace_id === snapshot.workspace_id &&
          store.current?.revision === snapshot.revision,
      })
      saveBlob(
        blob,
        kind === 'bundle'
          ? 'ion-project.zip'
          : kind === 'source_l2'
            ? 'compound-source.h5ad'
            : 'ion-evidence.json',
      )
    },
    '',
    { label: '下载离子数据', phase: 'downloading' },
  )
}
async function fileText(event: Event, target: 'database' | 'evidence') {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const text = await file.text()
  if (target === 'database') {
    database.value = text
    databaseFormat.value = file.name.toLowerCase().split('.').at(-1) ?? 'json'
  } else {
    evidence.value = text
    sourceName.value = file.name
    evidenceFormat.value = file.name.toLowerCase().endsWith('.mgf')
      ? 'mgf'
      : file.name.toLowerCase().endsWith('.msp')
        ? 'msp'
        : 'json'
  }
}
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
const polling = serialPolling(
  async () => {
    if (!store.busy && info.value?.tasks.some((row) => ['queued', 'running'].includes(row.status)))
      await refresh()
  },
  1500,
  () => {},
)
polling.start(false)
onUnmounted(() => {
  generation++
  polling.stop()
})
function label(view: IonView) {
  return `${view.level} · ${view.cell_ids.length} × ${(view.variable_ids ?? view.feature_ids).length} · ${view.id.slice(0, 8)}`
}
</script>
<template>
  <section>
    <h1>离子归组与化合物注释</h1>
    <p class="muted">
      先判断离子关系，再选择定量表示和化学身份。归组不等于鉴定；候选排序不代表鉴定概率。
    </p>
    <p>
      <RouterLink to="/preprocess">进入统计预处理</RouterLink> ·
      <RouterLink to="/analysis">进入分析</RouterLink>
    </p>
    <div v-if="!store.project" class="card">请先创建或打开项目。</div>
    <template v-else>
      <DataViewSelector />
      <div v-if="!info?.initialized" class="card">
        <h2>建立不可变测量来源</h2>
        <p>采用完整预处理起点，保留当前分析及用户图。导入矩阵的线性丰度必须由使用者明确声明。</p>
        <label
          >起点数值空间<select v-model="linearity">
            <option value="unknown">未知</option>
            <option value="linear_abundance">未变换线性丰度</option>
          </select></label
        >
        <button
          class="primary"
          :disabled="store.busy || !store.project.dataset"
          @click="command('initialize', { linearity, origin_kind: 'imported_feature' })"
        >
          启用离子数据目录
        </button>
      </div>
      <template v-if="info?.initialized">
        <div class="card">
          <h2>1. 候选关系与竞争解释</h2>
          <div class="field-grid">
            <label
              >测量来源<select v-model="root">
                <option v-for="row in info.roots" :key="row.id" :value="row.id">
                  {{ row.id }}
                </option>
              </select></label
            >
            <label title="polarity：按采集极性分别归组"
              >采集极性<select v-model="polarity">
                <option value="pos">正离子</option>
                <option value="neg">负离子</option>
              </select></label
            >
            <label title="ppm：相对预测 m/z 的容差"
              >质量容差 (ppm)<input
                v-model.number="ppm"
                type="number"
                min="0.1"
                max="100"
                step="0.5"
            /></label>
            <label title="species：多选明确的离子形式"
              >离子形式<select v-model="species" aria-label="离子形式" multiple size="5">
                <option v-for="row in availableSpecies" :key="row.id">{{ row.id }}</option>
              </select></label
            >
          </div>
          <details>
            <summary>分子式条件同位素证据</summary>
            <label title="resolution_200：实际采集配置，不能从仪器型号推定"
              >m/z 200 处分辨率<input v-model.number="resolution" type="number"
            /></label>
            <label title="formula_hypotheses：feature_id/formula/species_id"
              >已有分子式假设 JSON<textarea v-model="formulaHypotheses" rows="3" />
            </label>
          </details>
          <button class="primary" :disabled="store.busy || !root" @click="safely(run)">
            后台生成候选与解释
          </button>
          <p class="muted">
            化学质量约束优先；跨细胞相关仅作辅助。搜索触限保留未完成状态，不能用于去冗余。
          </p>
          <div v-for="task in info.tasks" :key="task.id" class="actions">
            <span>{{ task.id.slice(0, 8) }} · {{ task.status }} {{ task.reason }}</span>
            <button
              v-if="['queued', 'running'].includes(task.status)"
              class="danger"
              :disabled="store.busy"
              @click="command('cancel', { job_id: task.id })"
            >
              取消任务
            </button>
            <button
              v-if="task.collectible && !task.collected"
              class="primary"
              :disabled="store.busy"
              @click="command('collect', { job_id: task.id })"
            >
              收集结果
            </button>
          </div>
        </div>
        <div class="card">
          <h2>2. 审阅关系及离子角色</h2>
          <div class="field-grid">
            <label
              >归组版本<select v-model="version">
                <option v-for="row in info.versions" :key="row.id" :value="row.id">
                  {{ row.id.slice(0, 8) }} · {{ row.relations }} 关系 / {{ row.groups }} 组 ·
                  {{ row.complete ? '搜索完成' : '未完成' }}
                </option>
              </select></label
            >
            <label
              >查看内容<select v-model="tableKind">
                <option value="relations">离子关系</option>
                <option value="groups">候选 EC 与角色解释</option>
                <option value="diagnostics">搜索诊断</option>
                <option value="candidates">化合物候选</option>
                <option value="unknown">未知目标</option>
                <option value="evidence">外部证据</option>
                <option value="reviews">审阅记录</option>
                <option value="representations">定量映射与审计</option>
              </select></label
            >
          </div>
          <div class="actions">
            <button class="preview" :disabled="store.busy" @click="loadTable">刷新表格</button
            ><button
              class="download"
              :disabled="store.busy || !version"
              @click="download('version', version)"
            >
              下载完整归组 JSON</button
            ><button class="download" :disabled="store.busy" @click="download('registry')">
              下载全部候选与证据
            </button>
          </div>
          <p v-if="table">
            共 {{ table.total }} 行；显示 {{ offset + 1 }}–{{
              Math.min(offset + 100, table.total)
            }}。下载不受分页限制。
          </p>
          <DataTableView v-if="table" :table="table.table" />
          <details v-if="tableKind === 'relations'">
            <summary>选择支持关系</summary>
            <div class="actions">
              <button
                v-for="row in table?.table.rows"
                :key="String(row.relation_id)"
                :disabled="['neutral_loss', 'fragment_form'].includes(String(row.kind))"
                @click="
                  relationIds = [...new Set([...ids(relationIds), String(row.relation_id)])].join(
                    ',',
                  )
                "
              >
                {{ row.left_feature_id }} → {{ row.right_feature_id }} · {{ row.kind }} · z={{
                  row.charge_magnitude ?? '?'
                }}
                · {{ row.left_species }} / {{ row.right_species }} ·
                {{ String(row.relation_id).slice(0, 8) }}
              </button>
            </div>
          </details>
          <details v-if="['candidates', 'evidence'].includes(tableKind)">
            <summary>人工审阅当前候选 / 证据</summary>
            <label
              >目标<select v-model="overlayTarget">
                <option
                  v-for="row in table?.table.rows"
                  :key="String(row.candidate_id ?? row.evidence_id)"
                  :value="String(row.candidate_id ?? row.evidence_id)"
                >
                  {{ row.name ?? row.kind }} ·
                  {{ String(row.candidate_id ?? row.evidence_id).slice(0, 8) }}
                </option>
              </select></label
            ><label>审阅理由<input v-model="reason" aria-label="审阅理由" /></label>
            <div class="actions">
              <button
                class="primary"
                :disabled="store.busy || !overlayTarget || !reason"
                @click="reviewOverlay('accepted')"
              >
                接受为审阅声明</button
              ><button
                class="danger"
                :disabled="store.busy || !overlayTarget || !reason"
                @click="reviewOverlay('rejected')"
              >
                拒绝候选 / 证据
              </button>
            </div>
            <p class="muted">人工接受不自动授予鉴定等级。鉴定标准和结构层级另行声明。</p>
          </details>

          <div class="actions">
            <button :disabled="offset === 0" @click="offset = Math.max(0, offset - 100)">
              上一页</button
            ><button :disabled="!table || offset + 100 >= table.total" @click="offset += 100">
              下一页
            </button>
          </div>
          <details v-if="tableKind === 'groups'">
            <summary>选择候选组</summary>
            <div class="actions">
              <button
                v-for="row in table?.table.rows"
                :key="String(row.ec_id)"
                @click="chooseGroup(row)"
              >
                {{ String(row.feature_ids) }} · {{ String(row.ec_id).slice(0, 8) }}
              </button>
            </div>
          </details>
          <div class="field-grid">
            <label>EC ID<input v-model="groupId" aria-label="EC ID" /></label>
            <label title="hypothesis_id：必须明确选择，不默认接受首个解释"
              >离子角色解释<select
                v-if="hypotheses.length"
                v-model="hypothesisId"
                aria-label="离子角色解释"
              >
                <option value="">请选择解释</option>
                <option
                  v-for="row in hypotheses"
                  :key="row.hypothesis_id"
                  :value="row.hypothesis_id"
                >
                  {{ row.hypothesis_id.slice(0, 8) }} · {{ JSON.stringify(row.members) }} ·
                  {{ row.neutral_mass }}
                </option></select
              ><input v-else v-model="hypothesisId" aria-label="离子角色解释"
            /></label>
            <label title="relation_ids：接受的关系必须符合选择的角色并连接全部成员"
              >支持关系 ID（逗号分隔）<textarea
                v-model="relationIds"
                aria-label="支持关系 ID（逗号分隔）"
                rows="2"
              />
            </label>
            <label title="quantifier_feature_id：留空按稳定检测规则选固定单体离子"
              >固定定量离子 ID（可选）<input v-model="quantifier"
            /></label>
            <label>审阅理由<input v-model="reason" aria-label="审阅理由" /></label>
          </div>
          <div class="actions">
            <button
              class="primary"
              :disabled="store.busy || !groupId || !hypothesisId || !reason"
              @click="acceptGroup('accepted')"
            >
              接受所列关系与此组解释</button
            ><button
              class="danger"
              :disabled="store.busy || !groupId || !reason"
              @click="acceptGroup('rejected')"
            >
              拒绝此组
            </button>
          </div>
        </div>
        <div class="card">
          <h2>3. 构建 L1 / L2</h2>
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
          <button
            class="primary"
            :disabled="store.busy || !version"
            @click="
              command('represent', { version, mode, strategy, include_singletons: singletons })
            "
          >
            建立来源视图与分析分支
          </button>
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
            <label>轴 ID（留空使用整轴）<textarea v-model="availabilityIds" /></label>
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
          <h2>4. 化合物候选与外部证据</h2>
          <p class="muted">
            准确质量检索保留全部候选；证据按目标版本和作用域保存。群体 MS/MS
            不自动提升单细胞身份，也不运行谱库搜索。
          </p>
          <label>数据库命名空间<input v-model="namespace" /></label
          ><label
            >化合物库文件（JSON / CSV / TSV / SDF）<input
              type="file"
              accept=".json,.csv,.tsv,.sdf"
              @change="fileText($event, 'database')"
          /></label>
          <label title="record_id/name/formula/exact_mass：formula 与 exact_mass 至少提供一个"
            >候选库内容<textarea
              v-model="database"
              aria-label="候选库内容"
              rows="4"
              placeholder='[{"record_id":"id1","name":"compound","formula":"C6H12O6"}]'
            />
          </label>
          <label>字段映射 JSON（标准字段到文件列名）<input v-model="fieldMapping" /></label
          ><button
            class="primary"
            :disabled="store.busy || !root || !database"
            @click="safely(annotate)"
          >
            搜索质量与已有公式候选
          </button>
          <label
            >注释版本<select v-model="annotation">
              <option v-for="key in info.annotation_versions" :key="key">{{ key }}</option>
            </select></label
          >
          <button
            class="download"
            :disabled="store.busy || !annotation"
            @click="download('annotation', annotation)"
          >
            下载完整候选
          </button>
          <details>
            <summary>导入标准品、空白、经验及群体 MS/MS 证据</summary>
            <label
              >证据文件<input
                type="file"
                accept=".json,.mgf,.msp"
                @change="fileText($event, 'evidence')" /></label
            ><label>来源名称<input v-model="sourceName" /></label
            ><label
              >格式<select v-model="evidenceFormat">
                <option value="json">JSON</option>
                <option value="mgf">MGF</option>
                <option value="msp">MSP</option>
              </select></label
            >
            <label>证据记录 / 谱表<textarea v-model="evidence" rows="5" /></label
            ><button class="primary" :disabled="store.busy" @click="safely(importEvidence)">
              导入证据
            </button>
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
            <p class="muted">
              按实际证据分别填写 MSI、Schymanski、LSI
              或自定义标准、版本、等级、criteria、evidence_ids、scope、structure_level 及
              target。保存为未自动验证的人工声明。
            </p>
            <label>鉴定声明 JSON<textarea v-model="assertion" rows="5" /></label
            ><button class="primary" :disabled="store.busy" @click="safely(saveAssertion)">
              保存鉴定声明
            </button>
          </details>
          <h2>5. 分析敏感性与重复汇总</h2>
          <label>比较分支 ID（逗号分隔）<textarea v-model="comparison" /></label
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
