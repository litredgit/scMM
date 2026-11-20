<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { AnnotationSource } from '../../api/types'
import AnnotationHeader from '../annotation/AnnotationHeader.vue'
import { useAnnotationSource } from '../annotation/useAnnotationSource'
import { useReadScope } from '../../api/readScope'
import { formatTime } from '../../help/time'
import PlotView from '../../components/PlotView.vue'
import DataTableView from '../../components/DataTable.vue'
import LipidNetworkOptions from './LipidNetworkOptions.vue'
import LipidNetworkPanel from './LipidNetworkPanel.vue'
import AnnotationSpectrum from '../annotation/AnnotationSpectrum.vue'
import ProfileReviewPanel from '../annotation/ProfileReviewPanel.vue'
import type { ProfileCandidate } from '../annotation/profileReview'
import { ms2Label } from './lipids'
import { useLipidPanel } from './useLipidPanel'
const props = defineProps<{ source: AnnotationSource }>()
const router = useRouter()
const sourceId = computed(() => props.source.id)
const sourceIdentity = computed(() => props.source.identity)
const { grouping, selectTarget, selectedTarget, clearTarget } = useAnnotationSource()
const settings = ref('')
const showCharts = ref(false)
const {
  store,
  auth,
  info,
  results,
  resultLoading,
  resultFeature,
  isotopeFigure,
  rules,
  imported,
  preset,
  presetName,
  version,
  label,
  feature,
  selection,
  annotationName,
  syncRelated,
  offset,
  relationOffset,
  ruleOffset,
  candidateSort,
  relationSort,
  candidateSortOptions,
  relationSortOptions,
  sorting,
  limit,
  options,
  filters,
  rulesTable,
  validVersion,
  viewIsotope,
  classificationChoices,
  prepare,
  loadResults,
  run,
  importFile,
  choosePreset,
  savePreset,
  applyRules,
  activate,
  selectFeature,
  changeVersion,
  applyFilters,
  saveSelection,
  reviewRelation,
  pageCandidates,
  pageRelations,
  download,
  template,
  number,
  candidateDescending,
  relationDescending,
} = useLipidPanel(sourceId, sourceIdentity, () => groupingVersion.value)
const groupingVersion = computed(
  () => grouping.value || info.value?.grouping_versions?.at(-1) || '',
)
type EvidenceLink = {
  id: string
  record_id: string
  row: number | null
  decision: string
  target: { kind: string; id: string; version: string }
  scope: Record<string, unknown>
  passes_threshold: boolean | null
}
const evidenceLinks = ref<EvidenceLink[]>([])
const evidenceKey = () => [
  store.current?.workspace_id,
  store.project?.path,
  sourceIdentity.value,
  feature.value,
  store.current?.revision,
]
const evidenceReads = useReadScope(evidenceKey, () => void loadEvidence())
async function loadEvidence() {
  if (!feature.value) return
  const query = new URLSearchParams({ source: sourceId.value, feature: feature.value })
  const value = await store.read<{ links: EvidenceLink[] }>(
    '/analysis/annotation-evidence?' + query,
    undefined,
    evidenceReads.begin(),
  )
  if (value) evidenceLinks.value = value.links
}
watch(evidenceKey, () => {
  evidenceLinks.value = []
  void loadEvidence()
})
const currentEvidence = computed(() =>
  evidenceLinks.value.filter(
    (row) =>
      row.target.kind === 'feature' ||
      (row.target.kind === 'candidate' && row.target.version === version.value),
  ),
)
const currentResult = computed(() =>
  results.value?.version === version.value && resultFeature.value === feature.value
    ? results.value
    : undefined,
)
const profileCandidates = ref<ProfileCandidate[]>([])
function compositionDiffers(row: Record<string, unknown>) {
  const compact = (value: unknown) => String(value ?? '').replace(/[()\s]/g, '')
  return !!row.species && compact(row.species) !== compact(row.name)
}
watch([sourceIdentity, version], () => {
  profileCandidates.value = []
})
function addProfileCandidate(row: Record<string, unknown>) {
  const id = String(row.candidate_id)
  if (profileCandidates.value.some((candidate) => candidate.candidate_id === id)) {
    profileCandidates.value = profileCandidates.value.filter(
      (candidate) => candidate.candidate_id !== id,
    )
  } else if (profileCandidates.value.length < 2) {
    profileCandidates.value = [
      ...profileCandidates.value,
      {
        candidate_id: id,
        feature_id: String(row.feature_id),
        name: String(row.name),
        adduct: String(row.adduct),
      },
    ]
  }
}
const filteredIds = computed(() => results.value?.features.map((row) => row.id))
watch(feature, (id) => {
  if (id && selectedTarget.value?.featureId !== id)
    selectTarget({
      source: sourceId.value,
      sourceIdentity: sourceIdentity.value,
      kind: 'feature',
      id,
      version: version.value,
    })
})
function showAllCandidates() {
  clearTarget()
  void selectFeature('')
}
function choosePeak(id: string) {
  selectTarget({
    source: sourceId.value,
    sourceIdentity: sourceIdentity.value,
    kind: 'feature',
    id,
    version: version.value,
  })
  void selectFeature(id)
}
async function searchCandidates() {
  if (await run()) settings.value = ''
}
function evidenceFor(candidate?: string, record?: string, row?: number | null) {
  if (!feature.value) return
  selectTarget({
    source: sourceId.value,
    sourceIdentity: sourceIdentity.value,
    kind: candidate ? 'candidate' : 'feature',
    id: candidate ?? feature.value,
    featureId: feature.value,
    version: version.value,
  })
  void router.push({
    path: '/annotation/evidence',
    query: record ? { record, ...(row == null ? {} : { row }) } : {},
  })
}
watch(
  [() => selectedTarget.value, () => router.currentRoute.value.path],
  ([target]) => {
    if (target && router.currentRoute.value.path === '/annotation') {
      if (
        target.kind === 'candidate' &&
        target.version &&
        info.value?.versions.some((item) => item.id === target.version && item.valid)
      )
        version.value = target.version
      const id = target.featureId ?? (target.kind === 'feature' ? target.id : '')
      if (id && id !== feature.value) void selectFeature(id)
    }
  },
  { immediate: true },
)
</script>

<template>
  <AnnotationHeader
    title="候选与关系审核"
    :version="validVersion ? version : ''"
    :grouping="groupingVersion"
  />
  <section class="card lipid-panel" aria-label="注释与同位素">
    <AnnotationSpectrum
      :source="source"
      :version="validVersion ? version : ''"
      :feature-id="feature"
      :group="selectedTarget?.kind === 'ec' ? selectedTarget : undefined"
      :grouping="groupingVersion"
      :samples="info?.samples ?? []"
      :result-ids="filteredIds"
      @select="choosePeak"
      @review="reviewRelation"
    >
      <template #actions>
        <button
          class="primary"
          :aria-expanded="settings === 'search'"
          @click="settings = settings === 'search' ? '' : 'search'"
        >
          {{ settings === 'search' ? '收起查库设置' : '查找候选' }}
        </button>
        <slot name="grouping-action" />
        <ProfileReviewPanel
          :source="sourceId"
          :version="validVersion ? version : ''"
          :candidates="profileCandidates"
          @clear="profileCandidates = []"
        />
      </template>
      <template #settings>
        <section v-show="settings === 'search'" class="search-settings" aria-label="查找候选设置">
          <h2>注释与同位素</h2>
          <p class="muted">按所选测量来源的峰 m/z 查找候选。</p>
          <slot name="group-search" />
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
                  <optgroup v-if="info?.database.presets?.length" label="内置候选数据库">
                    <option
                      v-for="database in info?.database.presets"
                      :key="database.id"
                      :value="database.id"
                      :disabled="!database.available"
                    >
                      {{ database.label }} · {{ database.records }} 条候选
                    </option>
                  </optgroup>
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
            <p v-if="options.database.startsWith('preset:')" class="muted">
              {{
                info?.database.presets?.find((database) => database.id === options.database)
                  ?.description || '用户提供的脂质候选预设。数据库条目与谱图实测匹配分别记录。'
              }}
            </p>
            <details
              v-if="(info?.database.presets?.length ?? 0) + (info?.database.files.length ?? 0) > 1"
            >
              <summary>附加数据库（可多选）</summary>
              <label
                >同时检索的附加数据库<select
                  v-model="options.databases"
                  multiple
                  aria-label="附加注释数据库"
                >
                  <option
                    v-for="database in info?.database.presets"
                    :key="database.id"
                    :value="database.id"
                    :disabled="!database.available || options.database === database.id"
                  >
                    {{ database.label }}
                  </option>
                  <option
                    v-for="file in info?.database.files"
                    :key="file.filename"
                    :value="file.filename"
                    :disabled="options.database === file.filename"
                  >
                    {{ file.filename }}
                  </option>
                </select></label
              >
              <details class="inline-explanation">
                <summary>查看说明</summary>
                <p>不同数据库的候选与二级证据分别保留来源，不按名称或质量强制合并。</p>
              </details>
            </details>
            <div class="lipid-adducts">
              <label
                v-for="(spec, name) in info?.adducts"
                :key="name"
                v-show="options.polarity === 'both' || spec.polarity === options.polarity"
                ><input type="checkbox" :value="name" v-model="options.adducts" />{{ name }}</label
              >
            </div>
            <button
              class="secondary save"
              @click="prepare"
              :disabled="options.database.startsWith('preset:')"
            >
              {{ info?.database.available ? '检查本地数据库' : '准备数据库（缺失时官方下载）' }}
            </button>
          </fieldset>

          <fieldset :disabled="store.busy">
            <legend>评分规则与预设</legend>
            <details class="inline-explanation">
              <summary>查看说明</summary>
              <p>
                先按绝对 ppm 的 0–2、&gt;2–5、&gt;5
                三档排序，档内按类别分＋加合物分排序，同分并列。没有内置评分规则。
              </p>
            </details>
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
                  <option v-for="(_, name) in info?.presets" :key="name" :value="name">
                    {{ name }}
                  </option>
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
                <button
                  :disabled="ruleOffset + limit >= rules.rules.length"
                  @click="ruleOffset += limit"
                >
                  规则下一页
                </button>
              </div>
              <details class="inline-explanation">
                <summary>查看说明</summary>
                <p>
                  类别支持
                  CATEGORY、MAIN_CLASS、SUB_CLASS、LIPID_CLASS；较具体规则覆盖同项的通用规则。
                </p>
              </details>
            </details>
          </fieldset>

          <fieldset :disabled="store.busy">
            <legend>候选与强度证据</legend>
            <label
              >候选与证据模式<select
                v-model="options.mass_only"
                aria-label="注释证据模式"
                :disabled="info?.quantitation_available === false"
              >
                <option :value="false" :disabled="!info?.layers.length">
                  精确质量、天然同位素与相关证据
                </option>
                <option :value="true">仅精确质量候选</option>
              </select></label
            >
            <p v-if="options.mass_only" class="state-note">
              当前模式按 m/z 检索候选。可在谱图中审核候选和加合关系，强度来源与矩阵值随数据保留。
            </p>
            <template v-else>
              <LipidNetworkOptions v-model="options.network" :info="info" />
              <div class="field-grid">
                <label
                  ><FieldLabel
                    name="intensity_layer"
                    text="选择未归一化、未插补的强度层。导入数据的初始层未必是原始强度，请按来源核对。"
                  /><select aria-label="脂质 intensity_layer" v-model="options.intensity_layer">
                    <option v-for="item in info?.layers" :key="item" :value="item">
                      {{ item }}
                    </option>
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
            </template>
            <button :disabled="!options.adducts.length" @click="searchCandidates" class="primary">
              {{ options.mass_only ? '运行精确质量候选注释' : '运行注释与同位素标记' }}
            </button>
          </fieldset>
        </section>
        <slot name="grouping-settings" />
        <p v-if="version && !validVersion" class="state-note">
          该版本输入已改变。请重新查库后核对和下载。
        </p>
      </template>
      <template #version>
        <div class="actions annotation-version">
          <label
            ><FieldLabel name="查看版本（北京时间）" /><select
              aria-label="脂质查看版本"
              v-model="version"
              @change="changeVersion"
            >
              <option value="">未注释状态</option>
              <option v-for="item in info?.versions" :key="item.id" :value="item.id">
                {{ item.label }} · {{ formatTime(item.created_at)
                }}{{ item.valid ? '' : ' · 已过期' }}{{ item.id === info?.active ? ' · 当前' : '' }}
              </option>
            </select></label
          >
          <button
            class="preview"
            :disabled="store.busy || version === info?.active || (!!version && !validVersion)"
            @click="activate"
          >
            设为当前注释版本
          </button>
        </div>
      </template>
      <template #candidates="{ peak, status }">
        <p v-if="!peak">先从图或列表选择一个峰。</p>
        <template v-else>
          <p class="muted">
            {{ status }}
            <button class="text-button" @click="showAllCandidates">查看全部候选</button>
          </p>
          <p v-if="resultLoading && !currentResult" role="status">正在读取当前峰的候选…</p>
          <template v-if="currentResult">
            <article
              v-for="row in currentResult.feature_candidates.rows"
              :key="String(row.candidate_id)"
              class="candidate-card"
            >
              <label class="lipid-check">
                <input
                  v-model="selection"
                  type="checkbox"
                  :value="String(row.candidate_id)"
                  :aria-label="`指定 ${row.database_id} ${row.adduct}`"
                  :disabled="store.busy"
                />
                <strong>{{ row.name }}</strong>
              </label>
              <p>
                {{ row.database_filename }} · {{ row.adduct }} · {{ number(row.ppm_error) }} ppm
              </p>
              <p v-if="compositionDiffers(row)">总组成 {{ row.species }}</p>
              <p>
                {{ ms2Label(row.ms2_status) }} · {{ row.top_ranked ? '规则推荐' : '容差内候选' }}
              </p>
              <p v-if="row.source_annotation_level">
                原表注释 {{ row.source_annotation_level }} · MSI {{ row.source_msi_level }}
              </p>
              <p v-if="row.source_formula_conflict">
                原表理论 m/z 与分子式及加合物不一致，仅提供质量候选。
              </p>
              <details>
                <summary>候选详情</summary>
                <dl class="candidate-details">
                  <template
                    v-for="key in [
                      'database_record_id',
                      'formula',
                      'theoretical_mz',
                      'ppm_band',
                      'network_level',
                      'class_score',
                      'adduct_score',
                      'rule_score',
                      'score_evidence',
                    ]"
                    :key="key"
                  >
                    <dt><FieldLabel :name="key" /></dt>
                    <dd>{{ row[key] ?? '—' }}</dd>
                  </template>
                </dl>
                <dl v-if="row.source_row" class="candidate-details">
                  <dt>原表编号</dt>
                  <dd>{{ row.source_row }}</dd>
                  <dt>原表实测 m/z</dt>
                  <dd>{{ row.source_observed_mz }}</dd>
                  <dt>原表加合物</dt>
                  <dd>{{ row.source_adduct }}</dd>
                  <dt>原表质量误差（ppm）</dt>
                  <dd>{{ row.source_ppm_error }}</dd>
                  <dt>原表理论值与分子式计算值之差（ppm）</dt>
                  <dd>{{ row.source_formula_ppm_error }}</dd>
                </dl>
                <button class="preview" @click="evidenceFor(String(row.candidate_id))">
                  关联此候选的证据
                </button>
              </details>
              <button
                v-if="row.formula && !row.source_formula_conflict"
                type="button"
                class="text-button"
                :aria-pressed="
                  profileCandidates.some((item) => item.candidate_id === row.candidate_id)
                "
                :disabled="
                  store.busy ||
                  (profileCandidates.length === 2 &&
                    !profileCandidates.some((item) => item.candidate_id === row.candidate_id))
                "
                @click="addProfileCandidate(row)"
              >
                {{
                  profileCandidates.some((item) => item.candidate_id === row.candidate_id)
                    ? '移出原始谱复核'
                    : '选入原始谱复核'
                }}
              </button>
            </article>
            <div v-if="currentResult.feature_candidates.total > limit" class="actions">
              <button :disabled="offset === 0" @click="pageCandidates(-1)">候选上一页</button>
              <button
                :disabled="offset + limit >= currentResult.feature_candidates.total"
                @click="pageCandidates(1)"
              >
                候选下一页
              </button>
            </div>
            <label class="field"
              >人工注释名称
              <input
                v-model="annotationName"
                aria-label="人工注释名称"
                :disabled="store.busy"
                maxlength="500"
                placeholder="留空使用候选名称"
              />
            </label>
            <label class="field"
              >审核修改范围
              <select v-model="syncRelated" aria-label="审核修改范围" :disabled="store.busy">
                <option :value="true">同步已确认关联组</option>
                <option :value="false">仅当前峰</option>
              </select>
            </label>
            <div class="actions">
              <button class="save" :disabled="store.busy" @click="saveSelection()">
                保存人工指定
              </button>
              <button class="restore" :disabled="store.busy" @click="saveSelection(true)">
                恢复规则推荐
              </button>
            </div>
          </template>
        </template>
      </template>
      <template #evidence="{ annotations }">
        <p v-if="!annotations?.length" class="muted">当前峰没有候选二级条目。</p>
        <article
          v-for="row in annotations"
          :key="`${row.candidate_id}:${row.adduct}:${row.isotope_order}`"
          class="candidate-card"
        >
          <strong>{{ row.display_name || row.name }}</strong>
          <p>{{ row.database_filename }} · {{ row.adduct }} · {{ ms2Label(row.ms2_status) }}</p>
        </article>
        <article v-for="link in currentEvidence" :key="link.id" class="candidate-card">
          <strong
            >{{ link.decision === 'linked' ? '已关联' : '已撤回' }} ·
            {{ link.scope.sample_pool || link.scope.description || link.target.id }}</strong
          >
          <p v-if="link.passes_threshold !== null">
            {{ link.passes_threshold ? '实测比对通过' : '实测未匹配' }}
          </p>
          <button
            class="preview"
            @click="
              evidenceFor(
                link.target.kind === 'candidate' ? link.target.id : undefined,
                link.record_id,
                link.row,
              )
            "
          >
            打开原证据
          </button>
        </article>
        <button v-if="feature" class="preview" @click="evidenceFor()">查看或关联证据 →</button>
      </template>
      <template #reviews>
        <DataTableView
          v-if="currentResult?.audit?.length"
          :table="{
            columns: Object.keys(currentResult.audit[0] ?? {}),
            rows: currentResult.audit,
            total: currentResult.audit.length,
          }"
        />
        <p v-else class="muted">当前版本暂无人工审核记录。</p>
      </template>
      <template #relations><slot name="group-relations" /></template>
    </AnnotationSpectrum>

    <section v-if="results" class="lipid-results">
      <details class="lipid-filters">
        <summary>显示和导出筛选</summary>
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
              <option value="strongest" :disabled="!!results?.parameters.mass_only">
                每种物质保留最强加合物峰
              </option>
              <option value="specified">仅指定加合物</option>
            </select></label
          >
          <p v-if="results?.parameters.mass_only" class="muted">
            仅精确质量模式可按加合形式筛选，最强峰选择需要适用的原始强度证据。
          </p>
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
      </details>
      <div id="lipid-review" class="lipid-tables task-section">
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
        <details class="inline-explanation">
          <summary>查看说明</summary>
          <p>全部结果排序后分页，缺失值置后；不改变规则推荐和人工核对。</p>
        </details>
        <p>
          {{ results.features.length }} / {{ results.total_features }} 特征 ·
          {{ results.candidates.total }} 条候选 · {{ results.isotopes.total }} 条关系证据
        </p>
        <p class="muted lipid-path">
          {{ results.database.filename }} · 强度来源 {{ results.intensity_layer || 'X' }}
        </p>
        <div class="data-table candidate-table">
          <table>
            <thead>
              <tr>
                <th>特征 ID</th>
                <th>实测 m/z</th>
                <th>理论 m/z</th>
                <th>物质名</th>
                <th>当前数据库二级匹配</th>
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
              <tr v-for="row in results.candidates.rows" :key="String(row.candidate_id)">
                <td>
                  <button class="text-button" @click="selectFeature(String(row.feature_id))">
                    {{ row.feature_id }}
                  </button>
                </td>
                <td>{{ Number(row.query_mz).toFixed(4) }}</td>
                <td>
                  {{ Number(row.theoretical_mz).toFixed(4)
                  }}<HelpTip :text="String(row.theoretical_mz)" label="完整理论质量" />
                </td>
                <td>{{ row.name }}</td>
                <td>{{ ms2Label(row.ms2_status) }}</td>
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
            >{{ offset + 1 }}–{{ offset + results.candidates.rows.length }} /
            {{ results.candidates.total }} 条</span
          ><button
            class="secondary"
            :disabled="store.busy || offset + limit >= results.candidates.total"
            @click="pageCandidates(1)"
          >
            候选下一页
          </button>
        </div>

        <details class="isotope-table">
          <summary>完整天然同位素关系</summary>
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
          <details class="inline-explanation">
            <summary>查看说明</summary>
            <p>全部结果排序后分页，缺失值置后；不改变规则推荐和人工核对。</p>
          </details>
          <details class="inline-explanation">
            <summary>查看说明</summary>
            <p>
              同一特征可有多个来源解释；每个样本分别记录。命中表示质量和双侧比例条件通过，不证明该峰只有同位素贡献。
            </p>
          </details>
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
                  <td>{{ Number(row.parent_mz).toFixed(4) }}</td>
                  <td>
                    {{ Number(row.isotope_mz).toFixed(4) }} /
                    {{ Number(row.predicted_mz).toFixed(4) }}
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
        </details>
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
    </section>
    <details
      v-if="results && !results.parameters.mass_only && source.quantitation_available"
      @toggle="showCharts = ($event.target as HTMLDetailsElement).open || showCharts"
    >
      <summary>分类与相关网络图表</summary>
      <LipidNetworkPanel
        v-if="showCharts"
        :source="source.id"
        :results="results"
        :filters="{
          ...filters,
          adducts: filters.adduct_mode === 'specified' ? filters.adducts : [],
        }"
        @select="selectFeature"
        @updated="loadResults()"
      />
    </details>
    <section v-if="results" id="lipid-export" class="task-section">
      <h3>下载注释与核对结果</h3>
      <details class="inline-explanation">
        <summary>查看说明</summary>
        <p>CSV 使用当前筛选条件，包含全部细胞；不会只导出当前页或选中特征。</p>
      </details>
      <div class="lipid-downloads">
        <button
          class="save"
          :disabled="store.busy || !validVersion || !source.quantitation_available"
          @click="download('matrix')"
        >
          导出筛选矩阵 CSV</button
        ><button
          class="save"
          :disabled="store.busy || !validVersion"
          @click="download('candidates')"
        >
          导出候选明细 CSV</button
        ><button class="save" :disabled="store.busy || !validVersion" @click="download('isotopes')">
          导出完整同位素关系 CSV</button
        ><button class="secondary save" :disabled="store.busy" @click="download('rules')">
          导出版本规则 JSON
        </button>
      </div>
    </section>
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
.annotation-version {
  align-items: end;
  margin: 0 0 0 auto;
  gap: 6px;
}
.annotation-version select {
  width: auto;
  max-width: min(100%, 260px);
}
.search-settings {
  padding: 8px;
}
.candidate-card {
  border-bottom: 1px solid var(--border);
  padding: 5px 0;
  overflow-wrap: anywhere;
}
.candidate-card p {
  margin: 3px 0;
}
.candidate-details {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px;
}
.candidate-details dd {
  margin: 0;
}
.lipid-results {
  margin-top: 12px;
}
.lipid-filters fieldset {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 8px;
}
.candidate-table {
  max-height: 370px;
  overflow: auto;
}
.candidate-table thead {
  position: sticky;
  top: 0;
  z-index: 1;
}
.lipid-downloads,
.lipid-review {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
</style>
