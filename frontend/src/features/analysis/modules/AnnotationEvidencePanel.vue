<script setup lang="ts">
import { ref, watch } from 'vue'
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
watch(
  () => [store.current?.workspace_id, store.project?.path, source.value?.identity],
  () => {
    preview.value = undefined
    newest.value = ''
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
  const value = await store.command<Figure>('/analysis/msms', {
    source: sourceId.value,
    measured: measured.value,
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
      <label
        >字段对应（每行：导入列名=目标注释列名）<textarea
          v-model="mappingText"
          :disabled="store.busy"
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
      <p>
        导入带前体质量的实测与参考 MGF/MSP
        谱。每条扫描与参考候选独立保留，池化证据不自动传递为逐细胞鉴定；相似度不是概率。
      </p>
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
      <label>样本池与适用范围<input v-model="pool" :disabled="store.busy" /></label
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
      <div class="actions">
        <button
          class="primary"
          :disabled="store.busy || !measured || !library || !pool"
          @click="search()"
        >
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
.evidence-input section > label {
  display: inline-grid;
  gap: 3px;
  min-width: 160px;
  margin: 3px 7px 5px 0;
  vertical-align: top;
}
.evidence-input button[aria-pressed='true'] {
  background: #e4f2f4;
  border-color: var(--teal);
}
</style>
