import { ref, reactive, computed } from 'vue'
import type { Scope } from '../components/PlotScope.vue'

export function useAnalysisSettings() {
  const plotScope = ref<Scope>({
    group_key: 'group',
    groups: null,
    sample_key: 'sample',
    samples: null,
  })
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
  const projection = reactive({ x: 1, y: 2, z: 3, threeD: false })
  const usePca = ref(true)
  const cluster = reactive({
    method: 'kmeans',
    key: 'clusters',
    n_clusters: 3,
    use_rep: 'X',
    n_neighbors: 15,
    random_state: 42,
    eps: 0.5,
    min_samples: 5,
    resolution: 1,
    n_init: 10,
    max_iter: 300,
    tol: 0.0001,
    linkage: 'ward',
    metric: 'euclidean',
    n_iterations: 2,
    threshold: 0.0000001,
    max_level: null as number | null,
  })
  const diff = reactive({
    group_key: '',
    group_a: '',
    group_b: '',
    method: 'mannwhitney',
    layer: null as string | null,
  })
  const timeAnalysis = reactive({
    mode: 'palantir',
    key: 'palantir_a',
    root_cell_id: '',
    input_representation: '',
    terminal_cell_ids: '',
    layer: null as string | null,
    n_diff_components: 10,
    knn: 30,
    num_waypoints: 500,
    scale_components: true,
    max_iterations: 25,
    seed: 42,
    use_early_cell_as_start: true,
    coordinate_key: '',
    time_key: '',
    time_kind: '',
    unit: '',
    branch_probability_key: null as string | null,
    window_size: 100,
    step_size: 50,
    min_cells_per_window: 5,
    selected_result: '',
    plot_coordinate_key: '',
  })
  const stability = reactive({
    source_key: '',
    feature: '',
    time_kind: '',
    time_key: null as string | null,
    bins: 10,
    layer: null as string | null,
  })
  const featureEmbedding = reactive({
    features: [] as string[],
    layer: null as string | null,
    metric: 'pearson',
    name_key: null as string | null,
    class_key: null as string | null,
    n_neighbors: null as number | null,
    min_dist: 0.1,
    random_state: 42,
  })
  const scatter = reactive({
    feature_a: '',
    feature_b: '',
    layer: null as string | null,
    color_key: null as string | null,
    regression: true,
  })
  const network = reactive({
    method: 'pearson',
    min_abs_correlation: 0.7,
    top_features: 50,
    layer: null as string | null,
  })
  const train = reactive({
    random_state: 42,
    label_key: '',
    group_key: null as string | null,
    layer: null as string | null,
    model: 'logistic',
    cv: 5,
    test_size: 0.2,
    calibration_bins: 10,
    smote: false,
  })
  const logistic = reactive({
    C: 1,
    tol: 0.0001,
    max_iter: 5000,
    solver: 'lbfgs',
    penalty: 'l2' as string | null,
    class_weight: 'balanced' as string | null,
    fit_intercept: true,
    l1_ratio: null as number | null,
  })
  const lda = reactive({
    shrinkage: '' as string | number,
    n_components: null as number | null,
    tol: 0.0001,
    store_covariance: false,
  })
  const plsda = reactive({ n_components: 2, max_iter: 500 })
  const forest = reactive({
    n_estimators: 500,
    max_depth: null as number | null,
    min_samples_split: '2',
    min_samples_leaf: '1',
    max_features: 'sqrt',
    bootstrap: true,
    class_weight: 'balanced' as string | null,
    criterion: 'gini',
    max_samples: '',
  })
  const shapView = reactive({ class_index: 0, cell_index: 0, feature: '', top: 20 })
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
  const legend = ref('right')

  const initial = JSON.parse(JSON.stringify(settingsSnapshot()))
  function settingsSnapshot() {
    return {
      projection: { ...projection },
      reduction: { ...reduction },
      cluster: { ...cluster },
      diff: { ...diff },
      network: { ...network },
      scatter: { ...scatter },
      featureEmbedding: { ...featureEmbedding },
      stability: { ...stability },
      timeAnalysis: { ...timeAnalysis },
      train: { ...train },
      logistic: { ...logistic },
      lda: { ...lda },
      plsda: { ...plsda },
      forest: { ...forest },
      shapView: { ...shapView },
      shap: { ...shap },
      volcano: { ...volcano },
    }
  }
  function resetSettings() {
    plotScope.value = { group_key: 'group', groups: null, sample_key: 'sample', samples: null }
    for (const [key, target] of Object.entries({
      projection,
      reduction,
      cluster,
      diff,
      network,
      scatter,
      featureEmbedding,
      stability,
      timeAnalysis,
      train,
      logistic,
      lda,
      plsda,
      forest,
      shapView,
      shap,
      volcano,
    }))
      Object.assign(target, initial[key])
    usePca.value = true
    ldaSolver.value = 'svd'
    validation.value = 'grouped'
    latentKey.value = 'X_latent'
    embedding.value = ''
    colorSource.value = 'annotation'
    color.value = ''
    search.value = ''
    sort.value = 'mean'
    descending.value = true
    selectedFeatures.value = []
    hideZero.value = false
    legend.value = 'right'
    featureOptions.value = []
    featureTotal.value = 0
    featureOffset.value = 0
  }
  const settings = computed(() => ({
    plotScope: { ...plotScope.value },
    projection: { ...projection },
    reduction: { ...reduction },
    usePca: usePca.value,
    cluster: { ...cluster },
    diff: { ...diff },
    network: { ...network },
    scatter: { ...scatter },
    featureEmbedding: { ...featureEmbedding },
    stability: { ...stability },
    timeAnalysis: { ...timeAnalysis },
    train: { ...train },
    logistic: { ...logistic },
    lda: { ...lda },
    plsda: { ...plsda },
    forest: { ...forest },
    shapView: { ...shapView },
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
  function restoreSettings(saved: Record<string, unknown>, defaults: Record<string, unknown>) {
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
    for (const [key, target] of Object.entries({
      projection,
      reduction,
      cluster,
      diff,
      network,
      scatter,
      featureEmbedding,
      stability,
      timeAnalysis,
      train,
      logistic,
      lda,
      plsda,
      forest,
      shapView,
      shap,
      volcano,
    })) {
      if (saved[key] && typeof saved[key] === 'object' && !Array.isArray(saved[key])) {
        const source = saved[key] as Record<string, unknown>
        Object.assign(
          target,
          Object.fromEntries(
            Object.keys(target)
              .filter((name) => Object.hasOwn(source, name))
              .map((name) => [name, source[name]]),
          ),
        )
      }
    }
    if (saved.plotScope && typeof saved.plotScope === 'object') {
      const scope = saved.plotScope as Scope
      if (
        typeof scope.group_key === 'string' &&
        typeof scope.sample_key === 'string' &&
        [scope.groups, scope.samples].every(
          (v) => v === null || (Array.isArray(v) && v.every((item) => typeof item === 'string')),
        )
      )
        plotScope.value = { ...scope }
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
    // Old projects borrowed the reduction seed and differential layer.
    if (
      !saved.train ||
      typeof saved.train !== 'object' ||
      !Object.hasOwn(saved.train, 'random_state')
    )
      train.random_state = reduction.random_state
    if (
      !saved.network ||
      typeof saved.network !== 'object' ||
      !Object.hasOwn(saved.network, 'layer')
    )
      network.layer = diff.layer
  }
  return {
    plotScope,
    projection,
    reduction,
    usePca,
    cluster,
    diff,
    network,
    scatter,
    featureEmbedding,
    stability,
    timeAnalysis,
    train,
    logistic,
    lda,
    plsda,
    forest,
    shapView,
    ldaSolver,
    validation,
    latentKey,
    shap,
    embedding,
    colorSource,
    color,
    search,
    sort,
    descending,
    featureOptions,
    featureTotal,
    featureOffset,
    selectedFeatures,
    hideZero,
    volcano,
    legend,
    settings,
    resetSettings,
    restoreSettings,
  }
}
