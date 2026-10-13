<script setup lang="ts">
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import type { AnalysisInfo, Figure, DataTable } from '../../api/types'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
const store = useWorkspace(),
  info = ref<AnalysisInfo>()
const tab = ref('embedding')
const reduction = reactive({
  method: 'pca',
  store_key: 'X_pca',
  use_rep: 'X',
  n_components: 2,
  scale: false,
  random_state: 42,
  n_neighbors: 15,
  perplexity: 30,
  pca_components: 20,
  whiten: false,
  min_dist: 0.3,
  metric: 'euclidean',
  learning_rate: 'auto' as string | number,
  max_iter: 1000,
})
const usePca = ref(true)
const cluster = reactive({ method: 'kmeans', key: 'clusters', n_clusters: 3 })
const diff = reactive({
  group_key: '',
  group_a: '',
  group_b: '',
  method: 'mannwhitney',
  layer: null as string | null,
})
const network = reactive({ method: 'pearson', min_abs_correlation: 0.7, top_features: 50 })
const train = reactive({
  label_key: '',
  group_key: null as string | null,
  layer: null as string | null,
  model: 'logistic',
  cv: 5,
  test_size: 0.2,
  calibration_bins: 10,
  smote: false,
})
const ldaSolver = ref('svd'),
  validation = ref('grouped'),
  latentKey = ref('X_latent'),
  shap = reactive({ max_background: 100, max_samples: 100 })
const embedding = ref(''),
  colorSource = ref('annotation'),
  color = ref(''),
  search = ref(''),
  sort = ref('mean'),
  descending = ref(true),
  featureOptions = ref<{ value: string; label: string }[]>([]),
  featureTotal = ref(0),
  featureOffset = ref(0)
const selectedFeatures = ref<string[]>([]),
  hideZero = ref(false),
  volcano = reactive({ fdr: 0.05, fold_change: 1, labels: 10, order: 'fdr' })
const figures = ref<Record<string, Figure>>({}),
  tables = ref<Record<string, DataTable>>({}),
  modelReport = ref<Record<string, unknown>>()
const legend = ref('right')
let generation = 0,
  featureGeneration = 0,
  initializedPath = '',
  hydrating = false
const observed = computed(() => Object.keys(info.value?.observations ?? {}))
const groups = computed(() => info.value?.observations[diff.group_key] ?? [])
const colors = computed(() =>
  colorSource.value === 'annotation'
    ? observed.value
        .filter((c) => c.toLowerCase().includes(search.value.toLowerCase()))
        .map((c) => ({ value: `obs:${c}`, label: c }))
    : colorSource.value === 'feature'
      ? featureOptions.value.map((c) => ({ value: `feature:${c.value}`, label: c.label }))
      : [],
)
const settings = computed(() => ({
  reduction: { ...reduction },
  usePca: usePca.value,
  cluster: { ...cluster },
  diff: { ...diff },
  network: { ...network },
  train: { ...train },
  ldaSolver: ldaSolver.value,
  validation: validation.value,
  latentKey: latentKey.value,
  shap: { ...shap },
  embedding: embedding.value,
  colorSource: colorSource.value,
  color: color.value,
  volcano: { ...volcano },
  selectedFeatures: [...selectedFeatures.value],
  hideZero: hideZero.value,
}))
watch(
  [settings, legend],
  () => {
    if (store.project && initializedPath === store.project.path && !hydrating)
      store.analysisDraft = {
        path: store.project.path,
        analysis: settings.value,
        legend: legend.value,
      }
  },
  { deep: true },
)
function has(name: string) {
  return info.value?.results.includes(name) ?? false
}
function help(name: string) {
  return store.configuration?.analysis.find((p) => p.name === name)?.help ?? ''
}
async function refresh() {
  const token = ++generation
  if (!store.project?.dataset) {
    info.value = undefined
    figures.value = {}
    tables.value = {}
    return
  }
  const value = await store.read<AnalysisInfo>('/analysis')
  if (!value || token !== generation) return
  hydrating = true
  info.value = value
  if (initializedPath !== store.project.path) {
    initializedPath = store.project.path
    const defaults = Object.fromEntries(
      (store.configuration?.analysis ?? []).map((p) => [p.name, p.default]),
    )
    Object.assign(reduction, {
      method: defaults.reduction ?? 'pca',
      n_components: defaults.n_components ?? 2,
      n_neighbors: defaults.n_neighbors ?? 15,
      perplexity: defaults.perplexity ?? 30,
      random_state: defaults.random_state ?? 42,
    })
    Object.assign(cluster, {
      method: defaults.clustering ?? 'kmeans',
      n_clusters: defaults.n_clusters ?? 3,
    })
    Object.assign(train, {
      model: defaults.model ?? 'logistic',
      cv: defaults.cv ?? 5,
      test_size: defaults.test_size ?? 0.2,
      calibration_bins: defaults.calibration_bins ?? 10,
    })
    Object.assign(network, {
      method: defaults.network_method ?? 'pearson',
      min_abs_correlation: defaults.network_threshold ?? 0.7,
      top_features: defaults.network_top_features ?? 50,
    })
    Object.assign(shap, {
      max_background: defaults.shap_background ?? 100,
      max_samples: defaults.shap_samples ?? 100,
    })
    diff.method = String(defaults.differential_method ?? 'mannwhitney')
    const saved = value.settings
    for (const [key, target] of Object.entries({
      reduction,
      cluster,
      diff,
      network,
      train,
      shap,
      volcano,
    })) {
      if (saved[key] && typeof saved[key] === 'object') Object.assign(target, saved[key])
    }
    if (typeof saved.embedding === 'string') embedding.value = saved.embedding
    if (typeof saved.color === 'string') color.value = saved.color
    if (typeof saved.colorSource === 'string') colorSource.value = saved.colorSource
    if (typeof saved.usePca === 'boolean') usePca.value = saved.usePca
    if (typeof saved.ldaSolver === 'string') ldaSolver.value = saved.ldaSolver
    if (typeof saved.validation === 'string') validation.value = saved.validation
    if (typeof saved.latentKey === 'string') latentKey.value = saved.latentKey
    if (Array.isArray(saved.selectedFeatures))
      selectedFeatures.value = saved.selectedFeatures as string[]
    if (typeof saved.hideZero === 'boolean') hideZero.value = saved.hideZero
    legend.value = value.legend
  }
  if (!observed.value.includes(diff.group_key))
    diff.group_key =
      ['group', 'sample', 'clusters'].find((k) => observed.value.includes(k)) ??
      observed.value[0] ??
      ''
  if (!observed.value.includes(train.label_key)) train.label_key = diff.group_key
  if (!train.group_key || !observed.value.includes(train.group_key))
    train.group_key = observed.value.includes('subject')
      ? 'subject'
      : observed.value.includes('sample')
        ? 'sample'
        : null
  if (!value.embeddings.includes(embedding.value)) embedding.value = value.embeddings[0] ?? ''
  if (reduction.use_rep !== 'X' && !value.embeddings.includes(reduction.use_rep))
    reduction.use_rep = 'X'
  if (!color.value && colorSource.value === 'annotation') color.value = `obs:${diff.group_key}`
  for (const name of Object.keys(tables.value)) {
    if (!has(name)) delete tables.value[name]
  }
  for (const [kind, name] of Object.entries({
    volcano: 'differential',
    violin: 'differential',
    network_plot: 'network',
    shap_plot: 'shap',
    roc: 'supervised',
    pr: 'supervised',
    calibration: 'supervised',
  })) {
    if (!has(name)) delete figures.value[kind]
  }
  if (!value.embeddings.length) delete figures.value.embedding
  await Promise.resolve()
  hydrating = false
  void loadFeatures()
}
watch(
  [
    () => store.project?.path,
    () => store.project?.dataset?.id,
    () => store.project?.dataset?.revision,
  ],
  () => {
    figures.value = {}
    tables.value = {}
    modelReport.value = undefined
    void refresh()
  },
  { immediate: true },
)
watch(
  () => diff.group_key,
  () => {
    if (!groups.value.includes(diff.group_a)) diff.group_a = groups.value[0] ?? ''
    if (!groups.value.includes(diff.group_b) || diff.group_a === diff.group_b)
      diff.group_b = groups.value.find((g) => g !== diff.group_a) ?? groups.value[0] ?? ''
  },
)
watch(
  () => reduction.method,
  (method) => {
    if (!hydrating) reduction.store_key = `X_${method}`
  },
)
const pendingInvalidations = new Set<string>()
let invalidationScheduled = false
async function flushInvalidations() {
  if (store.busy || invalidationScheduled || !pendingInvalidations.size) return
  invalidationScheduled = true
  await nextTick()
  invalidationScheduled = false
  if (store.busy || !pendingInvalidations.size) return
  const names = [...pendingInvalidations]
  pendingInvalidations.clear()
  await store.mutate('/analysis/invalidate', { names })
  await refresh()
}
function invalidate(names: string[]) {
  if (hydrating || !info.value) return
  for (const n of names.filter(has)) {
    delete tables.value[n]
    pendingInvalidations.add(n)
  }
  if (names.includes('supervised')) modelReport.value = undefined
  void flushInvalidations()
}
watch(
  () => store.busy,
  (busy) => {
    if (!busy) void flushInvalidations()
  },
)
watch(
  () => store.project?.path,
  () => pendingInvalidations.clear(),
  { flush: 'sync' },
)
watch(
  () => JSON.stringify(diff),
  () => {
    if (!hydrating) void invalidate(['differential', 'markers'])
  },
)
watch(
  () => JSON.stringify([network, diff.layer]),
  () => {
    if (!hydrating) void invalidate(['network'])
  },
)
watch(
  () => JSON.stringify([train, validation.value, ldaSolver.value, reduction.random_state]),
  () => {
    if (!hydrating) void invalidate(['supervised', 'shap'])
  },
)
watch(
  () => JSON.stringify(shap),
  () => {
    if (!hydrating) void invalidate(['shap'])
  },
)
async function loadFeatures() {
  const token = ++featureGeneration
  const query = new URLSearchParams({
    query: search.value,
    sort: sort.value,
    descending: String(descending.value),
    offset: String(featureOffset.value),
    limit: '200',
  })
  const result = await store.read<{ rows: { value: string; label: string }[]; total: number }>(
    `/analysis/features?${query}`,
  )
  if (result && token === featureGeneration) {
    featureOptions.value = result.rows
    featureTotal.value = result.total
  }
}
watch([search, sort, descending], () => {
  featureOffset.value = 0
  void loadFeatures()
})
watch(colorSource, () => {
  search.value = ''
  color.value = colorSource.value === 'annotation' ? `obs:${diff.group_key}` : ''
  featureOffset.value = 0
  void loadFeatures()
})
async function execute(operation: string, options: Record<string, unknown>) {
  await store.mutate('/analysis/operation', { operation, options })
  if (store.error) return
  await refresh()
  if (operation === 'reduce') {
    embedding.value = String(options.store_key)
    await draw('embedding')
  } else if (operation === 'cluster') {
    colorSource.value = 'annotation'
    color.value = `obs:${options.key}`
    if (embedding.value) await draw('embedding')
  } else if (['differential', 'markers', 'network', 'train', 'explain_shap'].includes(operation)) {
    const resultName =
      operation === 'train' ? 'supervised' : operation === 'explain_shap' ? 'shap' : operation
    await loadResult(resultName)
    if (operation === 'differential') await draw('volcano')
    if (operation === 'network') await draw('network_plot')
    if (operation === 'train') {
      for (const kind of ['roc', 'pr', 'calibration']) await draw(kind)
    }
    if (operation === 'explain_shap') await draw('shap_plot')
  }
}
function reduce() {
  const options = {
    ...reduction,
    pca_components: reduction.method === 'umap' && usePca.value ? reduction.pca_components : null,
    learning_rate: reduction.learning_rate === 'auto' ? 'auto' : Number(reduction.learning_rate),
  }
  void execute('reduce', options)
}
function trainModel() {
  void execute('train', {
    ...train,
    group_key: validation.value === 'grouped' ? train.group_key : null,
    model_params: train.model === 'lda' ? { solver: ldaSolver.value } : {},
    random_state: reduction.random_state,
  })
}
async function loadResult(name: string, offset = 0) {
  const result = await store.read<{ table?: DataTable; diagnostics?: Record<string, unknown> }>(
    `/analysis/results/${name}?offset=${offset}`,
  )
  if (result?.table) tables.value[name] = result.table
  if (result?.diagnostics) modelReport.value = result.diagnostics
}
async function draw(kind: string) {
  const options =
    kind === 'embedding'
      ? { key: embedding.value, color: colorSource.value === 'none' ? null : color.value || null }
      : kind === 'volcano'
        ? { ...volcano }
        : kind === 'violin'
          ? {
              features: selectedFeatures.value,
              hide_zero: hideZero.value,
              columns: Math.max(1, Math.min(3, Math.floor(window.innerWidth / 400))),
            }
          : {}
  const value = await store.command<Figure>('/analysis/plot', { kind, options })
  if (value) figures.value[kind] = value
}
function toggleFeature(id: string) {
  const current = [...selectedFeatures.value]
  if (current.includes(id)) selectedFeatures.value = current.filter((x) => x !== id)
  else if (current.length < 12) selectedFeatures.value = [...current, id]
  else store.error = '最多选择 12 个特征。'
  if (has('differential')) void draw('violin')
}
function pageFeatures(delta: number) {
  featureOffset.value += delta
  void loadFeatures()
}
async function loadWithPlot(name: string, kind: string) {
  await loadResult(name)
  await draw(kind)
}
async function saveSettings() {
  await store.mutate(
    '/analysis/settings',
    { analysis: settings.value, legend: legend.value },
    'PUT',
    '视图与分析参数已记入当前项目；请主动保存项目。',
  )
}
</script>
<template>
  <section v-if="store.project?.dataset">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 05 / 分析</p>
        <h1>探索与分析</h1>
        <p>
          {{ store.project.dataset.cells }} 细胞 × {{ store.project.dataset.features }} 特征 ·
          结果随数据与依赖字段失效。
        </p>
      </div>
      <span class="step-badge">05 / 06</span>
    </div>
    <div class="card">
      <div class="section-heading">
        <div class="tabs">
          <button
            v-for="(label, key) in {
              embedding: '降维与聚类',
              differential: '差异与 Marker',
              network: '相关网络',
              supervised: '监督与 SHAP',
            }"
            :key="key"
            :class="{ selected: tab === key }"
            @click="tab = key"
          >
            {{ label }}
          </button>
        </div>
        <label class="field"
          ><FieldLabel name="图例" /><select aria-label="图例" v-model="legend">
            <option value="right">图右侧</option>
            <option value="top_left">图内左上</option>
            <option value="top_right">图内右上</option>
            <option value="bottom_left">图内左下</option>
            <option value="bottom_right">图内右下</option>
            <option value="hidden">隐藏</option>
          </select></label
        >
      </div>
      <button class="primary" :disabled="store.busy" @click="saveSettings">应用视图设置</button>
    </div>
    <div v-show="tab === 'embedding'" class="card">
      <h2>降维与聚类</h2>
      <div class="field-grid">
        <label
          ><FieldLabel name="reduction" /><select
            aria-label="reduction"
            v-model="reduction.method"
            :disabled="store.busy"
          >
            <option v-for="v in ['pca', 'umap', 'tsne', 'isomap', 'lle']" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="use_rep" /><select
            aria-label="use_rep"
            v-model="reduction.use_rep"
            :disabled="store.busy"
          >
            <option>X</option>
            <option v-for="v in info?.embeddings" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="n_components" /><input
            aria-label="n_components"
            v-model.number="reduction.n_components"
            type="number"
            min="1"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="store_key" /><input
            aria-label="store_key"
            v-model="reduction.store_key"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="random_state" /><input
            aria-label="random_state"
            v-model.number="reduction.random_state"
            type="number"
            min="0"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="scale" /><select
            aria-label="scale"
            v-model="reduction.scale"
            :disabled="store.busy"
          >
            <option :value="false">不标准化</option>
            <option :value="true">降维前标准化</option>
          </select></label
        >
      </div>
      <details>
        <summary>降维高级参数</summary>
        <div class="field-grid">
          <label v-if="['umap', 'isomap', 'lle'].includes(reduction.method)"
            ><FieldLabel name="n_neighbors" /><input
              aria-label="n_neighbors"
              v-model.number="reduction.n_neighbors"
              type="number"
              min="2"
              :disabled="store.busy" /></label
          ><label v-if="reduction.method === 'umap'"
            ><FieldLabel name="PCA preprocessing" /><select
              aria-label="PCA preprocessing"
              v-model="usePca"
              :disabled="store.busy"
            >
              <option :value="true">启用</option>
              <option :value="false">关闭</option>
            </select></label
          ><label v-if="reduction.method === 'umap' && usePca"
            ><FieldLabel name="PCA input dimensions" /><input
              aria-label="PCA input dimensions"
              v-model.number="reduction.pca_components"
              type="number"
              min="1"
              :disabled="store.busy" /></label
          ><label v-if="reduction.method === 'pca' || (reduction.method === 'umap' && usePca)"
            ><FieldLabel name="whiten" /><select
              aria-label="whiten"
              v-model="reduction.whiten"
              :disabled="store.busy"
            >
              <option :value="false">关闭</option>
              <option :value="true">启用</option>
            </select></label
          ><label v-if="reduction.method === 'umap'"
            ><FieldLabel name="min_dist" /><input
              aria-label="min_dist"
              v-model.number="reduction.min_dist"
              type="number"
              min="0"
              max="1"
              step="any"
              :disabled="store.busy" /></label
          ><label v-if="['umap', 'tsne', 'isomap'].includes(reduction.method)"
            ><FieldLabel name="metric" /><select
              aria-label="metric"
              v-model="reduction.metric"
              :disabled="store.busy"
            >
              <option>euclidean</option>
              <option>manhattan</option>
              <option>cosine</option>
            </select></label
          ><template v-if="reduction.method === 'tsne'"
            ><label
              ><FieldLabel name="perplexity" /><input
                aria-label="perplexity"
                v-model.number="reduction.perplexity"
                type="number"
                min="1"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="learning_rate" /><input
                aria-label="learning_rate"
                v-model="reduction.learning_rate"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="max_iter" /><input
                aria-label="max_iter"
                v-model.number="reduction.max_iter"
                type="number"
                min="250"
                :disabled="store.busy" /></label
          ></template>
        </div>
      </details>
      <button class="primary" :disabled="store.busy" @click="reduce">运行降维</button>
      <div class="field-grid">
        <label
          ><FieldLabel name="clustering" /><select
            aria-label="clustering"
            v-model="cluster.method"
            :disabled="store.busy"
          >
            <option v-for="v in ['kmeans', 'hierarchical', 'dbscan', 'leiden', 'louvain']" :key="v">
              {{ v }}
            </option>
          </select></label
        ><label v-if="['kmeans', 'hierarchical'].includes(cluster.method)"
          ><FieldLabel name="n_clusters" /><input
            aria-label="n_clusters"
            v-model.number="cluster.n_clusters"
            type="number"
            min="2"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="cluster_key" /><input
            aria-label="cluster_key"
            v-model="cluster.key"
            :disabled="store.busy"
        /></label>
      </div>
      <button
        class="primary"
        :disabled="store.busy"
        @click="
          execute('cluster', {
            ...cluster,
            use_rep: reduction.use_rep,
            n_neighbors: reduction.n_neighbors,
            random_state: reduction.random_state,
          })
        "
      >
        运行聚类
      </button>
      <p class="muted">
        DBSCAN 使用现有固定参数 0.5 / 5；图聚类 resolution 为 1。实验轨迹方法继续暂缓。
      </p>
      <div class="field-grid">
        <label
          ><FieldLabel name="查看嵌入" /><select
            aria-label="查看嵌入"
            v-model="embedding"
            :disabled="store.busy"
          >
            <option v-for="v in info?.embeddings" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="Color source" /><select
            aria-label="Color source"
            v-model="colorSource"
          >
            <option value="annotation">列标签</option>
            <option value="feature">Feature</option>
            <option value="none">无</option>
          </select></label
        ><label v-if="colorSource !== 'none'"
          ><FieldLabel name="Search" /><input
            aria-label="Search"
            v-model="search"
            placeholder="筛选列标签 / feature / m/z" /></label
        ><template v-if="colorSource === 'feature'"
          ><label
            ><FieldLabel name="Feature order" /><select aria-label="Feature order" v-model="sort">
              <option v-for="v in ['mean', 'total', 'median', 'detection', 'mz', 'name']" :key="v">
                {{ v }}
              </option>
            </select></label
          ><label
            ><FieldLabel name="Descending" /><select aria-label="Descending" v-model="descending">
              <option :value="true">降序</option>
              <option :value="false">升序</option>
            </select></label
          ></template
        ><label v-if="colorSource !== 'none'"
          ><FieldLabel name="Color" /><select v-model="color" aria-label="Color">
            <option value="">无</option>
            <option v-if="color && !colors.some((c) => c.value === color)" :value="color">
              {{ color }}
            </option>
            <option v-for="v in colors" :key="v.value" :value="v.value">{{ v.label }}</option>
          </select></label
        >
      </div>
      <div class="actions">
        <button v-if="search" @click="search = ''">清除筛选</button
        ><template v-if="colorSource === 'feature'"
          ><span
            >{{ featureOffset + 1 }}–{{ Math.min(featureOffset + 200, featureTotal) }} /
            {{ featureTotal }} 特征</span
          ><button :disabled="featureOffset === 0" @click="pageFeatures(-200)">上一页特征</button
          ><button :disabled="featureOffset + 200 >= featureTotal" @click="pageFeatures(200)">
            下一页特征
          </button></template
        ><button class="preview" :disabled="store.busy || !embedding" @click="draw('embedding')">
          更新嵌入图
        </button>
      </div>
      <PlotView
        v-if="figures.embedding && tab === 'embedding'"
        :figure="figures.embedding"
        :legend="legend"
        :name="embedding"
        view-key="analysis.embedding_plot"
      />
    </div>
    <div v-show="tab === 'differential' || tab === 'network'" class="card">
      <h2>比较输入</h2>
      <div class="field-grid">
        <label
          ><FieldLabel name="group_key" /><select
            aria-label="group_key"
            v-model="diff.group_key"
            :disabled="store.busy"
          >
            <option v-for="v in observed" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="group_a（fold change 分子）" /><select
            aria-label="group_a（fold change 分子）"
            v-model="diff.group_a"
            :disabled="store.busy"
          >
            <option v-for="v in groups" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="group_b" /><select
            aria-label="group_b"
            v-model="diff.group_b"
            :disabled="store.busy"
          >
            <option v-for="v in groups" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="layer" /><select
            aria-label="layer"
            v-model="diff.layer"
            :disabled="store.busy"
          >
            <option :value="null">当前 X</option>
            <option v-for="v in info?.layers" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="differential_method" /><select
            aria-label="differential_method"
            v-model="diff.method"
            :disabled="store.busy"
          >
            <option>mannwhitney</option>
            <option>welch</option>
          </select></label
        >
      </div>
      <p class="page-note">
        细胞数不等于生物重复。细胞级差异用于探索，来源层面推断须先按重复聚合；精确质量注释只是候选。
      </p>
    </div>
    <div v-show="tab === 'differential'" class="card">
      <h2>全特征差异与 Marker</h2>
      <div class="actions">
        <button
          class="primary"
          :disabled="store.busy || !diff.group_a || !diff.group_b"
          @click="execute('differential', { ...diff })"
        >
          比较全部特征</button
        ><button
          class="primary"
          :disabled="store.busy || !diff.group_key"
          @click="
            execute('markers', {
              group_key: diff.group_key,
              method: diff.method,
              layer: diff.layer,
            })
          "
        >
          计算全部簇 Marker</button
        ><button
          class="preview"
          v-if="has('differential')"
          :disabled="store.busy"
          @click="loadResult('differential')"
        >
          读取差异报告</button
        ><button
          class="preview"
          v-if="has('markers')"
          :disabled="store.busy"
          @click="loadResult('markers')"
        >
          读取 Marker 报告
        </button>
      </div>
      <p class="muted">
        差异检验对全部特征做 BH-FDR。Marker 为每簇对其余已标记细胞，每个比较内做 BH-FDR。
      </p>
      <template v-if="has('differential')"
        ><div class="field-grid">
          <label
            ><FieldLabel name="FDR threshold" /><input
              aria-label="FDR threshold"
              v-model.number="volcano.fdr"
              type="number"
              min="0"
              max="1"
              step="any" /></label
          ><label
            ><FieldLabel name="abs(log2FC)" /><input
              aria-label="abs(log2FC)"
              v-model.number="volcano.fold_change"
              type="number"
              min="0"
              step="any" /></label
          ><label
            ><FieldLabel name="Label count" /><input
              aria-label="Label count"
              v-model.number="volcano.labels"
              type="number"
              min="0"
              max="100" /></label
          ><label
            ><FieldLabel name="Label order" /><select
              aria-label="Label order"
              v-model="volcano.order"
            >
              <option>fdr</option>
              <option>effect</option>
              <option>p_value</option>
              <option>intensity</option>
            </select></label
          >
        </div>
        <button class="preview" :disabled="store.busy" @click="draw('volcano')">更新火山图</button
        ><PlotView
          v-if="figures.volcano && tab === 'differential'"
          :figure="figures.volcano"
          :legend="legend"
          name="volcano"
          @select="toggleFeature"
        /><label class="field"
          ><FieldLabel name="小提琴特征（最多 12 个；也可点击火山图）" /><select
            aria-label="小提琴特征（最多 12 个；也可点击火山图）"
            v-model="selectedFeatures"
            multiple
            size="6"
          >
            <option v-for="v in featureOptions" :key="v.value" :value="v.value">
              {{ v.label }}
            </option>
          </select></label
        >
        <div class="check-list">
          <label
            ><input
              v-model="hideZero"
              type="checkbox"
              aria-label="仅显示时隐藏零值" />仅显示时隐藏零值
            <HelpTip
              label="隐藏零值"
              text="只从小提琴图显示中排除零值，不修改矩阵，也不重新计算检验或 FDR。"
          /></label>
        </div>
        <button
          class="preview"
          :disabled="store.busy || !selectedFeatures.length"
          @click="draw('violin')"
        >
          更新小提琴图</button
        ><PlotView
          v-if="figures.violin && tab === 'differential'"
          :figure="figures.violin"
          :legend="legend"
          name="violin"
        />
        <p class="muted">特征选择和隐藏零值不重新检验，两图共享同一份全特征 FDR。</p></template
      ><template v-for="name in ['differential', 'markers']" :key="name"
        ><h3 v-if="tables[name]">{{ name }}</h3>
        <DataTableView v-if="tables[name]" :table="tables[name]!"
      /></template>
    </div>
    <div v-show="tab === 'network'" class="card">
      <h2>特征相关网络</h2>
      <div class="field-grid">
        <label
          ><FieldLabel name="network_method" /><select
            aria-label="network_method"
            v-model="network.method"
            :disabled="store.busy"
          >
            <option>pearson</option>
            <option>spearman</option>
            <option>kendall</option>
          </select></label
        ><label
          ><FieldLabel name="network_threshold" /><input
            aria-label="network_threshold"
            v-model.number="network.min_abs_correlation"
            type="number"
            min="0"
            max="1"
            step="any"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="network_top_features" /><input
            aria-label="network_top_features"
            v-model.number="network.top_features"
            type="number"
            min="1"
            max="1000"
            :disabled="store.busy"
        /></label>
      </div>
      <p class="muted">按方差筛选特征；相关不代表因果，也不是轨迹分析。</p>
      <div class="actions">
        <button
          class="primary"
          :disabled="store.busy"
          @click="execute('network', { ...network, layer: diff.layer })"
        >
          计算相关网络</button
        ><button
          class="preview"
          v-if="has('network')"
          :disabled="store.busy"
          @click="loadWithPlot('network', 'network_plot')"
        >
          读取相关网络
        </button>
      </div>
      <PlotView
        v-if="figures.network_plot && tab === 'network'"
        :figure="figures.network_plot"
        :legend="legend"
        name="network"
      /><DataTableView v-if="tables.network" :table="tables.network" />
    </div>
    <div v-show="tab === 'supervised'" class="card">
      <h2>监督学习与模型诊断</h2>
      <p class="page-note">
        训练、测试及 CV
        折均须包含全部类别。分组划分不能补救提前在全数据上插补或选特征造成的泄漏；反复调参后的
        holdout 不再是独立测试。
      </p>
      <div class="field-grid">
        <label
          ><FieldLabel name="label_key" /><select
            aria-label="label_key"
            v-model="train.label_key"
            :disabled="store.busy"
          >
            <option v-for="v in observed" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="验证方式" /><select
            aria-label="验证方式"
            v-model="validation"
            :disabled="store.busy"
          >
            <option value="grouped">按独立来源分组验证</option>
            <option value="cell">仅细胞级探索（可能泄漏）</option>
          </select></label
        ><label v-if="validation === 'grouped'"
          ><FieldLabel name="group_key" help-key="validation_group" /><select
            aria-label="group_key"
            v-model="train.group_key"
            :disabled="store.busy"
          >
            <option :value="null" disabled>选择独立样本 / 来源列</option>
            <option v-for="v in observed" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="layer" /><select
            aria-label="layer"
            v-model="train.layer"
            :disabled="store.busy"
          >
            <option :value="null">当前 X</option>
            <option v-for="v in info?.layers" :key="v">{{ v }}</option>
          </select></label
        ><label
          ><FieldLabel name="model" /><select
            aria-label="model"
            v-model="train.model"
            :disabled="store.busy"
          >
            <option v-for="v in ['logistic', 'lda', 'plsda', 'random_forest']" :key="v">
              {{ v }}
            </option>
          </select></label
        ><label v-if="train.model === 'lda'"
          ><FieldLabel name="LDA solver" /><select
            aria-label="LDA solver"
            v-model="ldaSolver"
            :disabled="store.busy"
          >
            <option>svd</option>
            <option>lsqr</option>
            <option>eigen</option>
          </select></label
        ><label
          ><FieldLabel name="cv" /><input
            aria-label="cv"
            v-model.number="train.cv"
            type="number"
            min="2"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="test_size" /><input
            aria-label="test_size"
            v-model.number="train.test_size"
            type="number"
            min="0.01"
            max="0.99"
            step="any"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="calibration_bins" /><input
            aria-label="calibration_bins"
            v-model.number="train.calibration_bins"
            type="number"
            min="2"
            :disabled="store.busy"
        /></label>
      </div>
      <div class="check-list">
        <label
          ><input
            v-model="train.smote"
            type="checkbox"
            aria-label="训练折内 SMOTE"
            :disabled="store.busy" />训练折内 SMOTE
          <HelpTip
            label="SMOTE"
            text="仅在每个训练折内部生成合成少数类细胞，测试集保持不变。少数类样本数须满足近邻条件，不能增加独立生物重复数。"
        /></label>
      </div>
      <div class="actions">
        <button
          class="primary"
          :disabled="
            store.busy || !train.label_key || (validation === 'grouped' && !train.group_key)
          "
          @click="trainModel"
        >
          训练并验证</button
        ><button
          class="preview"
          v-if="has('supervised')"
          :disabled="store.busy"
          @click="loadResult('supervised')"
        >
          读取监督诊断
        </button>
      </div>
      <pre v-if="modelReport" class="code-block">{{ JSON.stringify(modelReport, null, 2) }}</pre>
      <template v-for="kind in ['roc', 'pr', 'calibration']" :key="kind"
        ><button
          class="preview"
          v-if="has('supervised') && !figures[kind]"
          :disabled="store.busy"
          @click="draw(kind)"
        >
          显示 {{ kind }}</button
        ><PlotView
          v-if="figures[kind] && tab === 'supervised'"
          :figure="figures[kind]!"
          :legend="legend"
          :name="kind"
      /></template>
      <div class="field-grid">
        <label
          ><FieldLabel name="latent_key" /><input
            aria-label="latent_key"
            v-model="latentKey"
            :disabled="store.busy"
        /></label>
      </div>
      <button
        class="save"
        :disabled="store.busy || !info?.latent_supported"
        @click="execute('save_latent', { key: latentKey })"
      >
        保存潜变量和 train/test 标识
      </button>
      <p class="muted">lsqr 可做分类但不支持潜变量。项目重载仅保留只读报告，不保存可执行模型。</p>
      <h3>SHAP 特征解释</h3>
      <p class="muted">
        训练集背景解释测试集；绝对贡献跨样本和类别取平均，不表示效应方向或因果。图显示前 30
        项，下载包含全部。
      </p>
      <div class="field-grid">
        <label
          ><FieldLabel name="shap_background" /><input
            aria-label="shap_background"
            v-model.number="shap.max_background"
            type="number"
            min="1"
            max="1000"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="shap_samples" /><input
            aria-label="shap_samples"
            v-model.number="shap.max_samples"
            type="number"
            min="1"
            max="1000"
            :disabled="store.busy"
        /></label>
      </div>
      <div class="actions">
        <button
          class="primary"
          :disabled="store.busy || !info?.live_results.includes('supervised')"
          @click="execute('explain_shap', { ...shap, seed: reduction.random_state })"
        >
          解释当前模型（SHAP）</button
        ><button
          class="preview"
          v-if="has('shap')"
          :disabled="store.busy"
          @click="loadWithPlot('shap', 'shap_plot')"
        >
          读取 SHAP
        </button>
      </div>
      <PlotView
        v-if="figures.shap_plot && tab === 'supervised'"
        :figure="figures.shap_plot"
        :legend="legend"
        name="shap"
      /><DataTableView v-if="tables.shap" :table="tables.shap" />
    </div>
  </section>
  <div v-else class="card empty-state">
    <h1>尚未建立当前数据集</h1>
    <RouterLink to="/extraction">前往提取审核 →</RouterLink>
  </div>
</template>
