<script setup lang="ts">
import LegendOrder from '../../components/LegendOrder.vue'
import { useLegendOrder } from '../../components/useLegendOrder'
import { computed, reactive, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { request } from '../../api/client'
import { workspaceBlob, saveBlob } from '../../api/workspaceDownload'
import { useLipidImageExport } from './composables/useLipidImageExport'
import DataTableView from '../../components/DataTable.vue'
import type { LipidCharts, LipidChartView, LipidNode, LipidResults } from './lipids'

const props = defineProps<{ results: LipidResults; filters: Record<string, unknown> }>()
const emit = defineEmits<{ select: [id: string]; updated: [] }>()
const store = useWorkspace()
const charts = ref<LipidCharts>()
const view = reactive<LipidChartView>({
  classification_level: 'MAIN_CLASS',
  graph: 'feature',
  scope: '',
  sign: 'both',
  node_limit: 100,
  search: '',
  category: '',
  focus: '',
})
const paperDpi = ref(300),
  paperWidth = ref(89),
  paperFont = ref(7)
const graphSvg = ref<SVGSVGElement>()
const pieSvg = ref<SVGSVGElement>()
const node = ref<LipidNode>()
const representative = ref('')
const evidenceOffset = ref(0)
const edgeOffset = ref(0)
const pageSize = 100
let currentVersion = ''
let generation = 0
async function load() {
  const token = ++generation
  const workspace = store.current?.workspace_id
  if (!workspace || !store.current) return
  let value: LipidCharts
  try {
    value = await request<LipidCharts>('/workspace/lipids/charts', {
      method: 'POST',
      workspace,
      body: {
        revision: store.current.revision,
        version: props.results.version,
        filters: props.filters,
        view,
      },
    })
  } catch (cause) {
    if (token === generation && workspace === store.current?.workspace_id)
      store.error = cause instanceof Error ? cause.message : String(cause)
    return
  }
  if (value && token === generation && workspace === store.current?.workspace_id) {
    charts.value = value
    evidenceOffset.value = 0
    edgeOffset.value = 0
  }
}
watch(
  () => props.results,
  async () => {
    if (currentVersion !== props.results.version) {
      currentVersion = props.results.version
      Object.assign(
        view,
        {
          classification_level: 'MAIN_CLASS',
          graph: 'feature',
          scope: '',
          sign: 'both',
          node_limit: 100,
          search: '',
          category: '',
          focus: '',
        },
        props.results.chart_view ?? {},
      )
      node.value = undefined
    }
    charts.value = undefined
    await load()
  },
  { immediate: true },
)
const filterLines = computed(() => {
  const applied = charts.value?.pie.filters ?? {}
  const display = charts.value?.options
  const text =
    'filters: ' +
    Object.entries(applied)
      .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('|') : v}`)
      .join('; ') +
    (display
      ? `; search=${display.search}; category=${display.category}; focus=${display.focus}`
      : '')
  return text.match(/.{1,100}/g) ?? ['']
})
const {
  items: pieLegend,
  move: movePieLegend,
  reset: resetPieLegend,
} = useLegendOrder(
  computed(() => 'lipids.classification-pie'),
  computed(() => (charts.value?.pie.counts ?? []).map((p) => p.classification)),
)
const orderedCounts = computed(() =>
  pieLegend.value.map((name) => charts.value!.pie.counts.find((p) => p.classification === name)!),
)
const pieBodyHeight = computed(() =>
  Math.max(310, ((charts.value?.pie.counts.length ?? 0) + 3) * 23),
)
const palette = [
  '#2563eb',
  '#0d9488',
  '#d97706',
  '#9333ea',
  '#dc2626',
  '#475569',
  '#db2777',
  '#65a30d',
]
const colors = computed(() =>
  Object.fromEntries(
    (charts.value?.pie.counts ?? []).map((c, i) => [
      c.classification,
      palette[i % palette.length]!,
    ]),
  ),
)
const sectors = computed(() => {
  let start = -Math.PI / 2
  return (charts.value?.pie.counts ?? []).map((part) => {
    const angle = (2 * Math.PI * part.count) / (charts.value?.pie.denominator || 1)
    const end = start + angle
    const x = (a: number) => 150 + 115 * Math.cos(a)
    const y = (a: number) => 155 + 115 * Math.sin(a)
    const middle = start + angle / 2
    const path = `M150,155 L${x(start)},${y(start)} A115,115 0 ${angle / 2 > Math.PI ? 1 : 0},1 ${x(middle)},${y(middle)} A115,115 0 0,1 ${x(end)},${y(end)} Z`
    start = end
    return { ...part, path }
  })
})
const graph = computed(() => charts.value?.network)
const positioned = computed(() => {
  const nodes = graph.value?.nodes ?? []
  return nodes.map((n, i) => ({
    ...n,
    x:
      450 +
      (nodes.length === 1 ? 0 : 320 * Math.cos((2 * Math.PI * i) / nodes.length - Math.PI / 2)),
    y:
      410 +
      (nodes.length === 1 ? 0 : 290 * Math.sin((2 * Math.PI * i) / nodes.length - Math.PI / 2)),
  }))
})
const positions = computed(() => Object.fromEntries(positioned.value.map((n) => [n.id, n])))
const title = computed(
  () =>
    `${graph.value?.kind === 'molecule' ? '分子相关网络' : '带注释标签的 m/z 特征相关网络'} · ${graph.value?.method ?? ''}`,
)
const evidence = computed(() => {
  const rows: Record<string, unknown>[] = []
  for (const link of charts.value?.evidence ?? []) {
    if (node.value && ![link.source, link.target].includes(node.value.feature_id)) continue
    for (const sample of (link.samples ?? []) as Record<string, unknown>[])
      rows.push({
        source: link.source,
        target: link.target,
        type: link.type,
        candidates: link.candidate_names,
        level: link.level,
        ...sample,
        consensus: link.consensus,
      })
  }
  return {
    columns: [
      'source',
      'target',
      'type',
      'candidates',
      'level',
      'sample',
      'rho_all',
      'rho_joint',
      'joint_cells',
      'joint_fraction',
      'chemical_matched',
      'evaluable',
      'reason',
      'supported',
      'consensus',
    ],
    rows: rows.slice(evidenceOffset.value, evidenceOffset.value + pageSize),
    total: rows.length,
  }
})
const nodeEdges = computed(() =>
  (graph.value?.edges ?? []).filter(
    (e) => !node.value || [e.source, e.target].includes(node.value.id),
  ),
)
const edgeTable = computed(() => ({
  columns: [
    'source',
    'target',
    'sample',
    'rho_all',
    'rho_joint',
    'joint_cells',
    'joint_fraction',
    'relation_types',
  ],
  rows: nodeEdges.value.slice(edgeOffset.value, edgeOffset.value + pageSize) as unknown as Record<
    string,
    unknown
  >[],
  total: nodeEdges.value.length,
}))
function choose(n: LipidNode) {
  evidenceOffset.value = 0
  edgeOffset.value = 0
  node.value = n
  representative.value = n.feature_id
  emit('select', n.feature_id)
}
function clearNode() {
  node.value = undefined
  evidenceOffset.value = 0
  edgeOffset.value = 0
}
function changeGraph() {
  node.value = undefined
  view.focus = ''
}
async function applyView() {
  view.focus = ''
  node.value = undefined
  await load()
}
async function neighbors() {
  if (!node.value) return
  view.focus = node.value.id
  view.search = ''
  await load()
}
async function save() {
  if (
    await store.mutate(
      '/lipids/charts/save',
      { version: props.results.version, filters: props.filters, view },
      'POST',
      '',
    )
  ) {
    store.notice = '图表显示设置已加入工作区，请主动保存项目。'
  }
}
async function setRepresentative(reset = false) {
  if (!node.value) return
  if (
    await store.mutate(
      '/lipids/representative',
      {
        version: props.results.version,
        database_id: node.value.id,
        feature_id: reset ? '' : representative.value,
      },
      'POST',
      '',
    )
  ) {
    node.value = undefined
    emit('updated')
  }
}
async function download(kind: string) {
  if (!store.current) return
  const workspace = store.current.workspace_id
  const revision = store.current.revision
  await store.run(
    async (scope) => {
      const blob = await workspaceBlob('/lipids/export', {
        workspace,
        method: 'POST',
        body: { revision, version: props.results.version, filters: props.filters, view, kind },
        isCurrent: () =>
          scope.isCurrent() &&
          store.current?.workspace_id === workspace &&
          store.current?.revision === revision,
      })
      saveBlob(blob, `lipid-${kind}.${kind === 'charts' ? 'json' : 'csv'}`)
    },
    '',
    { label: '导出脂质分析结果', phase: 'downloading' },
  )
}
const { image } = useLipidImageExport({
  svg: (kind) => (kind === 'pie' ? pieSvg.value : graphSvg.value),
  width: () => paperWidth.value,
  dpi: () => paperDpi.value,
  font: () => paperFont.value,
  version: () => props.results.version,
})
</script>
<template>
  <section class="card lipid-network-panel">
    <h3>注释分类与相关网络</h3>
    <details class="plot-settings">
      <summary>注释图论文导出设置</summary>
      <div class="field-grid">
        <label
          >导出宽度（毫米）<input
            v-model.number="paperWidth"
            type="number"
            min="20"
            max="600" /></label
        ><label
          >导出字号（pt）<input
            v-model.number="paperFont"
            type="number"
            min="4.5"
            max="24" /></label
        ><label
          >导出分辨率（DPI）<input v-model.number="paperDpi" type="number" min="72" max="2400"
        /></label>
      </div>
    </details>
    <p class="muted">
      仅作 MS1
      候选辅助与共变探索。无支持不扣分；同分子式异构体不能据此区分。跨样本一致性不等于生物重复统计推断。
    </p>
    <fieldset :disabled="store.busy">
      <div class="field-grid">
        <label
          ><FieldLabel
            name="classification_level"
            text="每个当前筛选特征只计一次；人工选择优先，跨类别候选归多义，未注释单列。"
          /><select v-model="view.classification_level" aria-label="classification_level">
            <option>CATEGORY</option>
            <option>MAIN_CLASS</option>
            <option>SUB_CLASS</option>
          </select></label
        >
        <label
          ><FieldLabel name="graph" /><select
            v-model="view.graph"
            aria-label="网络 graph"
            @change="changeGraph"
          >
            <option value="feature">带注释标签的 m/z 特征网络</option>
            <option value="molecule">分子相关网络</option>
          </select></label
        >
        <label
          ><FieldLabel
            name="scope"
            text="样本视图显示逐样本边；条件视图要求同方向边达到重复共识，仍保留各支持样本的相关值。"
          /><select v-model="view.scope" aria-label="网络 scope">
            <option value="">首个样本</option>
            <option v-for="scope in graph?.scopes" :key="scope" :value="scope">{{ scope }}</option>
          </select></label
        >
      </div>
      <details>
        <summary>图表高级显示参数</summary>
        <div class="field-grid">
          <label
            ><FieldLabel name="sign" /><select v-model="view.sign" aria-label="网络 sign">
              <option value="both">正负边</option>
              <option value="positive">正相关</option>
              <option value="negative">负相关</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="node_limit"
              text="仅限制显示；辅助证据计算及节点/边导出不截断。" /><input
              v-model.number="view.node_limit"
              aria-label="node_limit"
              type="number"
              min="1"
              max="2000"
          /></label>
          <label
            ><FieldLabel name="search" text="搜索节点 ID、m/z 和候选名称；清空可恢复。" /><input
              v-model="view.search"
              aria-label="网络节点搜索"
          /></label>
          <label
            ><FieldLabel name="category" /><select v-model="view.category" aria-label="网络类别">
              <option value="">全部类别</option>
              <option v-for="c in charts?.pie.counts" :key="c.classification">
                {{ c.classification }}
              </option>
            </select></label
          >
        </div>
      </details>
      <div class="actions">
        <button @click="applyView" class="preview">应用图表显示</button
        ><button @click="save" class="save">保存图表设置</button>
      </div>
    </fieldset>
    <template v-if="charts">
      <p>
        饼图：{{ charts.pie.level }} · {{ charts.pie.denominator }} 个特征 · candidate_mode={{
          charts.pie.candidate_mode
        }}
        · 人工优先；使用当前已应用的注释筛选。
      </p>
      <svg
        ref="pieSvg"
        :viewBox="`0 0 900 ${pieBodyHeight + filterLines.length * 15}`"
        role="img"
        aria-label="注释分类饼图"
        style="width: 100%; max-height: 360px; background: white; color: #172033"
      >
        <metadata>
          {{
            JSON.stringify({
              version: results.version,
              filters: charts.pie.filters,
              view: charts.options,
              legend_order: pieLegend,
              layer: graph?.layer,
            })
          }}
        </metadata>
        <rect width="900" :height="pieBodyHeight + filterLines.length * 15" fill="white" />
        <text x="20" y="24" font-size="16" fill="#172033">
          {{ charts.pie.level }} · {{ charts.pie.denominator }} 特征 ·
          {{ charts.pie.candidate_mode }} · 人工优先
        </text>
        <path
          v-for="part in sectors"
          :key="part.classification"
          :d="part.path"
          :fill="colors[part.classification]"
        >
          <title>{{ part.classification }}: {{ part.count }}</title>
        </path>
        <g v-for="(part, i) in orderedCounts" :key="part.classification">
          <rect
            x="300"
            :y="45 + i * 23"
            width="12"
            height="12"
            :fill="colors[part.classification]"
          />
          <text x="320" :y="57 + i * 23" font-size="13" fill="#172033">
            {{ part.classification }}: {{ part.count }}
          </text>
        </g>
        <text
          x="20"
          :y="Math.max(300, (charts.pie.counts.length + 3) * 23 - 10)"
          font-size="10"
          fill="#475569"
        >
          annotation_version={{ results.version }}
        </text>
        <text
          v-for="(line, i) in filterLines"
          :key="i"
          x="20"
          :y="pieBodyHeight + i * 15"
          font-size="10"
          fill="#475569"
        >
          {{ line }}
        </text>
      </svg>
      <LegendOrder
        :items="pieLegend"
        :disabled="store.busy"
        @move="movePieLegend"
        @reset="resetPieLegend"
      />
      <ul class="chart-legend">
        <li v-for="part in orderedCounts" :key="part.classification">
          {{ part.classification }}：{{ part.count }}
        </li>
      </ul>
      <div class="actions">
        <button :disabled="store.busy" @click="image('pie', 'svg')" class="save">
          下载饼图 SVG</button
        ><button class="save" :disabled="store.busy" @click="image('pie', 'png')">
          下载饼图 PNG</button
        ><button class="save" :disabled="store.busy" @click="download('pie')">
          导出分类计数 CSV
        </button>
      </div>
      <template v-if="graph">
        <h4>{{ title }}</h4>
        <p>
          强度来源：{{ graph.layer }} · {{ graph.scope }} · |ρ| ≥
          {{ graph.parameters.plot_threshold }} · 显示 {{ graph.nodes.length }} /
          {{ graph.total_nodes }} 节点
        </p>
        <p class="muted">
          蓝色实线：正相关；红色虚线：负相关。边悬停查看逐样本相关与共同检出数，点击节点查看候选。圆形布局仅安排位置，不表示距离。
        </p>
        <p v-if="graph.kind === 'molecule'" class="muted">
          按稳定数据库 ID 合并，固定代表离子；{{ graph.undetermined_features.length }}
          个多义或未注释特征保持待定。total 层反映相对丰度共变，解释负相关需考虑总量约束。
        </p>
        <p v-if="graph.truncated" class="muted">
          节点上限只限制显示；搜索或展开邻居可查看其他节点。
        </p>
        <svg
          ref="graphSvg"
          :viewBox="`0 0 900 ${810 + filterLines.length * 15}`"
          role="img"
          aria-label="脂质相关网络"
          class="network-svg"
        >
          <rect width="900" :height="810 + filterLines.length * 15" fill="white" />
          <text x="20" y="25" font-size="17" fill="#172033">{{ title }}</text>
          <text x="20" y="49" font-size="12" fill="#475569">
            layer={{ graph.layer }} · scope={{ graph.scope }} · |ρ| ≥
            {{ graph.parameters.plot_threshold }}
          </text>
          <text x="20" y="70" font-size="12" fill="#475569">
            蓝色实线：正相关；红色虚线：负相关 · 节点 {{ graph.nodes.length }}/{{
              graph.total_nodes
            }}
          </text>
          <g v-for="(edge, i) in graph.edges" :key="i">
            <line
              :x1="positions[edge.source]?.x"
              :y1="positions[edge.source]?.y"
              :x2="positions[edge.target]?.x"
              :y2="positions[edge.target]?.y"
              :stroke="edge.sign === 'positive' ? '#2563eb' : '#dc2626'"
              :stroke-dasharray="edge.sign === 'negative' ? '6 4' : undefined"
              :stroke-width="1 + Math.abs(edge.rho_all) * 2"
              opacity="0.5"
            >
              <title>
                {{ edge.source }} ↔ {{ edge.target }} · {{ edge.sample }} · ρ_all={{
                  edge.rho_all
                }}
                · ρ_joint={{ edge.rho_joint }} · n={{ edge.joint_cells }} ·
                {{ edge.relation_types.join(', ') }}
              </title>
            </line>
          </g>
          <g
            v-for="n in positioned"
            :key="n.id"
            role="button"
            tabindex="0"
            :aria-label="`网络节点 ${n.id}`"
            @click="choose(n)"
            @keydown.enter="choose(n)"
          >
            <circle
              :cx="n.x"
              :cy="n.y"
              r="7"
              :fill="colors[n.classification] || '#475569'"
              :stroke="node?.id === n.id ? '#111827' : 'white'"
              stroke-width="2"
            >
              <title>
                {{ n.id }} · m/z {{ n.mz }} · {{ n.label }} · {{ n.classification }} ·
                {{ n.review }}
              </title>
            </circle>
            <text :x="n.x + 10" :y="n.y + 4" font-size="10" fill="#172033">
              {{ n.mz.toFixed(4) }} {{ n.label.length > 22 ? n.label.slice(0, 22) + '…' : n.label }}
            </text>
          </g>
          <text x="20" y="780" font-size="11" fill="#475569">
            annotation_version={{ results.version }} · 圆形布局无距离含义
          </text>
          <text
            v-for="(line, i) in filterLines"
            :key="i"
            x="20"
            :y="800 + i * 15"
            font-size="10"
            fill="#475569"
          >
            {{ line }}
          </text>
        </svg>
        <div class="actions">
          <button :disabled="store.busy" @click="image('network', 'svg')" class="save">
            下载网络 SVG</button
          ><button class="save" :disabled="store.busy" @click="image('network', 'png')">
            下载网络 PNG</button
          ><button class="save" :disabled="store.busy" @click="download(`${view.graph}_nodes`)">
            导出网络节点 CSV</button
          ><button class="save" :disabled="store.busy" @click="download(`${view.graph}_edges`)">
            导出网络边 CSV</button
          ><button class="save" :disabled="store.busy" @click="download('charts')">
            导出图表与证据 JSON</button
          ><button class="save" :disabled="store.busy" @click="download('network_evidence')">
            导出辅助证据 CSV
          </button>
        </div>
        <div v-if="node" class="card">
          <p>
            {{ node.id }} · m/z {{ node.mz }} · {{ node.label }} · {{ node.classification }} ·
            {{ node.review }}
          </p>
          <div class="actions">
            <button :disabled="store.busy" @click="neighbors" class="preview">展开邻居</button
            ><button class="preview" @click="clearNode">查看全部证据</button>
          </div>
          <div v-if="graph.kind === 'molecule' && node.features" class="actions">
            <label
              >representative_feature<select
                v-model="representative"
                aria-label="representative_feature"
              >
                <option v-for="f in node.features" :key="f">{{ f }}</option>
              </select></label
            ><button :disabled="store.busy" @click="setRepresentative()" class="restore">
              指定代表离子</button
            ><button class="restore" :disabled="store.busy" @click="setRepresentative(true)">
              恢复自动代表
            </button>
          </div>
          <p class="muted">候选及人工核对在下方“结果与人工核对”同步显示。</p>
        </div>
        <details>
          <summary>网络边明细（{{ edgeTable.total }} 条逐样本边）</summary>
          <DataTableView :table="edgeTable" />
          <div v-if="edgeTable.total > pageSize" class="actions">
            <button
              :disabled="edgeOffset === 0"
              @click="edgeOffset = Math.max(0, edgeOffset - pageSize)"
            >
              边上一页</button
            ><span
              >{{ edgeOffset + 1 }}–{{ Math.min(edgeOffset + pageSize, edgeTable.total) }} /
              {{ edgeTable.total }}</span
            ><button
              :disabled="edgeOffset + pageSize >= edgeTable.total"
              @click="edgeOffset += pageSize"
            >
              边下一页
            </button>
          </div>
        </details>
        <details>
          <summary>化学关系与逐样本辅助证据（{{ evidence.total }} 条）</summary>
          <p class="muted">
            level：0 无可用支持，1 单样本支持，2
            同条件重复支持；不可评估不进入共识分母。候选不递归传播。所有原始相关值与化学检查结果保留。
          </p>
          <DataTableView :table="evidence" />
          <div v-if="evidence.total > pageSize" class="actions">
            <button
              :disabled="evidenceOffset === 0"
              @click="evidenceOffset = Math.max(0, evidenceOffset - pageSize)"
            >
              证据上一页</button
            ><span
              >{{ evidenceOffset + 1 }}–{{ Math.min(evidenceOffset + pageSize, evidence.total) }} /
              {{ evidence.total }}</span
            ><button
              :disabled="evidenceOffset + pageSize >= evidence.total"
              @click="evidenceOffset += pageSize"
            >
              证据下一页
            </button>
          </div>
        </details>
      </template>
      <p v-else class="muted">旧版本没有相关网络，请使用当前参数重新运行注释。</p>
    </template>
  </section>
</template>
<style scoped>
.lipid-network-panel {
  min-width: 0;
  grid-column: 1 / -1;
  overflow-wrap: anywhere;
}
fieldset {
  min-width: 0;
}
.network-svg {
  width: 100%;
  background: white;
  min-height: 340px;
}
.network-svg [role='button'] {
  cursor: pointer;
}
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.5rem;
  overflow-wrap: anywhere;
}
</style>
