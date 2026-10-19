<script setup lang="ts">
import { useViewState } from '../../api/viewState'
import PlotView from '../../components/PlotView.vue'
import type { Figure } from '../../api/types'
import { computed, reactive, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import { useAuth } from '../../stores/auth'
import { authenticatedFetch, sessionVersion, ensureSession } from '../../api/client'
import DataTableView from '../../components/DataTable.vue'
import LipidNetworkOptions from './LipidNetworkOptions.vue'
import LipidNetworkPanel from './LipidNetworkPanel.vue'
import type { LipidInfo, LipidResults, LipidRules } from './lipids'

const store = useWorkspace()
const auth = useAuth()
const info = ref<LipidInfo>()
const results = ref<LipidResults>()
const isotopeFigure = ref<Figure>()
async function viewIsotope(id: string) {
  const result = await store.command<Figure>('/lipids/isotope-spectrum', {
    version: version.value,
    relation_id: id,
  })
  if (result) isotopeFigure.value = result
}
const rules = ref<LipidRules>({ schema_version: 1, name: '', rules: [] })
const imported = ref(false)
const preset = ref('')
const presetName = ref('')
const version = ref('')
const label = ref('')
const feature = ref('')
const selection = ref<string[]>([])
const offset = ref(0)
const relationOffset = ref(0)
const ruleOffset = ref(0)
const candidateSort = ref('recommended'),
  candidateDescending = ref(false)
const relationSort = ref('recommended'),
  relationDescending = ref(false)
const candidateSortOptions = {
  recommended: '规则推荐顺序',
  query_mz: '实测 m/z',
  theoretical_mz: '理论 m/z',
  name: '物质名',
  CATEGORY: '类别',
  MAIN_CLASS: '主类',
  SUB_CLASS: '子类',
  database_id: '数据库 ID',
  adduct: '加合物',
  abs_ppm_error: '绝对 ppm 误差',
  ppm_error: '带符号 ppm 误差',
  ppm_band: 'ppm 档',
  network_level: '网络支持',
  class_score: '类别分',
  adduct_score: '加合物分',
  rule_score: '规则分',
}
const relationSortOptions = {
  recommended: '原始证据顺序',
  parent_mz: '母峰 m/z',
  isotope_mz: '子峰 m/z',
  order: '同位素阶数',
  sample: '样本',
  abs_ppm_error: '绝对 ppm 误差',
  ppm_error: '带符号 ppm 误差',
  theoretical_ratio: '理论比例',
  observed_ratio: '实测比例',
  valid_cells: '有效细胞数',
  matched: '自动命中',
  review: '人工状态',
}
const sorting = computed(() => ({
  candidate_sort: candidateSort.value,
  candidate_descending: candidateDescending.value,
  relation_sort: relationSort.value,
  relation_descending: relationDescending.value,
}))
watch(
  [candidateSort, candidateDescending, relationSort, relationDescending],
  () => void loadResults(true),
)
const limit = 50
watch(rules, () => (ruleOffset.value = 0))
const options = reactive({
  database: '',
  polarity: 'pos',
  adducts: ['[M+H]+', '[M+Na]+', '[M+K]+', '[M+NH4]+'],
  annotation_ppm: 10,
  isotope_ppm: 10,
  max_isotope_order: 3,
  isotope_tolerance: 0.2,
  min_valid_cells: 20,
  intensity_layer: '',
  resolution: 35000,
  network: {
    method: 'spearman',
    support_all: 0.8,
    support_joint: 0.7,
    min_joint_cells: 30,
    plot_threshold: 0.7,
    consensus_fraction: 2 / 3,
    min_support_samples: 2,
    condition_field: '',
    samples: [] as string[],
    conditions: [] as string[],
    molecule_layer: 'total',
  },
})
const filters = reactive({
  query: '',
  category: '',
  main_class: '',
  sub_class: '',
  candidates: 'all',
  isotopes: 'all',
  review: 'all',
  adduct_mode: 'all',
  adducts: [] as string[],
  include_unannotated: true,
})
watch(
  () => filters.category,
  () => {
    filters.main_class = ''
    filters.sub_class = ''
  },
)
watch(
  () => filters.main_class,
  () => {
    filters.sub_class = ''
  },
)
function classificationChoices(field: string) {
  const tree = results.value?.classification_tree ?? []
  return [
    ...new Set(
      tree
        .filter(
          (row) =>
            (field === 'CATEGORY' || !filters.category || row.CATEGORY === filters.category) &&
            (field !== 'SUB_CLASS' || !filters.main_class || row.MAIN_CLASS === filters.main_class),
        )
        .map((row) => row[field]!)
        .filter(Boolean),
    ),
  ].sort()
}
const rulesTable = computed(() => ({
  columns: ['kind', 'level', 'value', 'polarity', 'adduct', 'score'],
  rows: rules.value.rules.slice(ruleOffset.value, ruleOffset.value + limit),
  total: rules.value.rules.length,
}))
const featureIndex = computed(
  () => results.value?.features.findIndex((f) => f.id === feature.value) ?? -1,
)
const validVersion = computed(
  () => info.value?.versions.find((v) => v.id === version.value)?.valid ?? false,
)
let generation = 0
let queryGeneration = 0
let restoredVersion = ''

async function refresh(reset = false) {
  const token = ++generation
  const workspace = store.current?.workspace_id
  const value = await store.read<LipidInfo>('/lipids')
  if (!value || token !== generation || workspace !== store.current?.workspace_id) return
  info.value = value
  if (reset) {
    version.value = value.active
    options.intensity_layer = value.default_layer
    options.resolution = value.resolution ?? 35000
    options.database = value.database.files[0]?.filename ?? ''
    imported.value = false
    rules.value = { schema_version: 1, name: '', rules: [] }
    results.value = undefined
    restoredVersion = ''
    feature.value = ''
  }
}
watch(
  [
    () => store.project?.path,
    () => store.project?.dataset?.id,
    () => store.project?.dataset?.revision,
  ],
  async () => {
    results.value = undefined
    version.value = ''
    await refresh(true)
    if (version.value && validVersion.value) {
      const notice = store.notice
      if (await loadResults(true)) store.notice = notice
    }
  },
  { immediate: true },
)
watch(
  () => options.polarity,
  () => {
    options.adducts = Object.entries(info.value?.adducts ?? {})
      .filter(([, spec]) => options.polarity === 'both' || spec.polarity === options.polarity)
      .map(([name]) => name)
  },
)

async function prepare() {
  const value = await store.command('/lipids/database')
  if (!value) return
  await refresh()
  options.database = info.value?.database.files[0]?.filename ?? ''
  if (!store.error) store.notice = '本地脂质数据库已校验。'
}
async function loadResults(reset = false): Promise<boolean> {
  if (!version.value || !validVersion.value || store.busy) return false
  if (reset) {
    offset.value = 0
    relationOffset.value = 0
  }
  const token = ++queryGeneration
  const workspace = store.current?.workspace_id
  const selectedVersion = version.value
  const value = await store.inspect<LipidResults>('/lipids/query', {
    version: selectedVersion,
    filters: { ...filters, adducts: filters.adduct_mode === 'specified' ? filters.adducts : [] },
    feature_id: feature.value,
    offset: offset.value,
    relation_offset: relationOffset.value,
    sorting: sorting.value,
    limit,
  })
  if (
    !value ||
    token !== queryGeneration ||
    workspace !== store.current?.workspace_id ||
    selectedVersion !== version.value
  )
    return false
  if (restoredVersion !== selectedVersion) {
    restoredVersion = selectedVersion
    if (value.chart_filters && Object.keys(value.chart_filters).length) {
      Object.assign(filters, value.chart_filters)
      return await loadResults(true)
    }
  }
  results.value = value
  if (!imported.value) rules.value = value.rules
  selection.value =
    feature.value in value.selected ? [...value.selected[feature.value]!] : [...value.suggested]
  if (feature.value && !value.features.some((f) => f.id === feature.value)) {
    feature.value = ''
    return await loadResults(true)
  }
  return true
}
async function run() {
  const result = await store.mutate(
    '/lipids/run',
    { options, rules: rules.value, label: label.value },
    'POST',
    '',
  )
  if (!result) return
  await refresh()
  version.value = info.value?.active ?? ''
  feature.value = ''
  imported.value = false
  if (await loadResults(true)) store.notice = '注释与同位素版本已生成；矩阵强度和特征保留。'
}
async function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 5_000_000) {
    store.error = '规则文件超过 5 MB。'
    return
  }
  const value = await store.inspect<LipidRules>('/lipids/rules/import', {
    content: await file.text(),
    format: file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'json',
  })
  if (value) {
    rules.value = value
    imported.value = true
    store.notice = '规则已校验，可保存预设或应用排序。'
  }
}
function choosePreset() {
  const value = info.value?.presets[preset.value]
  if (value) {
    rules.value = JSON.parse(JSON.stringify(value))
    imported.value = true
  }
}
async function savePreset() {
  const value = await store.command<Record<string, LipidRules>>('/lipids/presets', {
    name: presetName.value,
    rules: rules.value,
  })
  if (value && info.value) {
    info.value.presets = value
    store.notice = '规则已保存为预设。'
  }
}
async function applyRules() {
  const value = await store.mutate(
    '/lipids/rules/apply',
    { version: version.value, rules: rules.value },
    'POST',
    '',
  )
  if (value) {
    imported.value = false
    if (await loadResults()) store.notice = '排序已更新，全部候选仍保留。'
  }
}
async function activate() {
  const value = await store.mutate('/lipids/activate', { version: version.value }, 'POST', '')
  if (value) {
    await refresh()
    if (version.value) {
      if (await loadResults(true)) store.notice = '已切换注释版本。'
    } else {
      results.value = undefined
      if (!store.error) store.notice = '已切回未注释状态。'
    }
  }
}
async function selectFeature(id: string) {
  feature.value = id
  await loadResults(true)
}
async function changeVersion() {
  results.value = undefined
  imported.value = false
  feature.value = ''
  await loadResults(true)
}
async function applyFilters() {
  feature.value = ''
  await loadResults(true)
}
async function moveFeature(step: number) {
  const next = results.value?.features[featureIndex.value + step]
  if (next) await selectFeature(next.id)
}
async function saveSelection(auto = false) {
  const value = await store.mutate(
    '/lipids/review',
    {
      version: version.value,
      feature_id: feature.value,
      candidate_ids: auto ? null : selection.value,
    },
    'POST',
    '',
  )
  if (value && (await loadResults())) store.notice = auto ? '已恢复规则推荐。' : '人工指定已保存。'
}
async function reviewRelation(id: unknown, review: string) {
  const value = await store.mutate('/lipids/review', {
    version: version.value,
    relation_id: id,
    review,
  })
  if (value) {
    await refresh()
    if (await loadResults()) store.notice = '同位素核对已保存。'
  }
}
async function pageCandidates(step: number) {
  offset.value = Math.max(0, offset.value + step * limit)
  await loadResults()
}
async function pageRelations(step: number) {
  relationOffset.value = Math.max(0, relationOffset.value + step * limit)
  await loadResults()
}

async function download(kind: string) {
  if (!store.current || !version.value) return
  const workspace = store.current.workspace_id
  const revision = store.current.revision
  await store.run(async () => {
    const epoch = sessionVersion()
    const response = await authenticatedFetch('/api/v1/workspace/lipids/export', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-SCMM-Client': 'web',
        'X-SCMM-Workspace': workspace,
      },
      body: JSON.stringify({
        revision,
        version: version.value,
        filters: {
          ...filters,
          adducts: filters.adduct_mode === 'specified' ? filters.adducts : [],
        },
        kind,
        sorting: sorting.value,
      }),
    })
    if (!response.ok) {
      const body = await response.json()
      throw new Error(body.error?.message ?? '导出失败。')
    }
    const blob = await response.blob()
    ensureSession(epoch)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `lipid-${kind}.${kind === 'rules' ? 'json' : 'csv'}`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
}
function template() {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify({ schema_version: 1, name: '', rules: [] }, null, 2)], {
      type: 'application/json',
    }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = 'lipid-rules-template.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function number(value: unknown) {
  return typeof value === 'number' ? value.toPrecision(6) : '—'
}
useViewState('lipids', {
  version,
  label,
  feature,
  selection,
  offset,
  relationOffset,
  isotopeFigure,
  candidateSort,
  candidateDescending,
  relationSort,
  relationDescending,
})
</script>

<template>
  <section class="card lipid-panel" aria-labelledby="lipid-title">
    <div class="section-heading">
      <h2 id="lipid-title">注释与同位素</h2>
      <span class="muted">在筛选细胞与特征后进行候选注释与核对</span>
    </div>
    <p class="muted">
      一级精确质量候选注释。评分只用于排序，同位素命中只作标记；所有特征、强度和候选均保留。
    </p>
    <fieldset :disabled="store.busy">
      <legend>数据库与匹配</legend>
      <p class="lipid-path">数据库目录：{{ info?.database.directory }}</p>
      <p v-if="info?.database.error" class="muted">
        {{ info.database.error }}；已有注释仍可查看和导出。
      </p>
      <div class="field-grid">
        <label
          ><FieldLabel name="数据库文件" /><select
            aria-label="脂质数据库文件"
            v-model="options.database"
          >
            <option value="">自动选择本地数据库</option>
            <option
              v-for="file in info?.database.files"
              :key="file.filename"
              :value="file.filename"
            >
              {{ file.filename }}
            </option>
          </select></label
        >
        <label
          ><FieldLabel
            name="polarity"
            text="与实际采集极性一致；both 同时搜索正负候选，不推断实验极性。"
          /><select aria-label="脂质 polarity" v-model="options.polarity">
            <option value="pos">正离子</option>
            <option value="neg">负离子</option>
            <option value="both">正负候选</option>
          </select></label
        >
        <label
          ><FieldLabel
            name="annotation_ppm"
            text="实测与理论离子 m/z 的绝对 ppm 误差上限。全部容差内候选保留。" /><input
            aria-label="annotation_ppm"
            v-model.number="options.annotation_ppm"
            type="number"
            min="0"
            max="1000"
            step="any"
        /></label>
        <label
          ><FieldLabel name="版本名称" /><input
            aria-label="脂质版本名称"
            v-model="label"
            placeholder="注释与同位素"
            maxlength="200"
        /></label>
      </div>
      <div class="lipid-adducts">
        <label
          v-for="(spec, name) in info?.adducts"
          :key="name"
          v-show="options.polarity === 'both' || spec.polarity === options.polarity"
          ><input type="checkbox" :value="name" v-model="options.adducts" />{{ name }}</label
        >
      </div>
      <button class="secondary save" @click="prepare">
        {{ info?.database.available ? '检查本地数据库' : '准备数据库（缺失时官方下载）' }}
      </button>
    </fieldset>

    <fieldset :disabled="store.busy">
      <legend>评分规则与预设</legend>
      <p class="muted">
        先按绝对 ppm 的 0–2、&gt;2–5、&gt;5
        三档排序，档内按类别分＋加合物分排序，同分并列。没有内置评分规则。
      </p>
      <div class="field-grid">
        <label
          ><FieldLabel
            name="导入规则"
            text="支持 JSON 和 CSV；只读取声明式分值，不执行代码。格式见参数文档。" /><input
            aria-label="导入脂质规则"
            type="file"
            accept=".json,.csv"
            @change="importFile"
        /></label>
        <label
          ><FieldLabel name="规则预设" /><select
            aria-label="脂质规则预设"
            v-model="preset"
            @change="choosePreset"
          >
            <option value="">选择已保存预设</option>
            <option v-for="(_, name) in info?.presets" :key="name" :value="name">{{ name }}</option>
          </select></label
        >
        <label
          ><FieldLabel name="预设名称" /><input
            aria-label="脂质预设名称"
            v-model="presetName"
            maxlength="200"
        /></label>
      </div>
      <div class="actions">
        <button class="secondary save" @click="template">下载空规则模板</button
        ><button
          v-if="auth.admin"
          class="secondary save"
          :disabled="!presetName.trim()"
          @click="savePreset"
        >
          保存为规则预设</button
        ><button class="primary" :disabled="!validVersion || !imported" @click="applyRules">
          应用规则排序
        </button>
      </div>
      <details class="lipid-rule-preview">
        <summary>
          查看规则（{{ rules.rules.length }} 项）{{ imported ? ' · 尚未应用' : '' }}
        </summary>
        <DataTableView :table="rulesTable" />
        <div v-if="rules.rules.length > limit" class="actions">
          <button
            :disabled="ruleOffset === 0"
            @click="ruleOffset = Math.max(0, ruleOffset - limit)"
          >
            规则上一页
          </button>
          <span
            >第 {{ Math.floor(ruleOffset / limit) + 1 }} /
            {{ Math.ceil(rules.rules.length / limit) }} 页</span
          >
          <button :disabled="ruleOffset + limit >= rules.rules.length" @click="ruleOffset += limit">
            规则下一页
          </button>
        </div>
        <p class="muted">
          类别支持 CATEGORY、MAIN_CLASS、SUB_CLASS、LIPID_CLASS；较具体规则覆盖同项的通用规则。
        </p>
      </details>
    </fieldset>

    <fieldset :disabled="store.busy">
      <legend>天然同位素设置</legend>
      <LipidNetworkOptions v-model="options.network" :info="info" />
      <div class="field-grid">
        <label
          ><FieldLabel
            name="intensity_layer"
            text="选择未归一化、未插补的强度层。导入数据的初始层未必是原始强度，请按来源核对。"
          /><select aria-label="脂质 intensity_layer" v-model="options.intensity_layer">
            <option v-for="item in info?.layers" :key="item" :value="item">{{ item }}</option>
          </select></label
        >
        <label
          ><FieldLabel
            name="isotope_ppm"
            text="观测特征与预测同位素 m/z 的匹配容差；与仪器能否分开相邻峰的分辨率分开设置。" /><input
            aria-label="isotope_ppm"
            v-model.number="options.isotope_ppm"
            type="number"
            min="0"
            max="1000"
            step="any"
        /></label>
        <label
          ><FieldLabel
            name="max_isotope_order"
            text="检查 M+1 至 M+n，默认 3；增加阶数会增加关系证据量。" /><input
            aria-label="max_isotope_order"
            v-model.number="options.max_isotope_order"
            type="number"
            min="1"
            max="10"
        /></label>
        <label
          ><FieldLabel
            name="isotope_tolerance"
            text="相对理论比例的双侧容差；0.2 表示理论比例的 80%–120%，不是相差 20 个百分点。" /><input
            aria-label="isotope_tolerance"
            v-model.number="options.isotope_tolerance"
            type="number"
            min="0"
            max="1"
            step="0.01"
        /></label>
        <label
          ><FieldLabel
            name="min_valid_cells"
            text="每个样本至少有这么多母峰强度为正、子峰强度非负的有限细胞对。子峰的零值参与统计。" /><input
            aria-label="脂质 min_valid_cells"
            v-model.number="options.min_valid_cells"
            type="number"
            min="1"
        /></label>
        <label
          ><FieldLabel
            name="resolution"
            text="m/z 200 处的分辨率，用于估计理论细结构是否合峰；初值来自项目参数，请核对实际采集设置。" /><input
            aria-label="脂质 resolution"
            v-model.number="options.resolution"
            type="number"
            min="1"
            step="any"
        /></label>
      </div>
      <button :disabled="!options.adducts.length" @click="run" class="primary">
        运行注释与同位素标记
      </button>
    </fieldset>

    <fieldset :disabled="store.busy">
      <legend>独立处理版本</legend>
      <div class="field-grid">
        <label
          ><FieldLabel name="查看版本（北京时间）" /><select
            aria-label="脂质查看版本"
            v-model="version"
            @change="changeVersion"
          >
            <option value="">未注释状态</option>
            <option v-for="item in info?.versions" :key="item.id" :value="item.id">
              {{ item.label }} ·
              {{
                new Date(item.created_at).toLocaleString('zh-CN', {
                  timeZone: 'Asia/Shanghai',
                  hour12: false,
                })
              }}{{ item.valid ? '' : ' · 已过期' }}{{ item.id === info?.active ? ' · 当前' : '' }}
            </option>
          </select></label
        >
      </div>
      <div class="actions">
        <button class="secondary preview" :disabled="!!version && !validVersion" @click="activate">
          使用此注释版本</button
        ><button class="secondary preview" :disabled="!validVersion" @click="loadResults(true)">
          读取注释结果
        </button>
      </div>
      <p v-if="version && !validVersion" class="muted">
        该版本输入已改变，不能作为当前结果下载，请重新运行。
      </p>
      <p class="muted">
        切换只改变注释和标记，不改变矩阵或使数值分析失效。请主动保存项目以保留版本和核对进度。
      </p>
    </fieldset>

    <div v-if="results" class="lipid-results">
      <LipidNetworkPanel
        :results="results"
        :filters="{
          ...filters,
          adducts: filters.adduct_mode === 'specified' ? filters.adducts : [],
        }"
        @select="selectFeature"
        @updated="loadResults()"
      />
      <aside class="lipid-filters">
        <h3>显示与导出筛选</h3>
        <fieldset :disabled="store.busy">
          <label
            ><FieldLabel name="搜索" /><input aria-label="脂质结果搜索" v-model="filters.query"
          /></label>
          <label
            v-for="[key, field, title] in [
              ['category', 'CATEGORY', '类别'],
              ['main_class', 'MAIN_CLASS', '主类'],
              ['sub_class', 'SUB_CLASS', '子类'],
            ]"
            :key="key"
            ><FieldLabel :name="title!" /><select
              :aria-label="`脂质${title}`"
              :value="filters[key as 'category' | 'main_class' | 'sub_class']"
              @change="
                filters[key as 'category' | 'main_class' | 'sub_class'] = (
                  $event.target as HTMLSelectElement
                ).value
              "
            >
              <option value="">全部</option>
              <option v-for="name in classificationChoices(field!)" :key="name" :value="name">
                {{ name }}
              </option>
            </select></label
          >
          <label
            ><FieldLabel name="候选范围" /><select
              aria-label="脂质候选范围"
              v-model="filters.candidates"
            >
              <option value="all">全部候选</option>
              <option value="top">首档最高分及并列项 / 人工指定</option>
              <option value="manual">仅人工指定</option>
            </select></label
          >
          <label
            ><FieldLabel name="同位素状态" /><select
              aria-label="同位素状态"
              v-model="filters.isotopes"
            >
              <option value="all">全部特征</option>
              <option value="hide">隐藏命中同位素的特征</option>
              <option value="only">仅命中同位素的特征</option>
            </select></label
          >
          <label
            ><FieldLabel name="标记依据" /><select
              aria-label="同位素标记依据"
              v-model="filters.review"
            >
              <option value="all">自动命中及人工接受</option>
              <option value="accepted">仅人工接受</option>
            </select></label
          >
          <label
            ><FieldLabel name="加合物保留方式" /><select
              aria-label="加合物保留方式"
              v-model="filters.adduct_mode"
            >
              <option value="all">全部加合物</option>
              <option value="strongest">每种物质保留最强加合物峰</option>
              <option value="specified">仅指定加合物</option>
            </select></label
          >
          <div v-if="filters.adduct_mode === 'specified'" class="lipid-adducts">
            <label v-for="(_, name) in info?.adducts" :key="name"
              ><input type="checkbox" :value="name" v-model="filters.adducts" />{{ name }}</label
            >
          </div>
          <label class="lipid-check"
            ><input type="checkbox" v-model="filters.include_unannotated" />保留未注释峰</label
          >
          <button @click="applyFilters" class="preview">应用显示筛选</button>
        </fieldset>
        <p class="muted">CSV 使用当前筛选条件，包含全部细胞；不会只导出当前页或选中特征。</p>
        <div class="lipid-downloads">
          <button class="save" :disabled="store.busy || !validVersion" @click="download('matrix')">
            导出筛选矩阵 CSV</button
          ><button
            class="save"
            :disabled="store.busy || !validVersion"
            @click="download('candidates')"
          >
            导出候选明细 CSV</button
          ><button
            class="save"
            :disabled="store.busy || !validVersion"
            @click="download('isotopes')"
          >
            导出完整同位素关系 CSV</button
          ><button class="secondary save" :disabled="store.busy" @click="download('rules')">
            导出版本规则 JSON
          </button>
        </div>
      </aside>

      <div class="lipid-tables">
        <h3>结果与人工核对</h3>
        <div class="field-grid table-sorting">
          <label
            >排序条件<select
              v-model="candidateSort"
              aria-label="候选排序条件"
              :disabled="store.busy"
            >
              <option v-for="(title, key) in candidateSortOptions" :key="key" :value="key">
                {{ title }}
              </option>
            </select></label
          >
          <label
            >排序方向<select
              v-model="candidateDescending"
              aria-label="候选排序方向"
              :disabled="store.busy"
            >
              <option :value="false">升序</option>
              <option :value="true">降序</option>
            </select></label
          >
        </div>
        <p class="muted">全部结果排序后分页，缺失值置后；不改变规则推荐和人工核对。</p>
        <p>
          {{ results.features.length }} / {{ results.total_features }} 特征 ·
          {{ results.candidates.total }} 条候选 · {{ results.isotopes.total }} 条关系证据
        </p>
        <p class="muted lipid-path">
          {{ results.database.filename }} · 强度来源 {{ results.intensity_layer || 'X' }}
        </p>
        <div class="field-grid">
          <label
            ><FieldLabel name="逐特征核对" /><select
              aria-label="脂质逐特征核对"
              :value="feature"
              :disabled="store.busy"
              @change="selectFeature(($event.target as HTMLSelectElement).value)"
            >
              <option value="">查看全部特征</option>
              <option v-for="item in results.features" :key="item.id" :value="item.id">
                {{ item.id }} · m/z {{ item.mz.toPrecision(10) }} · {{ item.candidates }} 候选{{
                  item.isotope ? ' · 同位素命中' : ''
                }}{{ item.reviewed ? ' · 已核对' : '' }}
              </option>
            </select></label
          >
        </div>
        <div class="actions">
          <button
            class="secondary restore"
            :disabled="store.busy || featureIndex <= 0"
            @click="moveFeature(-1)"
          >
            上一特征</button
          ><button
            class="secondary"
            :disabled="store.busy || featureIndex >= results.features.length - 1"
            @click="moveFeature(1)"
          >
            下一特征</button
          ><button class="save" :disabled="store.busy || !feature" @click="saveSelection()">
            保存人工指定</button
          ><button
            class="secondary restore"
            :disabled="store.busy || !feature"
            @click="saveSelection(true)"
          >
            恢复规则推荐
          </button>
        </div>
        <div class="data-table">
          <table>
            <thead>
              <tr>
                <th v-if="feature">指定</th>
                <th>特征 ID</th>
                <th>实测 m/z</th>
                <th>理论 m/z</th>
                <th>物质名</th>
                <th>主类</th>
                <th>数据库 ID</th>
                <th>分子式</th>
                <th>加合物</th>
                <th>
                  <FieldLabel
                    name="ppm_error"
                    text="带符号误差，正数表示实测偏高，负数表示偏低。"
                  />
                </th>
                <th>ppm 档</th>
                <th>网络支持</th>
                <th>类别分</th>
                <th>加合物分</th>
                <th>规则分</th>
                <th>排序证据</th>
              </tr>
            </thead>
            <tbody>
              <template
                v-for="group in results.candidate_groups || []"
                :key="group.feature_id + group.label + group.formula + group.adduct"
                ><tr>
                  <td colspan="17">
                    <details>
                      <summary>
                        {{ group.feature_id }} · {{ group.label }} · {{ group.adduct }}（{{
                          group.rows.length
                        }}
                        个候选） · m/z {{ Number(group.rows[0]?.query_mz).toPrecision(10) }} · |ppm|
                        {{ number(Math.abs(Number(group.rows[0]?.ppm_error))) }} · 规则分
                        {{ group.rows[0]?.scored ? group.rows[0]?.rule_score : '未评分' }} ·
                        网络支持
                        {{
                          ['无可用支持', '单样本支持', '同条件重复支持'][
                            Number(group.rows[0]?.network_level ?? 0)
                          ]
                        }}
                      </summary>
                      <p v-for="row in group.rows" :key="String(row.candidate_id)">
                        <input
                          v-if="feature"
                          type="checkbox"
                          v-model="selection"
                          :value="String(row.candidate_id)"
                          :aria-label="`指定 ${row.database_id} ${row.adduct}`"
                          :disabled="store.busy"
                        />{{ row.name }} · {{ row.database_id }} · {{ row.formula }} · 误差
                        {{ number(row.ppm_error) }} ppm
                      </p>
                      <details>
                        <summary>完整匹配与评分字段</summary>
                        <DataTableView
                          :table="{
                            columns: Object.keys(group.rows[0] || {}),
                            rows: group.rows,
                            total: group.rows.length,
                          }"
                        />
                      </details>
                    </details>
                  </td></tr
              ></template>
              <tr
                v-for="row in results.candidate_groups ? [] : results.candidates.rows"
                :key="String(row.candidate_id)"
              >
                <td v-if="feature">
                  <input
                    type="checkbox"
                    v-model="selection"
                    :value="String(row.candidate_id)"
                    :aria-label="`指定 ${row.database_id} ${row.adduct}`"
                    :disabled="store.busy"
                  />
                </td>
                <td>{{ row.feature_id }}</td>
                <td>{{ Number(row.query_mz).toPrecision(10) }}</td>
                <td>
                  {{ Number(row.theoretical_mz).toPrecision(10)
                  }}<HelpTip :text="String(row.theoretical_mz)" label="完整理论质量" />
                </td>
                <td>{{ row.name }}</td>
                <td>{{ row.MAIN_CLASS }}</td>
                <td>{{ row.database_id }}</td>
                <td>{{ row.formula }}</td>
                <td>{{ row.adduct }}</td>
                <td>{{ number(row.ppm_error) }}</td>
                <td>{{ row.ppm_band }}</td>
                <td
                  :title="
                    JSON.stringify({
                      samples: row.network_samples,
                      relations: row.network_relations,
                    })
                  "
                >
                  {{ ['无可用支持', '单样本支持', '同条件重复支持'][Number(row.network_level ?? 0)]
                  }}{{ row.network_inconsistent ? ' · 重复不一致' : '' }}
                </td>
                <td>{{ row.class_score }}</td>
                <td>{{ row.adduct_score }}</td>
                <td>{{ row.scored ? row.rule_score : '未评分' }}</td>
                <td>
                  {{ row.top_ranked ? '首档并列推荐' : '完整候选'
                  }}<HelpTip :text="String(row.score_evidence)" label="评分明细" />
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="!results.candidates.rows.length" class="muted">没有符合筛选条件的候选。</p>
        </div>
        <div class="actions">
          <button
            class="secondary"
            :disabled="store.busy || offset === 0"
            @click="pageCandidates(-1)"
          >
            候选上一页</button
          ><span
            >{{ offset + 1 }}–{{
              offset + (results.candidate_groups?.length ?? results.candidates.rows.length)
            }}
            / {{ results.candidate_group_total ?? results.candidates.total }} 个组成</span
          ><button
            class="secondary"
            :disabled="
              store.busy ||
              offset + limit >= (results.candidate_group_total ?? results.candidates.total)
            "
            @click="pageCandidates(1)"
          >
            候选下一页
          </button>
        </div>

        <h3>天然同位素关系</h3>
        <div class="field-grid table-sorting">
          <label
            >排序条件<select
              v-model="relationSort"
              aria-label="同位素关系排序条件"
              :disabled="store.busy"
            >
              <option v-for="(title, key) in relationSortOptions" :key="key" :value="key">
                {{ title }}
              </option>
            </select></label
          >
          <label
            >排序方向<select
              v-model="relationDescending"
              aria-label="同位素关系排序方向"
              :disabled="store.busy"
            >
              <option :value="false">升序</option>
              <option :value="true">降序</option>
            </select></label
          >
        </div>
        <p class="muted">全部结果排序后分页，缺失值置后；不改变规则推荐和人工核对。</p>
        <p class="muted">
          同一特征可有多个来源解释；每个样本分别记录。命中表示质量和双侧比例条件通过，不证明该峰只有同位素贡献。
        </p>
        <div class="data-table">
          <table>
            <thead>
              <tr>
                <th>母峰 → 子峰</th>
                <th>母峰 m/z</th>
                <th>子峰实测 / 预测 m/z</th>
                <th>来源注释</th>
                <th>阶数</th>
                <th>样本</th>
                <th>ppm</th>
                <th>理论比例</th>
                <th>实测比例</th>
                <th>有效细胞</th>
                <th>自动命中</th>
                <th>人工状态</th>
                <th>核对</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in results.isotopes.rows" :key="String(row.relation_id)">
                <td>
                  {{ row.parent_feature_id }} → {{ row.isotope_feature_id
                  }}<button
                    class="preview"
                    :disabled="store.busy"
                    @click="viewIsotope(String(row.relation_id))"
                  >
                    查看截谱
                  </button>
                </td>
                <td>{{ Number(row.parent_mz).toPrecision(10) }}</td>
                <td>
                  {{ Number(row.isotope_mz).toPrecision(10) }} /
                  {{ Number(row.predicted_mz).toPrecision(10) }}
                </td>
                <td>{{ row.name }} {{ row.adduct }}</td>
                <td>M+{{ row.order }}</td>
                <td>{{ row.sample_name ?? row.sample }}</td>
                <td>{{ number(row.ppm_error) }}</td>
                <td>{{ number(row.theoretical_ratio) }}</td>
                <td>{{ number(row.observed_ratio) }}</td>
                <td>{{ row.valid_cells }}</td>
                <td>{{ row.matched ? '命中' : '未通过' }}</td>
                <td>
                  {{
                    row.review === 'accepted'
                      ? '接受'
                      : row.review === 'rejected'
                        ? '否定'
                        : '待核对'
                  }}
                </td>
                <td>
                  <div class="lipid-review">
                    <button
                      class="secondary"
                      :disabled="store.busy"
                      @click="reviewRelation(row.relation_id, 'accepted')"
                    >
                      接受</button
                    ><button
                      class="secondary"
                      :disabled="store.busy"
                      @click="reviewRelation(row.relation_id, 'rejected')"
                    >
                      否定</button
                    ><button
                      class="secondary"
                      :disabled="store.busy"
                      @click="reviewRelation(row.relation_id, 'pending')"
                    >
                      待核对
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <PlotView v-if="isotopeFigure" :figure="isotopeFigure" name="isotope-local-spectrum" />
          <p v-if="!results.isotopes.rows.length" class="muted">暂无质量匹配的同位素关系。</p>
        </div>
        <div class="actions">
          <button
            class="secondary"
            :disabled="store.busy || relationOffset === 0"
            @click="pageRelations(-1)"
          >
            关系上一页</button
          ><span
            >{{ relationOffset + 1 }}–{{ relationOffset + results.isotopes.rows.length }} /
            {{ results.isotopes.total }}</span
          ><button
            class="secondary"
            :disabled="store.busy || relationOffset + limit >= results.isotopes.total"
            @click="pageRelations(1)"
          >
            关系下一页
          </button>
        </div>
        <details v-if="results.diagnostics.length">
          <summary>
            无法计算分布的候选（{{ results.diagnostics.length }} 项，质量候选仍保留）
          </summary>
          <DataTableView
            :table="{
              columns: ['feature_id', 'formula', 'adduct', 'message'],
              rows: results.diagnostics,
              total: results.diagnostics.length,
            }"
          />
        </details>
      </div>
    </div>
  </section>
</template>

<style scoped>
.lipid-panel {
  min-width: 0;
}
fieldset {
  border: 1px solid var(--border, #dce4e9);
  border-radius: 8px;
  margin: 1rem 0;
  padding: 1rem;
  min-width: 0;
}
legend {
  font-weight: 650;
  padding: 0 0.4rem;
}
.lipid-path {
  overflow-wrap: anywhere;
}
.lipid-adducts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem 1.2rem;
  margin: 0.8rem 0;
}
.lipid-adducts label,
.lipid-check {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}
.lipid-adducts input,
.lipid-check input {
  width: auto;
}
.lipid-results {
  display: grid;
  grid-template-columns: minmax(200px, 250px) minmax(0, 1fr);
  gap: 1.2rem;
}
.lipid-filters,
.lipid-tables {
  min-width: 0;
}
.lipid-filters label {
  margin-bottom: 0.7rem;
}
.lipid-downloads {
  display: grid;
  gap: 0.5rem;
}
.lipid-review {
  display: flex;
  gap: 0.25rem;
}
.lipid-review button {
  padding: 0.25rem 0.4rem;
  white-space: nowrap;
}
@media (max-width: 900px) {
  .lipid-results {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
