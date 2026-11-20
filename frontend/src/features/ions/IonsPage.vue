<script setup lang="ts">
import { computed, onActivated, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { ionPath, type IonInfo, type IonTable, type IonView } from '../../api/ions'
import { saveBlob, workspaceBlob } from '../../api/workspaceDownload'
import { serialPolling } from '../../api/polling'
import DataTableView from '../../components/DataTable.vue'
import DataViewSelector from './DataViewSelector.vue'
import AnnotationHeader from '../annotation/AnnotationHeader.vue'
import CompoundSourcePanel from './CompoundSourcePanel.vue'
import { useAnnotationSource } from '../annotation/useAnnotationSource'
const props = withDefaults(
  defineProps<{
    surface?: 'quantitative' | 'review' | 'search' | 'evidence'
    focusFeature?: string
  }>(),
  { surface: 'quantitative', focusFeature: '' },
)
const { sourceId, source, grouping, selectTarget } = useAnnotationSource()
const store = useWorkspace()
const info = ref<IonInfo>()
const root = ref(''),
  version = ref(''),
  annotation = ref(''),
  tableKind = ref('relations')
const table = ref<IonTable>(),
  groupRelations = ref<IonTable>(),
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
const compoundTarget = ref('features'),
  compoundFormulas = ref('[]')
const database = ref(''),
  namespace = ref('local')
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
let tableGeneration = 0
const versions = computed(
  () => info.value?.versions?.filter((row) => row.root_id === root.value) ?? [],
)
const focusedOnly = ref(true)
const localVersions = computed(
  () =>
    info.value?.annotation_versions?.filter(
      (key) => info.value?.annotation_roots?.[key] === root.value,
    ) ?? [],
)
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
  if (!store.project) {
    info.value = undefined
    return
  }
  const token = ++generation
  const result = await store.read<IonInfo>(ionPath('info'), undefined, () => token === generation)
  if (!result) return
  info.value = result
  root.value = result.roots?.some((row) => row.id === sourceId.value) ? sourceId.value : ''
  if (!versions.value.some((row) => row.id === version.value))
    version.value =
      versions.value.find((item) => item.id === grouping.value)?.id ??
      versions.value.at(-1)?.id ??
      ''
  if (!localVersions.value.includes(annotation.value))
    annotation.value = localVersions.value.at(-1) ?? ''
}
watch(
  () => [store.project?.path, store.current?.revision, sourceId.value],
  () => void refresh(),
  { immediate: true },
)
watch(
  () => [
    version.value,
    annotation.value,
    tableKind.value,
    offset.value,
    focusedOnly.value,
    props.focusFeature,
  ],
  () => void loadTable(),
)
watch(version, (value) => {
  if (props.surface === 'review' && value) grouping.value = value
  offset.value = 0
  groupId.value = ''
  hypothesisId.value = ''
  relationIds.value = ''
  groupRelations.value = undefined
})
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
    feature_id: focusedOnly.value ? props.focusFeature : '',
  })
  const result = await store.read<IonTable>(
    `${ionPath('table')}?${query}`,
    undefined,
    () => token === tableGeneration,
  )
  if (result) table.value = result
}
async function loadGroupRelations() {
  const ec = groupId.value
  const revision = version.value
  if (!ec || !revision) return
  const query = new URLSearchParams({
    version: revision,
    kind: 'relations',
    ec_id: ec,
    limit: '200',
  })
  const result = await store.read<IonTable>(
    `${ionPath('table')}?${query}`,
    undefined,
    () => groupId.value === ec && version.value === revision,
  )
  if (result) groupRelations.value = result
}
watch(groupId, () => {
  groupRelations.value = undefined
  void loadGroupRelations()
})
async function reviewRelation(id: string, decision: string) {
  await command('review', {
    version: version.value,
    kind: 'relation',
    target_id: id,
    decision,
    reason: reason.value.trim() || '人工核对峰关系',
    scope: { root_id: root.value },
  })
  await loadGroupRelations()
}
async function previewRepresentation() {
  representation.value = await store.command(
    ionPath('represent/preview'),
    representationOptions.value,
  )
}

async function command(action: string, body: Record<string, unknown> = {}) {
  const result = await store.command(ionPath(action), body)
  if (result === undefined) return
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
  const previous =
    row.selection && typeof row.selection === 'string' ? JSON.parse(row.selection) : undefined
  hypothesisId.value = previous?.hypothesis_id ?? ''
  relationIds.value = (previous?.relation_ids ?? []).join(',')
  quantifier.value = previous?.quantifier_feature_id ?? ''
  if (source.value)
    selectTarget({
      source: root.value,
      sourceIdentity: source.value.identity,
      kind: 'ec',
      id: groupId.value,
      version: version.value,
      members: typeof row.feature_ids === 'string' ? JSON.parse(row.feature_ids) : [],
      quantifier: previous?.quantifier_feature_id,
    })
}
function toggleSupport(id: string, checked: boolean) {
  const selected = new Set(ids(relationIds.value))
  if (checked) selected.add(id)
  else selected.delete(id)
  relationIds.value = [...selected].join(',')
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
    field_mapping: JSON.parse(fieldMapping.value),
  })) as { version: string } | undefined
  if (result) {
    annotation.value = result.version
    tableKind.value = 'candidates'
    offset.value = 0
  }
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
async function fileText(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const text = await file.text()
  database.value = text
  databaseFormat.value = file.name.toLowerCase().split('.').at(-1) ?? 'json'
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
if (props.surface === 'review') polling.start(false)
onActivated(() => {
  if (props.surface === 'review') polling.start(false)
})
onDeactivated(polling.stop)
onUnmounted(() => {
  generation++
  polling.stop()
})
const taskStatuses: Record<string, string> = {
  queued: '等待执行',
  running: '计算中',
  succeeded: '计算完成',
  failed: '计算失败',
  cancelled: '已取消',
  interrupted: '已中断',
}
const taskReasons: Record<string, string> = {
  'worker submission failed': '无法启动任务，可重新生成。',
  'task wall time budget exceeded': '计算超时，可调整候选条件后重试。',
  'worker failed; inspect task log': '计算出错，可重新生成。',
  'cancelled by user': '已停止计算，可重新生成。',
  'service restarted': '服务重启，可重新生成。',
  'service maintenance': '服务维护，可重新生成。',
  'workspace/input changed; explicitly run a new task': '输入已变化，请重新生成。',
}
function label(view: IonView) {
  return `${view.level} · ${view.cell_ids.length} × ${(view.variable_ids ?? view.feature_ids).length} · ${view.id.slice(0, 8)}`
}
</script>
<template>
  <section>
    <AnnotationHeader v-if="surface === 'quantitative'" title="定量视图" :grouping="version" />
    <div v-if="!store.project" class="card">请先创建或打开项目。</div>
    <template v-else>
      <DataViewSelector v-if="surface === 'quantitative'" />
      <div v-if="!info?.initialized && surface === 'review'" class="card">
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
          :disabled="store.busy || !store.project.dataset?.quantitation_available"
          @click="command('initialize', { linearity, origin_kind: 'imported_feature' })"
        >
          启用离子数据目录
        </button>
      </div>
      <template v-if="info?.initialized">
        <div v-if="surface === 'review' && root" class="card">
          <h2>生成离子关系与竞争解释</h2>
          <div class="field-grid">
            <label
              ><FieldLabel name="采集极性" help-key="polarity" text="按采集极性分别归组" /><select
                v-model="polarity"
              >
                <option value="pos">正离子</option>
                <option value="neg">负离子</option>
              </select></label
            >
            <label
              ><FieldLabel name="质量容差 (ppm)" help-key="ppm" text="相对预测 m/z 的容差" /><input
                v-model.number="ppm"
                type="number"
                min="0.1"
                max="100"
                step="0.5"
            /></label>
            <label
              ><FieldLabel name="离子形式" help-key="species" text="可多选明确的离子形式" /><select
                v-model="species"
                aria-label="离子形式"
                multiple
                size="5"
              >
                <option v-for="row in availableSpecies" :key="row.id">{{ row.id }}</option>
              </select></label
            >
          </div>
          <details>
            <summary>分子式条件同位素证据</summary>
            <label
              ><FieldLabel
                name="m/z 200 处分辨率"
                help-key="resolution_200"
                text="填写实际采集配置，不能从仪器型号推定" /><input
                v-model.number="resolution"
                type="number"
            /></label>
            <label
              ><FieldLabel
                name="已有分子式假设 JSON"
                help-key="formula_hypotheses"
                text="字段为 feature_id、formula 和 species_id"
              /><textarea v-model="formulaHypotheses" rows="3" />
            </label>
          </details>
          <button class="primary" :disabled="store.busy || !root" @click="safely(run)">
            后台生成候选与解释
          </button>
          <p class="muted">
            化学质量约束优先；跨细胞相关仅作辅助。搜索触限保留未完成状态，不能用于去冗余。
          </p>
          <div v-for="task in info.tasks" :key="task.id" class="actions">
            <span>
              {{ task.id.slice(0, 8) }} ·
              {{ task.collected ? '已收集' : (taskStatuses[task.status] ?? '状态未知') }}
              {{ task.reason ? (taskReasons[task.reason] ?? task.reason) : '' }}
            </span>
            <button
              v-if="['queued', 'running'].includes(task.status)"
              class="restore"
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
        <details v-if="surface === 'review' && version" class="card" open>
          <summary>峰关系与离子组审核</summary>
          <div class="field-grid">
            <label
              >归组版本<select v-model="version">
                <option v-for="row in versions" :key="row.id" :value="row.id">
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
          <label
            v-if="focusFeature && ['groups', 'relations'].includes(tableKind)"
            class="inline-check"
          >
            <input v-model="focusedOnly" type="checkbox" />仅当前峰 {{ focusFeature }}
          </label>
          <div v-if="tableKind === 'relations'" class="data-table relation-grid">
            <table>
              <thead>
                <tr>
                  <th>支持</th>
                  <th>峰关系</th>
                  <th>角色 / 电荷</th>
                  <th>质量误差</th>
                  <th>状态</th>
                  <th>审核</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in table?.table.rows" :key="String(row.relation_id)">
                  <td>
                    <input
                      type="checkbox"
                      :aria-label="`支持关系 ${row.relation_id}`"
                      :checked="ids(relationIds).includes(String(row.relation_id))"
                      :disabled="['neutral_loss', 'fragment_form'].includes(String(row.kind))"
                      @change="
                        toggleSupport(
                          String(row.relation_id),
                          ($event.target as HTMLInputElement).checked,
                        )
                      "
                    />
                  </td>
                  <td>{{ row.left_feature_id }} → {{ row.right_feature_id }} · {{ row.kind }}</td>
                  <td>
                    {{ row.left_species }} / {{ row.right_species }} · {{ row.charge_magnitude }}
                  </td>
                  <td>{{ row.ppm_error ?? row.mass_error_ppm ?? '—' }}</td>
                  <td>{{ row.review }}</td>
                  <td>
                    <div class="actions">
                      <button
                        :disabled="
                          store.busy ||
                          row.review === 'accepted' ||
                          ['neutral_loss', 'fragment_form'].includes(String(row.kind))
                        "
                        @click="reviewRelation(String(row.relation_id), 'accepted')"
                      >
                        接受峰关系
                      </button>
                      <button
                        :disabled="store.busy || row.review === 'rejected'"
                        @click="reviewRelation(String(row.relation_id), 'rejected')"
                      >
                        否定
                      </button>
                      <button
                        :disabled="store.busy || row.review === 'pending'"
                        @click="reviewRelation(String(row.relation_id), 'pending')"
                      >
                        恢复待审核
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <DataTableView v-else-if="table && tableKind !== 'groups'" :table="table.table" />
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
          <div v-if="tableKind === 'groups'" class="group-list" aria-label="候选离子组">
            <div class="actions">
              <button
                v-for="row in table?.table.rows"
                :key="String(row.ec_id)"
                @click="chooseGroup(row)"
              >
                {{ String(row.feature_ids) }} · {{ String(row.ec_id).slice(0, 8) }}
              </button>
            </div>
          </div>
          <div v-if="tableKind === 'groups' || groupId" class="field-grid">
            <label>候选离子组编号（EC）<input v-model="groupId" aria-label="EC ID" /></label>
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
            <label title="quantifier_feature_id：留空按稳定检测规则选固定单体离子"
              >固定定量离子 ID（可选）<input v-model="quantifier"
            /></label>
            <label>审阅理由<input v-model="reason" aria-label="审阅理由" /></label>
          </div>
          <div v-if="groupId && groupRelations?.table.rows.length" class="group-relations">
            <label
              v-for="row in groupRelations.table.rows"
              :key="String(row.relation_id)"
              class="inline-check"
            >
              <input
                type="checkbox"
                :checked="ids(relationIds).includes(String(row.relation_id))"
                :disabled="['neutral_loss', 'fragment_form'].includes(String(row.kind))"
                :aria-label="`组内支持关系 ${row.relation_id}`"
                @change="
                  toggleSupport(
                    String(row.relation_id),
                    ($event.target as HTMLInputElement).checked,
                  )
                "
              />
              {{ row.left_feature_id }} → {{ row.right_feature_id }} · {{ row.kind }} ·
              {{ row.left_species }} / {{ row.right_species }} · z={{ row.charge_magnitude }}
            </label>
          </div>
          <div v-if="selectedGroup && hypothesisId" class="data-table">
            <DataTableView
              :table="{
                columns: ['feature_id', 'species_id', 'isotope_shift', 'charge'],
                rows: Object.entries(
                  hypotheses.find((item) => item.hypothesis_id === hypothesisId)?.members ?? {},
                ).map(([id, value]) => ({ feature_id: id, ...(value as Record<string, unknown>) })),
                total: Object.keys(
                  hypotheses.find((item) => item.hypothesis_id === hypothesisId)?.members ?? {},
                ).length,
              }"
            />
            <RouterLink to="/annotation/evidence">查看或关联此组的证据 →</RouterLink>
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
        </details>
        <CompoundSourcePanel v-if="surface === 'quantitative'" :views="info.views" />
        <div v-if="surface === 'quantitative'" class="card">
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
        <div v-if="surface === 'search'" class="card">
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
          <label>字段映射 JSON（标准字段到文件列名）<input v-model="fieldMapping" /></label
          ><button
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
        <div v-if="surface === 'evidence'" class="card">
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
        </div>
        <div v-if="surface === 'quantitative'" class="card">
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
      <div v-if="surface === 'quantitative'" class="card">
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
.relation-grid,
.group-list,
.group-relations {
  max-height: 260px;
  overflow: auto;
}
.group-list .actions {
  flex-wrap: wrap;
}
.group-relations {
  display: grid;
  gap: 4px;
  margin-bottom: 8px;
}
</style>
