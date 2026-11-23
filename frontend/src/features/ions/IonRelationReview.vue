<script setup lang="ts">
import { computed, onActivated, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { ionPath, type IonTable } from '../../api/ions'
import { serialPolling } from '../../api/polling'
import DataTableView from '../../components/DataTable.vue'
import { useIonSource, ids, useIonPolarity } from './useIonSource'
const props = withDefaults(defineProps<{ focusFeature?: string }>(), { focusFeature: '' })
const {
  store,
  info,
  root,
  source,
  version,
  versions,
  grouping,
  selectTarget,
  refresh,
  command: submit,
  safely,
  download,
} = useIonSource()
const { polarity, ppm, species } = useIonPolarity()
const linearity = ref('unknown')
const tableKind = ref('relations')
const annotation = ref('')
const overlayTarget = ref('')
const localVersions = computed(
  () =>
    info.value?.annotation_versions?.filter(
      (key) => info.value?.annotation_roots?.[key] === root.value,
    ) ?? [],
)
watch(
  localVersions,
  (values) => {
    if (!values.includes(annotation.value)) annotation.value = values.at(-1) ?? ''
  },
  { immediate: true },
)
const table = ref<IonTable>()
const groupRelations = ref<IonTable>()
const offset = ref(0)
let tableGeneration = 0
async function command(action: string, body: Record<string, unknown> = {}) {
  const result = await submit(action, body)
  if (result !== undefined) await loadTable()
  return result
}
const resolution = ref<number>(),
  formulaHypotheses = ref('[]')
const groupId = ref(''),
  hypothesisId = ref(''),
  relationIds = ref(''),
  quantifier = ref(''),
  reason = ref('')
const focusedOnly = ref(true)
const availableSpecies = computed(
  () => info.value?.species.filter((row) => row.polarity === polarity.value) ?? [],
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
  if (value) grouping.value = value
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
const polling = serialPolling(
  async () => {
    if (!store.busy && info.value?.tasks.some((row) => ['queued', 'running'].includes(row.status)))
      await refresh()
  },
  1500,
  () => {},
)
polling.start(false)
onActivated(() => {
  polling.start(false)
})
onDeactivated(polling.stop)
onUnmounted(() => {
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
</script>
<template>
  <section>
    <div v-if="!store.project" class="card">请先创建或打开项目。</div>
    <template v-else>
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
          :disabled="store.busy || !store.project.dataset?.quantitation_available"
          @click="command('initialize', { linearity, origin_kind: 'imported_feature' })"
        >
          启用离子数据目录
        </button>
      </div>
      <template v-if="info?.initialized">
        <div v-if="root" class="card">
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
        <details v-if="version" class="card" open>
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
          <label v-if="tableKind === 'candidates'"
            >注释版本
            <select v-model="annotation">
              <option v-for="key in localVersions" :key="key">{{ key }}</option>
            </select>
          </label>
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
      </template>
    </template>
  </section>
</template>
<style scoped>
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
