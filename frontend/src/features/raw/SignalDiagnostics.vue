<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { restoringViews, useViewState } from '../../api/viewState'
import { useWorkspace } from '../../stores/workspace'
import { useReadScope } from '../../api/readScope'
import type { Figure, DataTable } from '../../api/types'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
const props = defineProps<{ sample: string; opened: string }>()
const store = useWorkspace()
const initialOptions = {
  signal: '',
  baseline: '',
  window: null as number | null,
  references: '',
  ppm: 10,
  ms_level: 1,
  rt_min: '',
  rt_max: '',
  lam: 0.5,
  tau: 2,
  sigma_min: 0.001,
  max_iter: 50,
  rank_tol: 0.000001,
  rank_max_iter: 100,
}
const options = ref({ ...initialOptions })
const result = ref<{ figure: Figure; table: DataTable }>()
const identity = computed(() =>
  JSON.stringify([store.current?.workspace_id, store.project?.path, props.sample, props.opened]),
)
let savedRequest: { identity: string; draft: string } | undefined
const savedScope = useReadScope(
  () => identity.value,
  () => {
    if (
      !result.value &&
      savedRequest?.identity === identity.value &&
      savedRequest?.draft === JSON.stringify(options.value)
    )
      void loadSaved()
  },
)
let generation = 0
let hydrating = false
watch(
  () => store.project?.path,
  () => {
    generation++
    if (!restoringViews) {
      options.value = { ...initialOptions }
      result.value = undefined
    }
  },
)
watch(identity, () => {
  generation++
  if (!restoringViews && !hydrating) result.value = undefined
})
watch(
  options,
  () => {
    generation++
    if (!restoringViews && !hydrating) result.value = undefined
  },
  { deep: true },
)
const ready = computed(
  () =>
    props.sample &&
    props.opened === props.sample &&
    options.value.signal &&
    options.value.baseline &&
    (options.value.baseline !== 'median' ||
      (Number.isInteger(options.value.window) && Number(options.value.window) >= 3)),
)
async function diagnose() {
  const capture = identity.value,
    token = ++generation
  const v = options.value
  const body = {
    sample_id: props.sample,
    signal: v.signal,
    baseline: v.baseline,
    window: v.baseline === 'median' ? v.window : null,
    references:
      v.signal === 'eic'
        ? v.references
            .split(/[,，\s]+/)
            .filter(Boolean)
            .map(Number)
        : [],
    ppm: v.ppm,
    ms_level: v.ms_level,
    rt_range: v.rt_min === '' && v.rt_max === '' ? null : [Number(v.rt_min), Number(v.rt_max)],
    lam: v.lam,
    tau: v.tau,
    sigma_min: v.sigma_min,
    max_iter: v.max_iter,
    rank_tol: v.rank_tol,
    rank_max_iter: v.rank_max_iter,
  }
  if ((v.rt_min === '') !== (v.rt_max === '')) {
    store.error = '请同时填写诊断 RT 起点和终点。'
    return
  }
  const value = await store.command<{ figure: Figure; table: DataTable }>('/raw/diagnostic', body)
  if (value && capture === identity.value && token === generation) result.value = value
}
async function loadSaved() {
  if (!store.project || !props.sample || restoringViews) return
  savedRequest = { identity: identity.value, draft: JSON.stringify(options.value) }
  const capture = identity.value,
    token = generation
  const ticket = savedScope.begin()
  const accept = () => ticket() && capture === identity.value && token === generation
  const saved = await store.read<{
    figure: Figure
    table: DataTable
    request: Record<string, unknown>
  }>(`/raw/diagnostic?sample_id=${encodeURIComponent(props.sample)}`, undefined, accept)
  if (!saved || !accept()) return
  const v = saved.request
  hydrating = true
  try {
    options.value = {
      ...initialOptions,
      ...v,
      references: (v.references as number[]).join(','),
      rt_min: (v.rt_range as number[] | null)?.[0]?.toString() ?? '',
      rt_max: (v.rt_range as number[] | null)?.[1]?.toString() ?? '',
    } as typeof initialOptions
    await nextTick()
    if (ticket() && capture === identity.value) result.value = saved
  } finally {
    hydrating = false
  }
}
watch(identity, () => void loadSaved(), { immediate: true })
useViewState('rawDiagnostic', { options, result })
</script>
<template>
  <details class="card">
    <summary>独立原始信号诊断</summary>
    <p class="page-note">
      明确选择信号和基线后，对照峰重构、秩一近似、残差及逐通道噪声。本工具仅诊断，不应用到提取。RT
      以秒筛选，计算保留扫描顺序；中位窗口按扫描数计算。单通道的秩一近似不提供多通道结构证据。
    </p>
    <div class="field-grid">
      <label
        >诊断信号<select v-model="options.signal" aria-label="诊断信号" :disabled="store.busy">
          <option value="" disabled>请选择</option>
          <option value="tic">TIC</option>
          <option value="eic">指定离子的 EIC</option>
        </select></label
      >
      <label
        >诊断基线<select v-model="options.baseline" aria-label="诊断基线" :disabled="store.busy">
          <option value="" disabled>请选择</option>
          <option value="zero">零基线</option>
          <option value="median">逐通道扫描中位基线</option>
        </select></label
      >
      <label
        v-if="options.baseline === 'median'"
        title="window：3–1001 的奇数，且不超过选中扫描数。"
        >基线窗口（扫描数）<input
          v-model.number="options.window"
          aria-label="诊断基线窗口"
          type="number"
          min="3"
          max="1001"
          :disabled="store.busy"
      /></label>
      <template v-if="options.signal === 'eic'"
        ><label
          >参考离子（m/z，1–8 个）<input
            v-model="options.references"
            aria-label="诊断参考离子"
            :disabled="store.busy" /></label
        ><label
          >离子容差（ppm）<input
            v-model.number="options.ppm"
            aria-label="诊断 ppm"
            type="number"
            step="any"
            :disabled="store.busy" /></label
      ></template>
      <label
        >MS 级别<input
          v-model.number="options.ms_level"
          aria-label="诊断 MS 级别"
          type="number"
          min="1"
          :disabled="store.busy"
      /></label>
      <label
        >诊断 RT 起点（秒，留空全部）<input
          v-model="options.rt_min"
          aria-label="诊断 RT 起点"
          type="number"
          step="any"
          :disabled="store.busy"
      /></label>
      <label
        >诊断 RT 终点（秒）<input
          v-model="options.rt_max"
          aria-label="诊断 RT 终点"
          type="number"
          step="any"
          :disabled="store.busy"
      /></label>
    </div>
    <details>
      <summary>重构参数</summary>
      <div class="field-grid">
        <label title="lam：现有 peak_recon 的稀疏正则项，非负。"
          >稀疏系数<input
            v-model.number="options.lam"
            aria-label="诊断 lam"
            type="number"
            min="0"
            step="any"
            :disabled="store.busy"
        /></label>
        <label title="tau：现有 peak_recon 的正峰软阈值系数，非负。"
          >软阈值系数<input
            v-model.number="options.tau"
            aria-label="诊断 tau"
            type="number"
            min="0"
            step="any"
            :disabled="store.busy"
        /></label>
        <label title="sigma_min：逐通道估计噪声下限，单位与强度一致，须为正。"
          >噪声下限<input
            v-model.number="options.sigma_min"
            aria-label="诊断 sigma_min"
            type="number"
            min="0"
            step="any"
            :disabled="store.busy"
        /></label>
        <label title="max_iter：峰重构迭代上限，1–1000。"
          >峰重构最大迭代<input
            v-model.number="options.max_iter"
            type="number"
            min="1"
            max="1000"
            :disabled="store.busy"
        /></label>
        <label title="rank_tol：秩一交替迭代的向量变化绝对容差，正数。"
          >秩一收敛容差<input
            v-model.number="options.rank_tol"
            type="number"
            min="0"
            step="any"
            :disabled="store.busy"
        /></label>
        <label title="rank_max_iter：秩一近似迭代上限，1–1000。"
          >秩一最大迭代<input
            v-model.number="options.rank_max_iter"
            type="number"
            min="1"
            max="1000"
            :disabled="store.busy"
        /></label>
      </div>
    </details>
    <button class="preview" :disabled="store.busy || !ready" @click="diagnose">运行独立诊断</button>
    <p class="muted">
      迭代噪声估计与残差标准差不同，不作为提取
      SNR、空白对照或置信区间。秩一近似不保证全局最优。完整输入、基线、重构、残差与噪声表随图下载，表格仅预览前
      200 行。
    </p>
    <PlotView v-if="result" :figure="result.figure" name="raw-signal-diagnostic" />
    <DataTableView v-if="result" :table="result.table" />
  </details>
</template>
