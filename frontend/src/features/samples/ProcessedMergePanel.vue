<script setup lang="ts">
import { computed, ref, watch, onActivated, onDeactivated } from 'vue'
import FileBrowser from '../../components/FileBrowser.vue'
import DataTable from '../../components/DataTable.vue'
import { useWorkspace } from '../../stores/workspace'
import { useViewState } from '../../api/viewState'
import { request } from '../../api/client'
import type { DataTable as Table } from '../../api/types'

type Mapping = {
  source_sample: string | null
  cells: number
  baseline_cells: number
  name: string
  group: string
  subject: string
  batch: string
}
type Info = {
  cells: number
  features: number
  baseline_cells: number
  baseline_features: number
  baseline_scope: string
  label: string
  observations: string[]
  feature_columns: string[]
  layers: string[]
  samples: { source_sample: string | null; cells: number; baseline_cells: number }[]
}
type Source = {
  kind: 'file' | 'current'
  root: string
  path: string
  mass_key: string | null
  sample_key: string | null
  info?: Info
  rows: Mapping[]
}
type Preview = {
  token: string | null
  can_apply: boolean
  conflicts: number
  summaries: Record<
    string,
    {
      cells: number
      features: number
      matched: number
      excluded: number
      added: number
      ambiguous: number
    }
  >
  tables: Record<string, Table>
}
const store = useWorkspace()
const sources = ref<Source[]>([])
const root = ref('')
const path = ref('')
const reference = ref(-1)
const mode = ref('')
const ppm = ref(5)
const ambiguity = ref('reject')
const common = ref('')
const preview = ref<Preview>()
const choosing = ref(false)
const audit = ref<{
  available: boolean
  key?: string
  shape?: number[]
  mode?: string
  role?: string
}>()
const auditError = ref('')
const active = ref(true)
onDeactivated(() => {
  active.value = false
  auditGeneration++
})
onActivated(() => {
  if (!active.value) {
    active.value = true
    void loadAudit()
  }
})
let auditGeneration = 0
async function loadAudit() {
  const generation = ++auditGeneration
  const owner = context()
  if (!store.current || store.busy || !active.value) return
  try {
    const value = await request<NonNullable<typeof audit.value>>('/workspace/dataset/merge/info', {
      workspace: store.current.workspace_id,
    })
    if (generation === auditGeneration && owner === context()) {
      audit.value = value
      auditError.value = ''
    }
  } catch (cause) {
    if (generation === auditGeneration && owner === context()) {
      audit.value = undefined
      auditError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }
}

const context = () =>
  JSON.stringify([
    store.current?.workspace_id,
    store.project?.manifest.id,
    store.project?.dataset?.id,
  ])
watch(
  () => [context(), store.busy],
  () => void loadAudit(),
  { immediate: true },
)
watch(context, () => {
  audit.value = undefined
  auditError.value = ''
  sources.value = []
  preview.value = undefined
  reference.value = -1
  choosing.value = false
})
watch(
  () => store.current?.revision,
  () => {
    preview.value = undefined
    audit.value = undefined
  },
)
watch(
  [sources, reference, mode, ppm, ambiguity, common],
  () => {
    preview.value = undefined
  },
  { deep: true },
)
function spec(source: Source) {
  return {
    kind: source.kind,
    root: source.root,
    path: source.path,
    mass_key: source.mass_key === '' ? null : source.mass_key,
    sample_key: source.sample_key,
  }
}
async function inspect(source: Source) {
  source.info = undefined
  source.rows = []
  await store.analysisTransaction(async (api) => {
    const value = await api.command<Info>('/dataset/merge/inspect', { source: spec(source) })
    if (value && api.isCurrent?.() !== false && sources.value.includes(source)) {
      source.info = value
      source.rows = value.samples.map((row) => ({
        ...row,
        name: '',
        group: '',
        subject: '',
        batch: '',
      }))
    }
  })
}
async function add(kind: 'current' | 'file') {
  const source: Source = {
    kind,
    root: kind === 'file' ? root.value : '',
    path: kind === 'file' ? path.value : '',
    mass_key: '',
    sample_key: null,
    rows: [],
  }
  sources.value.push(source)
  reference.value = -1
  choosing.value = false
  await inspect(sources.value[sources.value.length - 1]!)
}
function removeSource(index: number) {
  sources.value.splice(index, 1)
  reference.value = -1
}
function independentNames(source: Source) {
  const i = sources.value.indexOf(source)
  const short = (value: string, n: number) => Array.from(value).slice(0, n).join('')
  source.rows.forEach((row, j) => {
    row.name = `输入${i + 1}-${j + 1}/${short(source.info?.label ?? '结果', 60)}/${short(row.source_sample ?? '整份或缺失', 80)}`
  })
}

const valid = computed(
  () =>
    sources.value.length >= 2 &&
    sources.value.every(
      (s) => s.info && s.mass_key !== '' && s.rows.length && s.rows.every((r) => r.name.trim()),
    ) &&
    reference.value >= 0 &&
    !!mode.value,
)
function options() {
  return {
    sources: sources.value.map(spec),
    reference: reference.value,
    mode: mode.value,
    ppm_tol: ppm.value,
    ambiguity: ambiguity.value,
    common_observations: common.value
      .split(/[\n,;]+/)
      .map((v) => v.trim())
      .filter(Boolean),
    mapping: sources.value.flatMap((source, i) =>
      source.rows.map((row) => ({
        input_id: `m${i}`,
        source_sample: row.source_sample,
        name: row.name.trim(),
        group: row.group === '' ? null : row.group,
        subject: row.subject === '' ? null : row.subject,
        batch: row.batch === '' ? null : row.batch,
      })),
    ),
  }
}
async function review() {
  preview.value = undefined
  await store.analysisTransaction(async (api) => {
    const value = await api.command<Preview>('/dataset/merge/preview', options())
    if (value && api.isCurrent?.() !== false) preview.value = value
  })
}
async function apply() {
  const token = preview.value?.token
  if (!token) return
  await store.mutate(
    '/dataset/merge/apply',
    { token },
    'POST',
    '合并已应用，当前数据和完整起点已更新；请核对后主动保存。',
  )
}
useViewState('processed_merge', { sources, reference, mode, ppm, ambiguity, common })
</script>
<template>
  <details class="card">
    <summary>合并已处理矩阵</summary>
    <p>
      明确选择当前工作区或独立 H5AD/CSV
      结果，不自动选择最新文件。合并替换当前数据并重建完整起点，不是批次校正；不同来源的归一化值不保证直接可比。旧目录含
      pickle 时请离线转换为 H5AD。
    </p>
    <div class="actions">
      <button
        class="preview"
        :disabled="
          store.busy ||
          !store.project?.dataset ||
          sources.some((s) => s.kind === 'current') ||
          sources.length >= 8
        "
        @click="add('current')"
      >
        加入当前工作区进行合并
      </button>
      <button
        class="preview"
        :disabled="store.busy || sources.length >= 8"
        @click="choosing = !choosing"
      >
        选择合并结果文件
      </button>
    </div>
    <div v-if="choosing" class="picker-panel">
      <FileBrowser
        :roots="store.configuration?.results ?? []"
        kind="results"
        :disabled="store.busy"
        @selected="
          (r, p) => {
            root = r
            path = p[0] ?? ''
          }
        "
        @project="store.error = '合并请选择独立 H5AD 或 CSV 结果；完整项目在项目首页打开。'"
      />
      <label
        >合并来源存储<select v-model="root" aria-label="合并来源存储" :disabled="store.busy">
          <option value="" disabled>选择存储</option>
          <option v-for="item in store.configuration?.results" :key="item.label">
            {{ item.label }}
          </option>
        </select></label
      >
      <label
        ><FieldLabel
          name="合并来源路径"
          help-key="path"
          text="可从上方选择或填写配置根内路径；不自动选择文件。" /><input
          v-model="path"
          aria-label="合并来源路径"
          :disabled="store.busy"
      /></label>
      <button class="preview" :disabled="store.busy || !root || !path" @click="add('file')">
        添加所选合并文件
      </button>
    </div>
    <fieldset v-for="(source, i) in sources" :key="i" :disabled="store.busy">
      <legend>
        合并输入 {{ i + 1 }} ·
        {{ source.info?.label ?? (source.kind === 'current' ? '当前工作区' : source.path) }}
      </legend>
      <p v-if="source.info">
        当前 {{ source.info.cells }} × {{ source.info.features }}；起点
        {{ source.info.baseline_cells }} × {{ source.info.baseline_features }} ·
        {{ source.info.baseline_scope }}
      </p>
      <div class="actions">
        <button class="preview" @click="inspect(source)">刷新输入 {{ i + 1 }}</button
        ><button class="danger" @click="removeSource(i)">移除输入 {{ i + 1 }}</button>
      </div>
      <div v-if="source.info" class="field-grid">
        <label
          ><FieldLabel
            name="合并 m/z 来源"
            help-key="mass_key"
            text="明确选择正数质量列，或显式使用数值特征 ID；稳定 ID 不作最近质量猜测，重复质量拒绝。"
          /><select v-model="source.mass_key" :aria-label="`合并输入 ${i + 1} 的 m/z 来源`">
            <option value="" disabled>明确选择质量来源</option>
            <option :value="null">数值特征 ID 就是 m/z</option>
            <option v-for="key in source.info.feature_columns" :key="key">{{ key }}</option>
          </select></label
        >
        <label
          ><FieldLabel
            name="合并样本来源"
            help-key="sample_key"
            text="按明确选择的观察字段分别映射；整份输入模式将其作为一个样本，保留原字段。改变来源后重新填写映射。"
          /><select
            v-model="source.sample_key"
            :aria-label="`合并输入 ${i + 1} 的样本来源`"
            @change="inspect(source)"
          >
            <option :value="null">整份输入作为一个样本</option>
            <option v-for="key in source.info.observations" :key="key">{{ key }}</option>
          </select></label
        >
      </div>
      <button v-if="source.rows.length" class="preview" @click="independentNames(source)">
        生成输入 {{ i + 1 }} 的独立样本名
      </button>
      <p v-if="source.rows.length">
        目标同名会明确合为同一样本；覆盖分组/subject/batch
        留空时保留各细胞原值。来源间同名不证明是同一生物来源，请手动统一或区分真实 subject。
      </p>
      <div class="table-scroll">
        <table v-if="source.rows.length">
          <thead>
            <tr>
              <th>来源样本（当前/起点细胞）</th>
              <th>目标样本名</th>
              <th>覆盖分组</th>
              <th>覆盖 subject</th>
              <th>覆盖 batch</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, j) in source.rows" :key="j">
              <td>
                {{ row.source_sample ?? '整份或缺失' }}（{{ row.cells }}/{{ row.baseline_cells }}）
              </td>
              <td>
                <input v-model="row.name" :aria-label="`合并输入 ${i + 1} 样本 ${j + 1} 目标名`" />
              </td>
              <td>
                <input v-model="row.group" :aria-label="`合并输入 ${i + 1} 样本 ${j + 1} 分组`" />
              </td>
              <td>
                <input
                  v-model="row.subject"
                  :aria-label="`合并输入 ${i + 1} 样本 ${j + 1} subject`"
                />
              </td>
              <td>
                <input v-model="row.batch" :aria-label="`合并输入 ${i + 1} 样本 ${j + 1} batch`" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </fieldset>
    <fieldset v-if="sources.length" :disabled="store.busy">
      <legend>对齐与保留规则</legend>
      <div class="field-grid">
        <label
          ><FieldLabel
            name="合并参考集"
            help-key="reference"
            text="参考先处理，其他输入按选择顺序处理；union 新特征会成为后续匹配目标，顺序写入溯源。"
          /><select v-model="reference" aria-label="合并参考集">
            <option :value="-1" disabled>明确选择参考输入</option>
            <option v-for="(source, i) in sources" :key="i" :value="i">
              输入 {{ i + 1 }} · {{ source.info?.label ?? source.path }}
            </option>
          </select></label
        >
        <label
          ><FieldLabel
            name="合并特征范围"
            help-key="mode"
            text="union 保留新特征；ref 当前矩阵只保留参考集。完整重置起点始终按 union 保存来源完整轴，不丢未匹配特征。"
          /><select v-model="mode" aria-label="合并特征范围">
            <option value="" disabled>明确选择</option>
            <option value="union">union · 保留新特征</option>
            <option value="ref">ref · 当前仅参考特征</option>
          </select></label
        >
        <label
          ><FieldLabel
            name="合并质量容差"
            help-key="ppm_tol"
            text="以参考目标质量为分母，沿原逐步一对一最近未占用匹配；默认 5 ppm 来自 Python concat，不是实验推荐。" /><input
            v-model.number="ppm"
            type="number"
            min="0"
            max="1000000"
            step="0.1"
            aria-label="合并质量容差"
        /></label>
        <label
          ><FieldLabel
            name="合并多候选策略"
            help-key="ambiguity"
            text="默认拒绝；显式选择沿旧规则时记录所有多候选位置和实际选择，不改为全局最优匹配。"
          /><select v-model="ambiguity" aria-label="合并多候选策略">
            <option value="reject">拒绝多候选冲突</option>
            <option value="legacy">显式沿既有贪心规则</option>
          </select></label
        >
      </div>
      <label
        ><FieldLabel
          name="共同观察字段"
          help-key="common_observations"
          text="明确填写需要按原值拼接的同义字段，例如 time；不重排或统一时间单位。未选择字段按来源分别保留，缺失留空，类型或精度不兼容拒绝。"
        /><textarea v-model="common" rows="2" aria-label="合并共同观察字段" />
      </label>
      <p>
        所有原始观察/特征元数据按输入保留，层按来源命名、其他来源细胞留 NaN；raw
        分来源保留原轴，不进行 m/z
        对齐。已有嵌入、图及模型不能当作合并后结果。当前及起点都生成新状态，重置不是撤销合并；若需原项目请先主动保存。
      </p>
      <p class="muted">
        同步上限：8 个输入、每矩阵 2 万细胞/1 万特征/500 万值，当前与起点及层/raw 合计 2000
        万值，候选匹配 20 万对；大规模后台执行仍待 M2。
      </p>
      <button class="preview" :disabled="!valid" @click="review">预览已处理矩阵合并</button>
    </fieldset>
    <section v-if="preview" role="status">
      <h3>合并预览</h3>
      <p>
        多候选位置 {{ preview.conflicts }}；{{
          preview.can_apply
            ? '输入已验证，预览 5 分钟内有效'
            : '当前策略拒绝冲突，请调整后重新预览'
        }}。预览不写项目，文件/工作区变化会拒绝应用。
      </p>
      <div v-for="(summary, role) in preview.summaries" :key="role">
        <h4>
          {{ role === 'data' ? '当前输出' : '完整 union 重置起点' }} · {{ summary.cells }} ×
          {{ summary.features }}
        </h4>
        <p>
          匹配 {{ summary.matched }} / 新增 {{ summary.added }} / 排除 {{ summary.excluded }} /
          多候选 {{ summary.ambiguous }}
        </p>
        <DataTable :table="preview.tables[role]!" />
      </div>
      <button
        class="primary"
        :disabled="store.busy || !preview.can_apply || !preview.token"
        @click="apply"
      >
        合并并替换当前数据和起点
      </button>
      <button
        class="download"
        :disabled="store.busy || !preview.token"
        @click="store.download('merge_preview', 'scmm-merge-preview.zip', preview.token ?? '')"
      >
        下载完整合并预览
      </button>
      <p>仅应用到当前工作区；正式项目由顶部“保存项目”主动保存。原独立输入文件不会覆盖。</p>
    </section>
    <p v-if="auditError" role="alert">读取合并历史失败：{{ auditError }}</p>
    <section v-if="audit?.available">
      <h3>历史合并溯源</h3>
      <p>
        合并时 {{ audit.shape?.join(' × ') }} · {{ audit.mode }} /
        {{
          audit.role
        }}。记录合并时输入、匹配及样本映射，不能当作当前分析结果；后续预处理不会改写这段历史。
      </p>
      <button
        class="download"
        :disabled="store.busy"
        @click="store.download('merge_audit', 'scmm-merge-audit.zip', audit.key ?? '')"
      >
        下载历史合并溯源
      </button>
    </section>
  </details>
</template>

<style scoped>
fieldset {
  min-width: 0;
}
legend {
  max-width: 100%;
  overflow-wrap: anywhere;
}
.table-scroll {
  max-width: 100%;
  overflow: auto;
}
.table-scroll input {
  min-width: 8rem;
}
</style>
