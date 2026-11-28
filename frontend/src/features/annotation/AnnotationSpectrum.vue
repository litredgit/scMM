<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import PlotView from '../../components/PlotView.vue'
import { request } from '../../api/client'
import { useReadScope } from '../../api/readScope'
import { useViewState } from '../../api/viewState'
import { useWorkspace } from '../../stores/workspace'
import type { AnnotationSource, Figure } from '../../api/types'
import { ms2Label, type AnnotationSpectrum } from '../preprocess/lipids'
import type { ReviewTarget } from './useAnnotationSource'

type Peak = Pick<AnnotationSpectrum['peaks'][number], 'feature_id' | 'mz' | 'intensity'>
type OverlayPeak = Omit<AnnotationSpectrum['peaks'][number], 'mz' | 'intensity'>
type Axis = Pick<
  AnnotationSpectrum,
  | 'spectrum_kind'
  | 'intensity_label'
  | 'intensity_missing'
  | 'intensity_source'
  | 'relative_intensity_allowed'
> & {
  peaks: Peak[]
  source_identity: string
}
type Overlay = Pick<
  AnnotationSpectrum,
  'version' | 'review_revision' | 'relations' | 'review_conflicts'
> & {
  peaks: OverlayPeak[]
  source_identity: string
  grouping: string
  sample: string
  catalog_revision?: number
  external_names?: Record<string, string>
}
const props = defineProps<{
  source: AnnotationSource
  version: string
  featureId: string
  samples: string[]
  grouping: string
  resultIds?: string[]
  group?: ReviewTarget
}>()
const emit = defineEmits<{
  select: [id: string]
  review: [id: string, state: string]
}>()
const store = useWorkspace()
const sample = ref('')
const labelMode = ref<'both' | 'name' | 'mz'>('both')
const showMS2 = ref(true)
const full = ref(false)
const viewScope = computed(() => `${store.current?.workspace_id}:${store.project?.path}`)
let userViewScope: string | undefined
const savedFull = computed({
  get: () => full.value,
  set: (value: boolean) => {
    if (userViewScope !== viewScope.value) full.value = value
  },
})
function toggleFull() {
  userViewScope = viewScope.value
  full.value = !full.value
}
const query = ref('')
const reviewFilter = ref('')
const tabs = [
  ['candidates', '候选'],
  ['relations', '峰关系'],
  ['evidence', '证据'],
  ['reviews', '审核记录'],
] as const
const tab = ref<(typeof tabs)[number][0]>('candidates')
const axis = shallowRef<Axis>()
const overlay = shallowRef<Overlay>()
const axisError = ref('')
const overlayError = ref('')
const axisLoading = ref(false)
const peakPage = ref(0)
const overlaps = ref<Peak[]>([])
const pageSize = 100
const axisKey = () => [
  store.current?.workspace_id,
  store.project?.path,
  props.source.identity,
  sample.value,
]
const overlayKey = () => [...axisKey(), props.version, props.grouping, store.current?.revision]
const axisReads = useReadScope(axisKey, () => void loadAxis())
const overlayReads = useReadScope(overlayKey, () => void loadOverlay())

async function loadAxis() {
  const current = store.current
  if (!current) return
  const accept = axisReads.begin()
  axisLoading.value = true
  axisError.value = ''
  try {
    const response = await request<Axis>('/workspace/lipids/spectrum/axis', {
      method: 'POST',
      workspace: current.workspace_id,
      body: { revision: current.revision, source: props.source.id, sample: sample.value },
    })
    if (accept() && response.source_identity === props.source.identity) axis.value = response
  } catch (cause) {
    if (accept()) axisError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (accept()) axisLoading.value = false
  }
}
async function loadOverlay() {
  const current = store.current
  if (!current) return
  const accept = overlayReads.begin()
  overlayError.value = ''
  try {
    const response = await request<Overlay>('/workspace/lipids/spectrum/overlay', {
      method: 'POST',
      workspace: current.workspace_id,
      body: {
        revision: current.revision,
        source: props.source.id,
        version: props.version,
        grouping: props.grouping,
        sample: sample.value,
      },
    })
    if (accept() && response.source_identity === props.source.identity) overlay.value = response
  } catch (cause) {
    if (accept()) overlayError.value = cause instanceof Error ? cause.message : String(cause)
  }
}
watch(
  () => JSON.stringify(axisKey()),
  () => {
    axis.value = undefined
    overlaps.value = []
    void loadAxis()
  },
  { immediate: true },
)
watch(
  () => JSON.stringify(overlayKey()),
  () => void loadOverlay(),
  { immediate: true },
)
watch(
  () => store.current?.revision,
  () => {
    if (!axis.value && axisReads.isActive()) void loadAxis()
  },
)
watch(
  () => props.samples,
  (values) => {
    if (sample.value && values.length && !values.includes(sample.value)) sample.value = ''
  },
)
watch(
  () => props.source.identity,
  () => {
    sample.value = ''
    peakPage.value = 0
  },
  { flush: 'sync' },
)
watch([query, reviewFilter], () => {
  peakPage.value = 0
})

const activeOverlay = computed(() =>
  axis.value &&
  overlay.value?.source_identity === axis.value.source_identity &&
  overlay.value.version === props.version &&
  overlay.value.sample === sample.value &&
  (!props.grouping || overlay.value.grouping === props.grouping)
    ? overlay.value
    : undefined,
)
const peakLabels = computed(
  () => new Map(activeOverlay.value?.peaks.map((peak) => [peak.feature_id, peak])),
)
const peaks = computed(() => axis.value?.peaks ?? [])
const byId = computed(() => new Map(peaks.value.map((peak) => [peak.feature_id, peak])))
const byMass = computed(() => [...peaks.value].sort((a, b) => a.mz - b.mz))
const selected = computed(() => byId.value.get(props.featureId))
const selectedLabel = computed(() => peakLabels.value.get(props.featureId))
const selectedRelations = computed(() => {
  const groups = new Map<string, AnnotationSpectrum['relations']>()
  for (const row of activeOverlay.value?.relations ?? []) {
    if (!selected.value || ![row.source, row.target].includes(props.featureId)) continue
    const id = row.shared_review || row.id
    const rows = groups.get(id) ?? []
    rows.push(row)
    groups.set(id, rows)
  }
  return [...groups].map(([id, rows]) => ({
    ...(rows.find((row) => row.id === id) ?? rows[0]!),
    evidence: rows,
  }))
})
const selectedRoles = computed(() => {
  const roles = new Map<string, 'selected' | 'isotope' | 'adduct' | 'group_member'>()
  if (props.group) {
    for (const id of props.group.members ?? [])
      roles.set(id, id === props.group.quantifier ? 'selected' : 'group_member')
    return roles
  }
  if (!selected.value) return roles
  for (const row of selectedRelations.value) {
    if (row.review !== 'rejected') {
      const id = row.source === props.featureId ? row.target : row.source
      if (row.type === 'isotope' || row.type === 'adduct') roles.set(id, row.type)
    }
  }
  roles.set(props.featureId, 'selected')
  return roles
})
const filtered = computed(() => {
  const text = query.value.trim().toLocaleLowerCase()
  return peaks.value.filter((peak) => {
    const label = peakLabels.value.get(peak.feature_id)
    const matches = [
      peak.feature_id,
      String(peak.mz),
      peak.mz.toFixed(4),
      label?.label,
      ...(label?.candidate_names ?? []),
      activeOverlay.value?.external_names?.[peak.feature_id],
    ].some((value) => value?.toLocaleLowerCase().includes(text))
    return (
      matches &&
      (!reviewFilter.value ||
        (reviewFilter.value === 'ambiguous' && (label?.candidate_count ?? 0) > 1) ||
        (reviewFilter.value === 'reviewed' && label?.reviewed) ||
        (reviewFilter.value === 'pending' && !label?.reviewed))
    )
  })
})
const displayed = computed(() =>
  filtered.value.slice(peakPage.value * pageSize, (peakPage.value + 1) * pageSize),
)
const outside = computed(
  () =>
    selected.value &&
    (!filtered.value.some((peak) => peak.feature_id === props.featureId) ||
      (props.resultIds && !props.resultIds.includes(props.featureId))),
)
watch([filtered, () => props.featureId], () => {
  const index = filtered.value.findIndex((peak) => peak.feature_id === props.featureId)
  if (index >= 0) peakPage.value = Math.floor(index / pageSize)
})
function select(id: string) {
  overlaps.value = []
  emit('select', id)
}
function pointClick(event: { points: { customdata?: unknown }[]; xUnitsPerPixel?: number }) {
  const custom = event.points.find((point) => Array.isArray(point.customdata))?.customdata
  if (!Array.isArray(custom) || custom[3] !== axis.value?.source_identity) return
  const peak = byId.value.get(String(custom[0]))
  if (!peak) return
  const tolerance = Math.abs(event.xUnitsPerPixel ?? 0)
  const hits = byMass.value.filter((item) => Math.abs(item.mz - peak.mz) <= tolerance)
  if (hits.length > 1) overlaps.value = hits
  else select(peak.feature_id)
}
const coverage = (peak: Peak) => {
  const label = peakLabels.value.get(peak.feature_id)
  if (!label) return '未计算候选'
  return label.candidate_count ? `${label.candidate_count} 个候选` : '已查未命中'
}
const colors = {
  selected: '#c0392b',
  isotope: '#2166ac',
  adduct: '#b86814',
  group_member: '#247884',
  unrelated: '#39484d',
}
const roleNames = {
  selected: 'Selected peak',
  isotope: 'Isotope',
  adduct: 'Adduct',
  group_member: 'Group member',
  unrelated: 'Measured features',
}
const escape = (value: string) =>
  value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
const featureCSV = computed(() => {
  const quote = (value: unknown) => '"' + String(value ?? '').replaceAll('"', '""') + '"'
  return [
    'source,source_identity,sample,layer,annotation_version,review_revision,range,feature_id,mz,intensity,annotation,ms2_status',
    ...peaks.value.map((peak) => {
      const label = peakLabels.value.get(peak.feature_id)
      return [
        props.source.id,
        axis.value?.source_identity,
        sample.value,
        axis.value?.intensity_source.layer,
        activeOverlay.value?.version,
        activeOverlay.value?.review_revision,
        'all_source_features',
        peak.feature_id,
        peak.mz,
        peak.intensity,
        label?.label,
        label?.ms2_status,
      ]
        .map(quote)
        .join(',')
    }),
  ].join('\n')
})
const figure = computed<Figure | undefined>(() => {
  const data = axis.value
  if (!data) return
  const traces: Record<string, unknown>[] = []
  const localCenter =
    (props.group?.members?.length ? byId.value.get(props.group.members[0]!) : selected.value) ??
    byMass.value[0]
  const centerMass = localCenter?.mz ?? 0
  const ms = [
    centerMass,
    ...[...selectedRoles.value.keys()].map((id) => byId.value.get(id)?.mz ?? centerMass),
  ]
  const localRange = [Math.min(...ms) - 0.6, Math.max(...ms) + 0.6]
  for (const role of ['unrelated', 'group_member', 'isotope', 'adduct', 'selected'] as const) {
    const items = peaks.value.filter(
      (peak) => (selectedRoles.value.get(peak.feature_id) ?? 'unrelated') === role,
    )
    if (!items.length) continue
    if (!data.intensity_missing)
      traces.push({
        type: 'scattergl',
        mode: 'lines',
        name: roleNames[role],
        showlegend: false,
        x: items.flatMap((p) => [p.mz, p.mz, null]),
        y: items.flatMap((p) => [0, p.intensity, null]),
        line: { color: colors[role], width: role === 'unrelated' ? 1 : 2 },
        hoverinfo: 'skip',
        meta: { spectrum_role: 'observed', annotation_role: role },
      })
    const visibleText = (peak: Peak) => {
      const detail = peakLabels.value.get(peak.feature_id)
      if (role === 'unrelated' && items.length > 100 && !detail?.label) return ''
      if (role === 'unrelated' && full.value && items.length > 100) return ''
      return [
        labelMode.value !== 'mz' ? escape(detail?.label ?? '') : '',
        labelMode.value !== 'name' || !detail?.label ? peak.mz.toFixed(4) : '',
        showMS2.value && detail?.label ? ms2Label(detail.ms2_status) : '',
      ]
        .filter(Boolean)
        .join('<br>')
    }
    traces.push({
      type: items.length > 1500 && !data.intensity_missing ? 'scattergl' : 'scatter',
      mode: 'markers+text',
      name: roleNames[role],
      x: items.map((peak) => peak.mz),
      y: items.map((peak) => peak.intensity ?? 0),
      customdata: items.map((peak) => {
        const detail = peakLabels.value.get(peak.feature_id)
        return [
          peak.feature_id,
          escape(detail?.label || 'Unannotated'),
          ms2Label(detail?.ms2_status),
          data.source_identity,
        ]
      }),
      text: items.map(visibleText),
      marker: {
        color: colors[role],
        size: role === 'selected' ? 9 : 6,
        symbol: data.intensity_missing ? 'line-ns-open' : 'circle',
      },
      hovertemplate:
        'Feature: %{customdata[0]}<br>m/z: %{x}<br>' +
        (data.intensity_missing ? 'Intensity: Not supplied' : 'Intensity: %{y}') +
        '<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>',
      meta: { spectrum_role: 'observed', annotation_role: role },
    })
  }
  return {
    data: traces,
    layout: {
      title: { text: full.value ? 'Full feature spectrum' : 'Local feature spectrum' },
      xaxis: {
        title: { text: 'm/z' },
        showline: true,
        showgrid: false,
        ...(full.value ? {} : { range: localRange }),
      },
      yaxis: {
        title: { text: data.intensity_label },
        showline: true,
        showgrid: false,
        zeroline: false,
        ...(data.intensity_missing
          ? { showticklabels: false, range: [-0.2, 1] }
          : { rangemode: 'tozero' }),
      },
      hovermode: 'closest',
      meta: {
        scmm_spectrum: true,
        spectrum_kind: data.spectrum_kind,
        intensity_missing: data.intensity_missing,
        relative_intensity_allowed: data.relative_intensity_allowed,
        spectrum_context: full.value
          ? 'full'
          : 'local:' + (props.group?.id ?? localCenter?.feature_id ?? ''),
        spectrum_input: JSON.stringify([data.source_identity, sample.value]),
        spectrum_local: !full.value,
        annotation_source: props.source.id,
        annotation_source_identity: data.source_identity,
        intensity_source: data.intensity_source,
        spectrum_data_range: 'all_source_features',
        lipid_version: activeOverlay.value?.version,
        lipid_review_revision: activeOverlay.value?.review_revision,
        annotation_catalog_revision: activeOverlay.value?.catalog_revision,
        annotation_grouping_version: activeOverlay.value?.grouping,
        export_tables: { features: featureCSV.value },
      },
    },
  }
})
const reviewName = (value: string) =>
  ({ accepted: '已确认', rejected: '已否定' })[value] ?? '待审核'
useViewState('annotation_spectrum', {
  sample,
  labelMode,
  showMS2,
  full: savedFull,
  query,
  reviewFilter,
  tab,
})
</script>

<template>
  <section id="annotation-spectrum" class="annotation-spectrum" aria-label="谱图注释与关联峰">
    <div class="actions spectrum-toolbar">
      <slot name="actions" />
      <button class="preview" @click="toggleFull">
        {{ full ? '返回局部谱图' : '查看完整谱图' }}
      </button>
      <label
        >强度样本
        <select
          v-model="sample"
          aria-label="谱图强度样本"
          :disabled="!source.quantitation_available"
        >
          <option value="">全部观测</option>
          <option v-for="value in samples" :key="value" :value="value">{{ value }}</option>
        </select>
      </label>
      <label
        >峰标签
        <select v-model="labelMode" aria-label="峰标签内容">
          <option value="both">注释名称 + m/z</option>
          <option value="name">注释名称</option>
          <option value="mz">m/z</option>
        </select>
      </label>
      <label class="inline-check"><input v-model="showMS2" type="checkbox" />二级状态标签</label>
      <slot name="version" />
    </div>
    <slot name="settings" />
    <div class="spectrum-grid" :class="{ 'full-spectrum': full }">
      <aside class="peak-list" aria-label="峰列表">
        <label class="field"
          >定位峰<input v-model="query" type="search" placeholder="特征 ID、m/z 或名称"
        /></label>
        <label v-if="!full" class="field"
          >审核状态
          <select v-model="reviewFilter">
            <option value="">全部峰</option>
            <option value="ambiguous">有多候选</option>
            <option value="pending">待审核</option>
            <option value="reviewed">已审核</option>
          </select>
        </label>
        <div class="peak-items">
          <button
            v-for="peak in displayed"
            :key="peak.feature_id"
            type="button"
            :aria-pressed="peak.feature_id === featureId"
            @click="select(peak.feature_id)"
          >
            <strong>{{ peak.feature_id }}</strong> <span>{{ peak.mz.toFixed(4) }}</span>
            <small>{{ peakLabels.get(peak.feature_id)?.label || coverage(peak) }}</small>
          </button>
        </div>
        <div v-if="filtered.length > pageSize" class="actions">
          <button :disabled="!peakPage" @click="peakPage--">上一页</button>
          <span>{{ peakPage + 1 }} / {{ Math.ceil(filtered.length / pageSize) }}</span>
          <button :disabled="(peakPage + 1) * pageSize >= filtered.length" @click="peakPage++">
            下一页
          </button>
        </div>
        <p v-if="axis && !filtered.length" class="muted">没有符合筛选的峰。</p>
      </aside>
      <div class="spectrum-chart">
        <div class="peak-summary" aria-live="polite">
          <p v-if="group" class="selected-peak">
            离子组 {{ group.id }} · {{ group.members?.length ?? 0 }} 个测量峰
            <template v-if="group.quantifier"> · 固定代表 {{ group.quantifier }}</template>
          </p>
          <p v-else-if="selected" class="selected-peak">
            选中 {{ selected.feature_id }} · m/z {{ selected.mz }} ·
            {{ selectedLabel?.label || coverage(selected) }}
            <template v-if="selectedLabel?.label">
              · {{ ms2Label(selectedLabel.ms2_status) }}</template
            >
            <template v-if="activeOverlay?.external_names?.[selected.feature_id]">
              · 外部名称 {{ activeOverlay.external_names[selected.feature_id] }}</template
            >
          </p>
          <p v-else>点击图中峰或从列表选择特征。</p>
          <p v-if="outside" class="muted">当前峰在列表筛选范围之外。</p>
          <p v-if="axis?.intensity_missing" class="muted">
            独立特征表没有实测强度，标记仅表示 m/z 位置。
          </p>
          <p v-if="axisError" role="alert">
            {{ axisError }} <button class="preview" @click="loadAxis">重试读取</button>
          </p>
          <p v-else-if="axisLoading && !axis" role="status">正在读取特征谱…</p>
        </div>
        <div v-if="overlaps.length" class="overlap-list">
          <strong>此位置有 {{ overlaps.length }} 个可选峰</strong>
          <button v-for="peak in overlaps" :key="peak.feature_id" @click="select(peak.feature_id)">
            {{ peak.feature_id }} · m/z {{ peak.mz }} · {{ peak.intensity ?? '未提供强度' }}
          </button>
        </div>
        <PlotView
          v-if="figure"
          :figure="figure"
          name="annotation-spectrum"
          legend="hidden"
          @point-click="pointClick"
        />
      </div>
      <aside class="spectrum-review" aria-label="所选对象详情">
        <nav class="review-tabs" aria-label="审核详情">
          <button
            v-for="[id, name] in tabs"
            :key="id"
            type="button"
            :aria-pressed="tab === id"
            @click="tab = id"
          >
            {{ name }}
          </button>
        </nav>
        <p v-if="overlayError" role="alert">
          {{ overlayError }} <button class="preview" @click="loadOverlay">重试</button>
        </p>
        <div v-show="tab === 'candidates'" class="review-pane">
          <slot name="candidates" :peak="selected" :status="selected && coverage(selected)" />
        </div>
        <div v-show="tab === 'relations'" class="review-pane">
          <p v-if="!selectedRelations.length" class="muted">当前峰没有可审核关系。</p>
          <article v-for="row in selectedRelations" :key="row.id" class="relation-item">
            <strong
              >{{
                {
                  isotope: '同位素',
                  adduct: '加合离子',
                  charge: '电荷关系',
                  multimer: '多聚体',
                  neutral_loss: '失水或中性丢失',
                  fragment_form: '源内碎片',
                }[row.type] ?? row.type
              }}
              · {{ reviewName(row.review) }}</strong
            >
            <div class="actions">
              <button class="text-button" @click="select(row.source)">{{ row.source }}</button> →
              <button class="text-button" @click="select(row.target)">{{ row.target }}</button>
            </div>
            <p>
              {{ row.sample || '质量关系'
              }}<template v-if="row.name"> · {{ row.name }} {{ row.adduct }}</template>
            </p>
            <details>
              <summary>关系依据（{{ row.evidence.length }} 条）</summary>
              <dl v-for="item in row.evidence" :key="item.id">
                <dt>{{ item.origin ? '测量归组' : '注释候选计算' }}</dt>
                <dd>
                  {{ item.left_species || item.adduct }} / {{ item.right_species || item.adduct }} ·
                  ppm {{ item.ppm_error ?? '—' }} · {{ item.sample || '完整测量来源' }}
                </dd>
              </dl>
            </details>
            <div class="actions">
              <button
                class="save"
                :disabled="
                  store.busy ||
                  row.review === 'accepted' ||
                  ['neutral_loss', 'fragment_form'].includes(row.type)
                "
                @click="emit('review', row.id, 'accepted')"
              >
                接受关联
              </button>
              <button
                :disabled="store.busy || row.review === 'rejected'"
                @click="emit('review', row.id, 'rejected')"
              >
                否定关联
              </button>
              <button
                :disabled="store.busy || row.review === 'pending'"
                @click="emit('review', row.id, 'pending')"
              >
                恢复待审核
              </button>
            </div>
          </article>
          <slot name="relations" />
        </div>
        <div v-show="tab === 'evidence'" class="review-pane">
          <slot name="evidence" :annotations="selectedLabel?.annotations" />
        </div>
        <div v-show="tab === 'reviews'" class="review-pane">
          <p v-if="activeOverlay?.review_conflicts.length" class="state-note">
            有 {{ activeOverlay.review_conflicts.length }} 项历史冲突待核对。
          </p>
          <slot name="reviews" />
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.annotation-spectrum,
.spectrum-chart,
.spectrum-review {
  min-width: 0;
}
.spectrum-toolbar {
  align-items: end;
  flex-wrap: wrap;
  margin: 0 0 8px;
}
.spectrum-toolbar .inline-check {
  min-height: 36px;
}
.spectrum-toolbar select {
  width: auto;
}
.spectrum-grid {
  display: grid;
  grid-template-columns: minmax(145px, 0.55fr) minmax(0, 2.2fr) minmax(315px, 1.15fr);
  align-items: start;
  gap: 10px;
}
.full-spectrum {
  grid-template-columns: minmax(130px, 0.4fr) minmax(0, 3.2fr) minmax(305px, 1fr);
}
.peak-list,
.spectrum-review {
  border: 1px solid var(--border);
  border-radius: var(--control-radius);
  background: var(--panel-soft);
  padding: 8px;
}
.peak-items,
.review-pane {
  max-height: 475px;
  overflow: auto;
  overscroll-behavior: contain;
}
.peak-items button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  margin-bottom: 3px;
  width: 100%;
  padding: 5px;
  text-align: left;
  font-variant-numeric: tabular-nums;
}
.peak-items strong,
.peak-items small {
  overflow-wrap: anywhere;
}
.peak-items small {
  grid-column: 1 / -1;
}
button[aria-pressed='true'] {
  background: #e4f2f4;
  border-color: var(--teal);
}
.review-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}
.review-tabs button {
  flex: 1;
  padding: 4px;
}
.peak-summary {
  min-height: 40px;
}
.peak-summary p,
.relation-item p {
  margin: 2px 0;
}
.selected-peak {
  overflow-wrap: anywhere;
  border-left: 3px solid #c0392b;
  padding-left: 8px;
}
.relation-item {
  border-bottom: 1px solid var(--border);
  padding: 6px 0;
  overflow-wrap: anywhere;
}
.overlap-list {
  display: grid;
  gap: 3px;
  max-height: 155px;
  padding: 6px;
  border: 1px solid var(--border);
  overflow: auto;
}
</style>
