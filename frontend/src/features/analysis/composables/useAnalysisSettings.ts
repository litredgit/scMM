import { ref, reactive, computed } from 'vue'

export function useAnalysisSettings() {
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
      train: { ...train },
      shap: { ...shap },
      volcano: { ...volcano },
    }
  }
  function resetSettings() {
    for (const [key, target] of Object.entries({
      projection,
      reduction,
      cluster,
      diff,
      network,
      train,
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
    projection: { ...projection },
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
      train,
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
    projection,
    reduction,
    usePca,
    cluster,
    diff,
    network,
    train,
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
