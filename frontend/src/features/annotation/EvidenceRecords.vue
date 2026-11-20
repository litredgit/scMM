<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspace } from '../../stores/workspace'
import { useReadScope } from '../../api/readScope'
import { saveBlob } from '../../api/workspaceDownload'
import { formatTime } from '../../help/time'
import type { Figure } from '../../api/types'
import PlotView from '../../components/PlotView.vue'
import ProfileReviewResult from './ProfileReviewResult.vue'
import type { ProfileReview } from './profileReview'
import DataTableView from '../../components/DataTable.vue'
import { useAnnotationSource } from './useAnnotationSource'

type Match = {
  feature_id: string
  name: string
  measured_scan: string
  measured_index: number
  library_scan: number
  precursor_mz: number
  library_precursor_mz: number
  matched_fragments: number
  score: number | null
  passes_threshold: boolean
  sample_pool: string
  fragments_json: string
  acquisition_scan_index?: number
  acquisition_isolation_offsets_da?: [number, number] | null
  acquisition_collision_energy?: number | null
  acquisition_polarity?: string | null
}
type EvidenceRecord = {
  id: string
  kind?: string
  rows?: Match[]
  figure?: Figure
  scope?: Record<string, unknown>
  text?: string
  parameters?: Record<string, unknown>
  profile_review?: ProfileReview
}
type Link = {
  id: string
  target: {
    id: string
    kind: 'feature' | 'candidate' | 'ec'
    version: string
    feature_id: string
    source: string
  }
  record_id: string
  row: number | null
  scope: Record<string, unknown>
  decision: string
  passes_threshold: boolean | null
}
type Index = {
  searches: {
    id: string
    created_at: string
    parameters: { sample_pool: string }
    size: number
    current: boolean
  }[]
  external: {
    evidence_id: string
    kind: string
    source: { name?: string }
    scope: Record<string, unknown>
  }[]
  links: Link[]
  tables: Record<string, unknown>[]
}
const props = defineProps<{ newest?: string }>()
const route = useRoute()
const router = useRouter()
const store = useWorkspace()
const { source, sourceId, sources, selectedTarget, selectTarget } = useAnnotationSource()
const index = ref<Index>()
const key = ref('')
const record = ref<EvidenceRecord>()
const rowIndex = ref<number | null>(null)
const preview = ref<Link>()
const reason = ref('')
const memberFeature = ref('')
const showAll = ref(false)
const offset = ref(0)
const prefix = '/analysis/annotation-evidence'
const scopeKey = () => [
  store.current?.workspace_id,
  store.project?.path,
  sourceId.value,
  store.current?.revision,
]
const listReads = useReadScope(scopeKey, () => void reload())
const recordReads = useReadScope(
  () => [store.current?.workspace_id, store.project?.path, key.value],
  () => void readRecord(),
)
async function reload() {
  if (!store.project) return
  const value = await store.read<Index>(
    `${prefix}?source=${encodeURIComponent(sourceId.value)}`,
    undefined,
    listReads.begin(),
  )
  if (!value) return
  index.value = value
}
async function readRecord() {
  if (!key.value) {
    record.value = undefined
    return
  }
  const value = await store.read<EvidenceRecord>(
    `${prefix}/record?key=${encodeURIComponent(key.value)}`,
    undefined,
    recordReads.begin(),
  )
  if (value) record.value = value
}
watch(scopeKey, () => void reload(), { immediate: true })
watch(
  () => store.project?.path,
  () => {
    index.value = undefined
    key.value = ''
    record.value = undefined
    rowIndex.value = null
  },
)
watch(key, () => {
  record.value = undefined
  offset.value = 0
  void readRecord()
})
watch(
  () => props.newest,
  (value) => {
    if (value) {
      rowIndex.value = null
      key.value = value
    }
  },
)
watch(
  () => [route.path, route.query.record, route.query.row],
  () => {
    if (route.path === '/annotation/evidence' && typeof route.query.record === 'string') {
      key.value = route.query.record
      rowIndex.value = typeof route.query.row === 'string' ? Number(route.query.row) : null
    }
  },
  { immediate: true },
)
const target = computed(() => {
  const value = selectedTarget.value
  return value
    ? {
        source: value.source,
        kind: value.kind,
        id: value.id,
        version: value.version ?? '',
        feature_id: value.featureId ?? (value.kind === 'feature' ? value.id : memberFeature.value),
      }
    : undefined
})
watch([target, key, rowIndex], () => {
  preview.value = undefined
})
const links = computed(
  () =>
    index.value?.links.filter(
      (link) =>
        link.record_id === key.value &&
        link.row === rowIndex.value &&
        link.target.id === target.value?.id &&
        link.target.kind === target.value?.kind &&
        (target.value.kind === 'feature' || link.target.version === target.value.version),
    ) ?? [],
)
const selected = computed(() =>
  rowIndex.value == null ? undefined : record.value?.rows?.[rowIndex.value],
)
const displayed = computed(() =>
  (record.value?.rows ?? [])
    .map((row, i) => ({ row, i }))
    .filter(
      ({ row }) =>
        showAll.value || !target.value?.feature_id || target.value.feature_id === row.feature_id,
    ),
)
watch([target, showAll], () => {
  offset.value = 0
})
const currentRecord = computed(() => index.value?.searches.find((row) => row.id === key.value))
const recordLinks = computed(
  () => index.value?.links.filter((link) => link.record_id === key.value) ?? [],
)
async function returnToTarget(link: Link) {
  const destination = sources.value.find((item) => item.id === link.target.source)
  if (!destination) return
  const response = await store.command<Link>(prefix + '/preview', {
    target: {
      source: destination.id,
      kind: link.target.kind,
      id: link.target.id,
      version: link.target.version,
      feature_id: link.target.feature_id,
    },
    record_id: link.record_id,
    row: link.row,
  })
  if (!response || response.id !== link.id) return
  sourceId.value = destination.id
  selectTarget({
    source: destination.id,
    sourceIdentity: destination.identity,
    kind: link.target.kind,
    id: link.target.id,
    featureId: link.target.feature_id,
    version: link.target.version,
  })
  void router.push('/annotation')
}
const canLink = computed(() => {
  const selectedTarget = target.value
  const stored = record.value
  if (!selectedTarget || !key.value || !stored) return false
  if (stored.rows)
    return currentRecord.value?.current && selectedTarget.feature_id === selected.value?.feature_id
  const profile = stored.profile_review
  return (
    !profile ||
    (profile.source === selectedTarget.source &&
      profile.candidates.some(
        (candidate) =>
          candidate.feature_id === selectedTarget.feature_id &&
          (selectedTarget.kind === 'feature' ||
            (selectedTarget.kind === 'candidate' &&
              selectedTarget.id === candidate.candidate_id &&
              selectedTarget.version === profile.version)),
      ))
  )
})
async function association(decision: 'preview' | 'linked' | 'withdrawn') {
  if (!target.value) return
  const body = {
    target: target.value,
    record_id: key.value,
    row: rowIndex.value,
    decision: decision === 'preview' ? 'linked' : decision,
    reason: reason.value,
  }
  const value = await store.command<Link>(
    `${prefix}/${decision === 'preview' ? 'preview' : 'apply'}`,
    body,
  )
  if (value) {
    preview.value = value
    if (decision !== 'preview') await reload()
  }
}
function targetMatch() {
  if (!source.value || !selected.value || !currentRecord.value?.current) return
  selectTarget({
    source: source.value.id,
    sourceIdentity: source.value.identity,
    kind: 'feature',
    id: selected.value.feature_id,
  })
}
function download() {
  if (!record.value) return
  saveBlob(
    new Blob([JSON.stringify(record.value, null, 2)], { type: 'application/json' }),
    `annotation-evidence-${key.value}.json`,
  )
}
type PeakSpectrum = { peaks: [number, number][] }
const fragments = computed<Record<string, unknown>[]>(() =>
  selected.value ? JSON.parse(selected.value.fragments_json) : [],
)
const fragmentPlot = computed<Figure | undefined>(() => {
  const match = selected.value
  const meta = record.value?.figure?.layout.meta as
    { spectra?: { measured: PeakSpectrum[]; library: PeakSpectrum[] } } | undefined
  if (!match || !meta?.spectra) return
  const scan = meta.spectra.measured[match.measured_index]
  const reference = meta.spectra.library[match.library_scan - 1]
  if (!scan || !reference) return
  const spectrum = (peaks: [number, number][], sign: number, name: string, color: string) => {
    const base = Math.max(...peaks.map((row) => row[1]), 1)
    return {
      type: 'scatter',
      mode: 'lines',
      name,
      line: { color, width: 1.3 },
      x: peaks.flatMap(([mz]) => [mz, mz, null]),
      y: peaks.flatMap(([, intensity]) => [0, ((sign * intensity) / base) * 100, null]),
      hovertemplate: 'm/z: %{x}<br>Relative abundance: %{y:.2f}%<extra>%{fullData.name}</extra>',
    }
  }
  return {
    data: [
      spectrum(scan.peaks, 1, 'Measured', '#246e85'),
      spectrum(reference.peaks, -1, 'Reference', '#c16629'),
    ],
    layout: {
      title: { text: 'Measured and reference fragments' },
      xaxis: { title: { text: 'Fragment m/z' } },
      yaxis: { title: { text: 'Relative abundance (%)' } },
      meta: { annotation_record: key.value, match_row: rowIndex.value },
    },
  }
})
const externalKind = ref('standard')
const externalFormat = ref('text')
const externalName = ref('')
const externalScope = ref('')
const externalText = ref('')
async function readFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) {
    externalText.value = await file.text()
    externalFormat.value = ['mgf', 'msp', 'json'].includes(
      file.name.split('.').at(-1)?.toLowerCase() ?? '',
    )
      ? file.name.split('.').at(-1)!.toLowerCase()
      : 'text'
  }
}
async function archive() {
  if (
    await store.command(`${prefix}/import`, {
      kind: externalKind.value,
      format: externalFormat.value,
      source_name: externalName.value,
      scope: externalScope.value,
      content: externalText.value,
    })
  ) {
    externalText.value = ''
    await reload()
  }
}
</script>

<template>
  <section v-if="store.project" class="card evidence-records">
    <div class="section-heading">
      <h2>证据记录与关联</h2>
      <RouterLink to="/annotation">返回审核对象 →</RouterLink>
    </div>
    <p v-if="target">
      关联目标
      {{ target.kind === 'ec' ? '离子组' : target.kind === 'candidate' ? '候选' : '测量峰' }} ·
      {{ target.id
      }}<template v-if="target.version"> · 版本 {{ target.version.slice(0, 8) }}</template>
    </p>
    <p v-else class="muted">可从审核对象带入关联目标，也可在比对结果中明确选择测量峰。</p>
    <div class="actions">
      <label
        >已保存记录
        <select v-model="key" aria-label="已保存证据记录" @change="rowIndex = null">
          <option value="">选择记录</option>
          <optgroup label="MS/MS 比对">
            <option v-for="row in index?.searches" :key="row.id" :value="row.id">
              {{ formatTime(row.created_at) }} · {{ row.parameters.sample_pool }} ·
              {{ row.size }} 条{{ row.current ? '' : ' · 其他来源或历史版本' }}
            </option>
          </optgroup>
          <optgroup label="原始谱复核与外部证据">
            <option v-for="row in index?.external" :key="row.evidence_id" :value="row.evidence_id">
              {{ row.scope.description || row.source.name || row.kind }} ·
              {{ row.kind === 'ms1_overlap' ? '原始谱重叠复核' : row.kind }}
            </option>
          </optgroup>
        </select>
      </label>
      <button class="save" :disabled="!record" @click="download">下载完整证据 JSON</button>
    </div>
    <template v-if="record?.rows">
      <p v-if="currentRecord && !currentRecord.current" class="state-note">
        历史记录的测量来源或样本轴与当前选择不同，可核对原谱。
      </p>
      <label v-if="target?.feature_id" class="inline-check"
        ><input v-model="showAll" type="checkbox" />显示全部峰的比对</label
      >
      <div class="table-scroll msms-results">
        <table>
          <thead>
            <tr>
              <th>测量峰 / 扫描</th>
              <th>前体 m/z</th>
              <th>参考条目</th>
              <th>匹配片段</th>
              <th>相似度</th>
              <th>阈值结果</th>
              <th>样本池</th>
              <th>关联</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="{ row, i } in displayed.slice(offset, offset + 50)"
              :key="i"
              :class="{ selected: rowIndex === i }"
            >
              <td>
                <button class="text-button" @click="rowIndex = i">
                  {{ row.feature_id }} / {{ row.measured_scan }}
                </button>
              </td>
              <td>{{ row.precursor_mz }}</td>
              <td>{{ row.name }} · #{{ row.library_scan }}</td>
              <td>{{ row.matched_fragments }}</td>
              <td>{{ row.score === null ? '不可评估' : row.score.toFixed(4) }}</td>
              <td>{{ row.passes_threshold ? '实测比对通过' : '实测未匹配' }}</td>
              <td>{{ row.sample_pool }}</td>
              <td>
                {{
                  index?.links.some(
                    (link) =>
                      link.record_id === key && link.row === i && link.decision === 'linked',
                  )
                    ? '已关联'
                    : '待关联'
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!displayed.length" class="muted">当前范围没有前体匹配，原始记录可下载。</p>
      <div v-if="displayed.length > 50" class="actions">
        <button :disabled="!offset" @click="offset -= 50">上一页</button>
        <span
          >{{ offset + 1 }}–{{ Math.min(offset + 50, displayed.length) }} /
          {{ displayed.length }}</span
        >
        <button :disabled="offset + 50 >= displayed.length" @click="offset += 50">下一页</button>
      </div>
      <section v-if="selected" class="fragment-detail">
        <p>
          {{ selected.feature_id }} · {{ selected.name }} · 数据库中有参考谱 ·
          {{ selected.passes_threshold ? '实测比对通过' : '实测未匹配' }}
        </p>
        <p v-if="selected.acquisition_scan_index != null" class="muted">
          原始索引 {{ selected.acquisition_scan_index }} · 隔离窗偏移
          {{ selected.acquisition_isolation_offsets_da?.join(' / ') || '未提供' }} Da · 采集碰撞能
          {{ selected.acquisition_collision_energy ?? '未提供' }} ·
          {{
            selected.acquisition_polarity === 'positive'
              ? '正离子'
              : selected.acquisition_polarity === 'negative'
                ? '负离子'
                : '采集极性未提供'
          }}
        </p>
        <button v-if="currentRecord?.current && !target" class="preview" @click="targetMatch">
          以此测量峰为关联目标
        </button>
        <button
          v-if="currentRecord?.current && target?.kind === 'ec'"
          class="preview"
          @click="memberFeature = selected.feature_id"
        >
          选择该组的测量成员
        </button>
        <PlotView
          v-if="fragmentPlot"
          :figure="fragmentPlot"
          name="msms-fragments"
          legend="hidden"
        />
        <DataTableView
          v-if="fragments.length"
          :table="{ columns: Object.keys(fragments[0]!), rows: fragments, total: fragments.length }"
        />
      </section>
      <details v-if="record.figure">
        <summary>查看比对相似度分布</summary>
        <PlotView :figure="record.figure" name="msms_evidence" />
      </details>
    </template>
    <ProfileReviewResult v-else-if="record?.profile_review" :result="record.profile_review" />
    <p v-else-if="record?.kind">
      {{ record.kind }} · {{ record.scope?.description }}
      {{ record.text ? ' · ' + record.text : '' }}
    </p>
    <div v-if="canLink" class="evidence-link">
      <button class="preview" :disabled="store.busy" @click="association('preview')">
        预览关联范围
      </button>
      <p v-if="preview">
        输入版本 {{ preview.target.version.slice(0, 8) }} · 目标 {{ preview.target.id }} ·
        {{ preview.scope.sample_pool || preview.scope.description }} ·
        {{
          preview.decision === 'linked'
            ? '已关联'
            : preview.decision === 'withdrawn'
              ? '已撤回'
              : '待审核'
        }}
      </p>
      <label>审核理由<input v-model="reason" aria-label="证据关联理由" /></label>
      <div class="actions">
        <button
          class="save"
          :disabled="
            store.busy ||
            !reason.trim() ||
            preview?.decision === 'linked' ||
            links.some((link) => link.decision === 'linked')
          "
          @click="association('linked')"
        >
          保存证据关联
        </button>
        <button
          class="restore"
          :disabled="
            store.busy || !reason.trim() || !links.some((link) => link.decision === 'linked')
          "
          @click="association('withdrawn')"
        >
          撤回关联
        </button>
      </div>
    </div>
    <details v-if="recordLinks.length">
      <summary>此记录的关联历史</summary>
      <div v-for="link in recordLinks" :key="link.id" class="actions">
        <span>{{ link.target.id }} · {{ link.decision === 'linked' ? '已关联' : '已撤回' }}</span>
        <button
          class="preview"
          :disabled="store.busy || !sources.some((item) => item.id === link.target.source)"
          @click="returnToTarget(link)"
        >
          回看关联目标
        </button>
      </div>
    </details>
    <details>
      <summary>登记标准品、空白、群体谱或人工证据</summary>
      <div class="field-grid">
        <label
          >类型<select v-model="externalKind">
            <option value="standard">标准品</option>
            <option value="blank">空白</option>
            <option value="bulk_msms">群体 MS/MS</option>
            <option value="experience">经验标注</option>
            <option value="literature">文献</option>
            <option value="user_review">人工审阅</option>
            <option value="tracer">示踪</option>
          </select></label
        >
        <label>来源名称<input v-model="externalName" /></label>
        <label>适用范围<input v-model="externalScope" /></label>
        <label
          >载入文件<input type="file" accept=".json,.mgf,.msp,.txt" @change="readFile"
        /></label>
        <label
          >格式<select v-model="externalFormat">
            <option value="text">文字</option>
            <option value="json">JSON</option>
            <option value="mgf">MGF</option>
            <option value="msp">MSP</option>
          </select></label
        >
      </div>
      <label class="field">原始引用、正文或谱表<textarea v-model="externalText" rows="3" /></label>
      <button
        class="primary"
        :disabled="
          store.busy || !externalName.trim() || !externalScope.trim() || !externalText.trim()
        "
        @click="archive"
      >
        登记证据
      </button>
    </details>
  </section>
</template>

<style scoped>
.evidence-records .actions {
  align-items: end;
  flex-wrap: wrap;
}
.msms-results {
  max-height: 320px;
  overflow: auto;
}
.msms-results th {
  position: sticky;
  top: 0;
  z-index: 1;
}
.msms-results tr.selected {
  background: #e4f2f4;
}
.fragment-detail,
.evidence-link {
  margin: 8px 0;
  padding: 8px;
  border: 1px solid var(--border);
}
</style>
