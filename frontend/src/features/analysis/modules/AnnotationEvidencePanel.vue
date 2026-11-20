<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import { useAnnotationSource } from '../../annotation/useAnnotationSource'
import EvidenceRecords from '../../annotation/EvidenceRecords.vue'
import type { DataTable, Figure } from '../../../api/types'
import DataTableView from '../../../components/DataTable.vue'
import { useViewState } from '../../../api/viewState'
const store = useWorkspace()
const { source, sourceId } = useAnnotationSource()
const view = ref<'table' | 'msms'>('table')
const newest = ref('')
const featureColumns = ref<string[]>(['mz'])
const content = ref(''),
  format = ref('csv'),
  mappingText = ref('name=manual_annotation'),
  sourceKey = ref('feature_id'),
  targetKey = ref('feature_id'),
  alignment = ref('key'),
  ppm = ref(5),
  clear = ref(false),
  transpose = ref(false)
const preview = ref<{ table: DataTable; matched: number; ambiguous: number; unmatched: number }>()
const measured = ref(''),
  library = ref(''),
  measuredFormat = ref('mgf'),
  libraryFormat = ref('mgf'),
  pool = ref(''),
  polarity = ref('positive'),
  energy = ref(''),
  instrument = ref(''),
  precursorPPM = ref(10),
  fragmentPPM = ref(20),
  score = ref(0.5),
  matches = ref(3)
const msmsInput = ref<'spectrum' | 'acquisition'>('spectrum')
const acquisitionSample = ref('')
const firstScan = ref<number | ''>(0)
const lastScan = ref<number | ''>('')
const unknownType = ref('')
const acquisitions = computed(() =>
  (store.project?.manifest.samples ?? []).filter(
    (row) => !row.result_only && /\.(mzml|mzxml)$/i.test(row.path),
  ),
)
const canSearch = computed(
  () =>
    !!library.value &&
    !!pool.value.trim() &&
    (msmsInput.value === 'spectrum'
      ? !!measured.value
      : acquisitions.value.some((row) => row.id === acquisitionSample.value) &&
        firstScan.value !== '' &&
        Number.isInteger(firstScan.value) &&
        firstScan.value >= 0 &&
        (lastScan.value === '' ||
          (Number.isInteger(lastScan.value) && lastScan.value >= firstScan.value))),
)
watch(
  () => [store.current?.workspace_id, store.project?.path, source.value?.identity],
  () => {
    preview.value = undefined
    newest.value = ''
    acquisitionSample.value = ''
  },
)
watch(
  () => [sourceId.value, source.value?.identity],
  async () => {
    const identity = source.value?.identity
    featureColumns.value = ['mz']
    if (!identity) return
    const payload = await store.read<{ feature_columns: string[] }>(
      '/lipids?source=' + encodeURIComponent(sourceId.value),
      undefined,
      () => source.value?.identity === identity,
    )
    if (payload) featureColumns.value = payload.feature_columns
  },
  { immediate: true },
)
watch(
  [content, format, mappingText, sourceKey, targetKey, alignment, ppm, clear, transpose],
  () => {
    preview.value = undefined
  },
)
async function file(event: Event, type: 'content' | 'measured' | 'library') {
  const selected = (event.target as HTMLInputElement).files?.[0]
  if (!selected) return
  const text = await selected.text()
  if (type === 'content') content.value = text
  else if (type === 'measured') measured.value = text
  else library.value = text
}
function annotationOptions() {
  const mapping = Object.fromEntries(
    mappingText.value
      .split('\n')
      .filter((v) => v.trim())
      .map((v) => {
        const index = v.indexOf('=')
        return [v.slice(0, index).trim(), v.slice(index + 1).trim()]
      }),
  )
  return {
    source: sourceId.value,
    content: content.value,
    format: format.value,
    mapping,
    source_key: sourceKey.value,
    target_key: targetKey.value,
    mode: alignment.value,
    ppm: ppm.value,
    clear_unmatched: clear.value,
    transpose: transpose.value,
  }
}
async function annotate(apply = false) {
  const value = await store.command<typeof preview.value>(
    `/analysis/annotations/${apply ? 'apply' : 'preview'}`,
    annotationOptions(),
  )
  if (value) {
    preview.value = apply ? undefined : value
    if (apply) store.notice = '注释已应用，请保存项目。'
  }
}
async function search() {
  if (!canSearch.value) return
  const value = await store.command<Figure>('/analysis/msms', {
    source: sourceId.value,
    measured: msmsInput.value === 'spectrum' ? measured.value : '',
    library: library.value,
    measured_format: measuredFormat.value,
    library_format: libraryFormat.value,
    sample_pool: pool.value,
    polarity: polarity.value,
    collision_energy: energy.value,
    instrument: instrument.value,
    precursor_ppm: precursorPPM.value,
    fragment_ppm: fragmentPPM.value,
    minimum_score: score.value,
    minimum_matches: matches.value,
    ...(msmsInput.value === 'acquisition'
      ? {
          acquisition_sample: acquisitionSample.value,
          scan_start: firstScan.value,
          scan_end: lastScan.value === '' ? null : lastScan.value,
          unknown_spectrum_type: unknownType.value,
        }
      : {}),
  })
  const meta = value?.layout.meta as { annotation_record?: string } | undefined
  if (meta?.annotation_record) newest.value = meta.annotation_record
}
useViewState('annotation_evidence', {
  mappingText,
  sourceKey,
  targetKey,
  alignment,
  ppm,
  clear,
  transpose,
  measuredFormat,
  libraryFormat,
  pool,
  polarity,
  energy,
  instrument,
  precursorPPM,
  fragmentPPM,
  score,
  matches,
  view,
})
</script>
<template>
  <div v-if="source" class="card evidence-input">
    <div class="tabs">
      <button :aria-pressed="view === 'table'" @click="view = 'table'">已有注释表</button>
      <button :aria-pressed="view === 'msms'" @click="view = 'msms'">MS/MS 搜索</button>
    </div>
    <section v-show="view === 'table'">
      <h3>导入注释表</h3>
      <p>按稳定编号或指定字段对齐。多条匹配会阻止写入；按顺序导入须显式选择且行数一致。</p>
      <div class="field-grid evidence-fields">
        <label
          >注释文件<input
            type="file"
            accept=".csv,.tsv,.txt"
            :disabled="store.busy"
            @change="file($event, 'content')"
        /></label>
        <label
          >文件格式<select v-model="format" :disabled="store.busy">
            <option value="csv">CSV</option>
            <option value="tsv">TSV</option>
          </select></label
        >
        <label
          >表格方向<select v-model="transpose" :disabled="store.busy">
            <option :value="false">每行一个特征</option>
            <option :value="true">首列为字段名，转置后导入</option>
          </select></label
        >
        <label class="span-two"
          >字段对应（每行：导入列名=目标注释列名）<textarea
            v-model="mappingText"
            :disabled="store.busy"
            rows="2"
          />
        </label>
        <label
          >匹配方式<select v-model="alignment" :disabled="store.busy">
            <option value="key">指定匹配字段</option>
            <option value="position">显式按当前特征顺序</option>
          </select></label
        >
        <template v-if="alignment === 'key'"
          ><label>导入表匹配列<input v-model="sourceKey" :disabled="store.busy" /></label
          ><label
            >当前特征匹配列<select v-model="targetKey" :disabled="store.busy">
              <option value="feature_id">稳定特征编号</option>
              <option v-for="key in featureColumns" :key="key" :value="key">{{ key }}</option>
            </select></label
          ><label v-if="targetKey === 'mz'"
            >质量匹配容差（ppm）<input
              v-model.number="ppm"
              type="number"
              min="0"
              :disabled="store.busy" /></label
        ></template>
        <label
          >未匹配项<select v-model="clear" :disabled="store.busy">
            <option :value="false">保留已有注释</option>
            <option :value="true">清空目标列的未匹配项</option>
          </select></label
        >
      </div>
      <div class="actions">
        <button class="preview" :disabled="store.busy || !content" @click="annotate()">
          预览匹配</button
        ><button
          class="primary"
          :disabled="store.busy || !preview || !!preview.ambiguous"
          @click="annotate(true)"
        >
          应用注释
        </button>
      </div>
      <template v-if="preview"
        ><p>
          匹配 {{ preview.matched }} · 歧义 {{ preview.ambiguous }} · 未匹配 {{ preview.unmatched }}
        </p>
        <DataTableView :table="preview.table"
      /></template>
    </section>
    <section v-show="view === 'msms'">
      <h3>MS/MS 候选搜索</h3>
      <p>逐扫描比较碎片谱。样本池与适用范围随比对记录保存。</p>
      <div class="field-grid evidence-fields">
        <label>
          实测来源
          <select v-model="msmsInput" :disabled="store.busy">
            <option value="spectrum">实测 MGF/MSP</option>
            <option value="acquisition">项目 mzML/mzXML</option>
          </select>
        </label>
        <template v-if="msmsInput === 'acquisition'">
          <label>
            项目采集文件
            <select v-model="acquisitionSample" :disabled="store.busy">
              <option value="">选择项目样本</option>
              <option v-for="row in acquisitions" :key="row.id" :value="row.id">
                {{ row.name }}
              </option>
            </select>
          </label>
          <label>
            起始扫描索引（从 0 开始）
            <input
              v-model.number="firstScan"
              type="number"
              min="0"
              step="1"
              :disabled="store.busy"
            />
          </label>
          <label>
            结束扫描索引（含端点）
            <input
              v-model.number="lastScan"
              type="number"
              min="0"
              step="1"
              placeholder="留空至文件末尾"
              :disabled="store.busy"
            />
          </label>
          <label>
            文件缺少谱型时
            <select v-model="unknownType" :disabled="store.busy">
              <option value="">跳过类型未知的扫描</option>
              <option value="centroid">已知为质心谱</option>
              <option value="profile">已知为连续谱</option>
            </select>
          </label>
        </template>
        <template v-else>
          <label
            >实测谱文件<input
              type="file"
              accept=".mgf,.msp"
              :disabled="store.busy"
              @change="file($event, 'measured')" /></label
          ><label
            >实测格式<select v-model="measuredFormat" :disabled="store.busy">
              <option value="mgf">MGF</option>
              <option value="msp">MSP</option>
            </select></label
          >
        </template>
        <label
          >参考谱库<input
            type="file"
            accept=".mgf,.msp"
            :disabled="store.busy"
            @change="file($event, 'library')" /></label
        ><label
          >参考格式<select v-model="libraryFormat" :disabled="store.busy">
            <option value="mgf">MGF</option>
            <option value="msp">MSP</option>
          </select></label
        >
        <label class="span-two"
          >样本池与适用范围<input v-model="pool" :disabled="store.busy" /></label
        ><label
          >极性<select v-model="polarity" :disabled="store.busy">
            <option value="positive">正离子</option>
            <option value="negative">负离子</option>
          </select></label
        ><label>碰撞能（未知可空）<input v-model="energy" :disabled="store.busy" /></label
        ><label>仪器（未知可空）<input v-model="instrument" :disabled="store.busy" /></label>
        <label
          >前体容差（ppm）<input
            v-model.number="precursorPPM"
            type="number"
            min="0"
            :disabled="store.busy" /></label
        ><label
          >碎片容差（ppm）<input
            v-model.number="fragmentPPM"
            type="number"
            min="0"
            :disabled="store.busy" /></label
        ><label
          >最低相似度<input
            v-model.number="score"
            type="number"
            min="0"
            max="1"
            step=".01"
            :disabled="store.busy" /></label
        ><label
          >最少匹配碎片<input v-model.number="matches" type="number" min="1" :disabled="store.busy"
        /></label>
      </div>
      <p v-if="msmsInput === 'acquisition' && !acquisitions.length" class="state-note">
        请先在项目样本中登记可读的 mzML 或 mzXML 文件。
      </p>
      <div class="actions">
        <button class="primary" :disabled="store.busy || !canSearch" @click="search()">
          搜索候选证据
        </button>
      </div>
    </section>
  </div>
  <p v-else class="card">
    导入注释表和实测二级比对需要稳定的测量峰来源。已有证据记录可在下方查询。
  </p>
  <EvidenceRecords :newest="newest" />
</template>

<style scoped>
.evidence-input section {
  margin-top: 8px;
}
.evidence-fields {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 6px 0 10px;
}
.evidence-fields .span-two {
  grid-column: span 2;
}
.evidence-fields label {
  min-width: 0;
  gap: 4px;
}
.evidence-input button[aria-pressed='true'] {
  background: #e4f2f4;
  border-color: var(--teal);
}
</style>
