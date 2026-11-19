<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import PlotView from '../../components/PlotView.vue'
import { request } from '../../api/client'
import { useReadScope } from '../../api/readScope'
import { useViewState } from '../../api/viewState'
import { useWorkspace } from '../../stores/workspace'
import type { Figure, WorkspaceView } from '../../api/types'
import { ms2Label, type AnnotationSpectrum } from '../preprocess/lipids'

const props = defineProps<{ version: string; featureId: string; samples: string[] }>()
const emit = defineEmits<{
  (event: 'select', id: string): void
  (event: 'review', id: string, state: string): void
}>()
const store = useWorkspace()
const sample = ref('')
const showNames = ref(true)
const showMS2 = ref(true)
const data = ref<AnnotationSpectrum>()
const failure = ref('')
const loading = ref(false)
const relationPage = ref(0)
const identity = () => [
  store.current?.workspace_id,
  store.project?.path,
  store.current?.revision,
  props.version,
  props.featureId,
  sample.value,
]
const reads = useReadScope(identity, () => void load())
async function load() {
  const current = store.current
  const accept = reads.begin()
  if (!current || !props.version) {
    data.value = undefined
    return
  }
  failure.value = ''
  loading.value = true
  data.value = undefined
  try {
    const response = await request<{ workspace: WorkspaceView; value: AnnotationSpectrum }>(
      '/workspace/lipids/spectrum',
      {
        method: 'POST',
        workspace: current.workspace_id,
        body: {
          revision: current.revision,
          version: props.version,
          feature_id: props.featureId,
          sample: sample.value,
        },
      },
    )
    if (accept()) data.value = response.value
  } catch (cause) {
    if (accept()) failure.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (accept()) loading.value = false
  }
}
watch(
  identity,
  () => {
    relationPage.value = 0
    void load()
  },
  { immediate: true },
)
watch(
  () => props.samples,
  (values) => {
    if (sample.value && !values.includes(sample.value)) sample.value = ''
  },
)
const selected = computed(() => data.value?.peaks.find((p) => p.feature_id === props.featureId))
const selectedRelations = computed(
  () =>
    data.value?.relations.filter(
      (r) => !props.featureId || r.source === props.featureId || r.target === props.featureId,
    ) ?? [],
)
const visibleRelations = computed(() =>
  selectedRelations.value.slice(relationPage.value * 30, (relationPage.value + 1) * 30),
)
const colors = { selected: '#c0392b', isotope: '#2166ac', adduct: '#d27c12', unrelated: '#252525' }
const roleNames = {
  selected: 'Selected peak',
  isotope: 'Isotope',
  adduct: 'Adduct',
  unrelated: 'Measured features',
}
function featureTable(spectrum: AnnotationSpectrum) {
  const columns = ['feature_id', 'mz', 'intensity', 'label', 'role', 'ms2_status'] as const
  const quote = (value: unknown) => '"' + String(value ?? '').replaceAll('"', '""') + '"'
  return [
    columns.join(','),
    ...spectrum.peaks.map((peak) => columns.map((key) => quote(peak[key])).join(',')),
  ].join('\n')
}
const figure = computed<Figure | undefined>(() => {
  const spectrum = data.value
  if (!spectrum) return
  const traces: Record<string, unknown>[] = []
  const intensityMissing = spectrum.intensity_missing
  for (const role of ['unrelated', 'isotope', 'adduct', 'selected'] as const) {
    const peaks = spectrum.peaks.filter((p) => p.role === role)
    if (!peaks.length) continue
    if (!intensityMissing) {
      traces.push({
        type: 'scattergl',
        mode: 'lines',
        name: roleNames[role],
        showlegend: false,
        x: peaks.flatMap((p) => [p.mz, p.mz, null]),
        y: peaks.flatMap((p) => [0, p.intensity, null]),
        line: {
          color: colors[role],
          width: role === 'selected' ? 2.4 : role === 'unrelated' ? 0.8 : 1.6,
        },
        hoverinfo: 'skip',
        meta: { spectrum_role: 'observed', annotation_role: role },
      })
    }
    const labels = peaks.map((p) => {
      if (showNames.value && p.annotations?.length) {
        const multipleSources = new Set(p.annotations.map((a) => a.database_filename)).size > 1
        return [
          ...new Set(
            p.annotations.map((a) =>
              [
                `${a.display_name || a.name} ${a.adduct}${a.isotope_order ? ` M+${a.isotope_order}` : ''}`,
                showMS2.value
                  ? `${ms2Label(a.ms2_status)}${multipleSources ? ` (${a.database_filename})` : ''}`
                  : '',
              ]
                .filter(Boolean)
                .join('<br>'),
            ),
          ),
        ].join('<br>')
      }
      return [
        showNames.value && p.label ? p.label : p.mz.toFixed(4),
        showMS2.value && (p.candidate_ids.length || p.label) ? ms2Label(p.ms2_status) : '',
      ]
        .filter(Boolean)
        .join('<br>')
    })
    traces.push({
      type: 'scatter',
      mode: 'markers+text',
      name: roleNames[role],
      x: peaks.map((p) => p.mz),
      y: peaks.map((p) => (intensityMissing ? 0 : p.intensity)),
      customdata: peaks.map((p) => [
        p.feature_id,
        p.label || 'Unannotated',
        ms2Label(p.ms2_status),
      ]),
      text: labels,
      textposition: 'top center',
      textfont: { size: role === 'selected' ? 12 : 10, color: colors[role] },
      marker: {
        color: colors[role],
        size: role === 'selected' ? 9 : intensityMissing ? 6 : 4,
        symbol: intensityMissing ? 'line-ns-open' : 'circle',
      },
      hovertemplate:
        'Feature: %{customdata[0]}<br>m/z: %{x:.4f}<br>' +
        (intensityMissing ? 'Intensity: Not supplied' : 'Intensity: %{y:.1e}') +
        '<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>',
      meta: {
        spectrum_role: 'observed',
        annotation_role: role,
        label_kind: showNames.value ? 'annotation' : 'mz',
      },
    })
  }
  return {
    data: traces,
    layout: {
      title: { text: 'Feature annotation spectrum' },
      xaxis: {
        title: { text: 'm/z' },
        showline: true,
        linecolor: '#252525',
        ticks: 'outside',
        showgrid: false,
        zeroline: false,
      },
      yaxis: {
        title: { text: spectrum.intensity_label },
        showline: true,
        showgrid: false,
        zeroline: false,
        rangemode: intensityMissing ? 'normal' : 'tozero',
        ...(intensityMissing ? { showticklabels: false, range: [-0.2, 1] } : {}),
      },
      plot_bgcolor: '#fff',
      paper_bgcolor: '#fff',
      hovermode: 'closest',
      meta: {
        scmm_spectrum: true,
        spectrum_kind: spectrum.spectrum_kind,
        intensity_missing: intensityMissing,
        relative_intensity_allowed: spectrum.relative_intensity_allowed,
        dataset_token: spectrum.dataset_token,
        lipid_version: spectrum.version,
        lipid_review_revision: spectrum.review_revision,
        export_tables: { features: featureTable(spectrum) },
      },
    },
  }
})
function pointClick(event: { points: { customdata?: unknown }[] }) {
  const custom = event.points?.[0]?.customdata
  const id = Array.isArray(custom)
    ? String(custom[0] ?? '')
    : typeof custom === 'string'
      ? custom
      : ''
  if (id) emit('select', id)
}
function stateName(state: string) {
  return state === 'accepted' ? '已确认' : state === 'rejected' ? '已否定' : '待审核'
}
useViewState('annotation_spectrum', { sample, showNames, showMS2 })
</script>

<template>
  <section
    id="annotation-spectrum"
    class="annotation-spectrum task-section"
    aria-labelledby="annotation-spectrum-title"
  >
    <div class="section-heading">
      <h3 id="annotation-spectrum-title">谱图注释与关联峰</h3>
      <button class="preview" :disabled="loading || store.busy" @click="load">重新读取谱图</button>
    </div>
    <p class="muted">
      点击峰可定位候选并高亮同位素与加合关系；当前图展示特征位置及所选样本的平均强度。
    </p>
    <div class="spectrum-settings">
      <label
        >强度样本<select v-model="sample" :disabled="store.busy">
          <option value="">全部样本</option>
          <option v-for="value in samples" :key="value" :value="value">{{ value }}</option>
        </select></label
      >
      <label
        >峰标签<select v-model="showNames">
          <option :value="true">注释名称</option>
          <option :value="false">m/z</option>
        </select></label
      >
      <label
        >数据库二级匹配标签<select v-model="showMS2">
          <option :value="true">显示</option>
          <option :value="false">隐藏</option>
        </select></label
      >
    </div>
    <p v-if="failure" role="alert">
      {{ failure }} <button class="preview" @click="load">重试读取</button>
    </p>
    <p v-else-if="loading" role="status">正在读取谱图与关联关系…</p>
    <template v-if="data">
      <p class="muted">
        当前数据库：{{ data.database.label || data.database.filename }} · MS2
        状态按此注释版本使用的数据库显示；未提供信息不等于匹配失败。
      </p>
      <p v-if="data.intensity_missing" class="state-note">
        当前只有特征表，没有实测强度；图中标记仅表示 m/z 位置。
      </p>
      <p v-if="selected" class="selected-peak" aria-live="polite">
        选中 {{ selected.feature_id }} · m/z {{ selected.mz.toFixed(4) }} ·
        {{ selected.label || '未注释' }} · {{ ms2Label(selected.ms2_status) }} · 已确认关联
        {{
          (data.confirmed_linked_feature_ids ?? []).filter((id) => id !== selected?.feature_id)
            .length
        }}
        个峰
      </p>
      <PlotView
        v-if="figure"
        :figure="figure"
        name="annotation-spectrum"
        @point-click="pointClick"
      />
      <details v-if="selected?.annotations?.length">
        <summary>当前峰的候选与数据库二级证据（{{ selected.annotations.length }} 项）</summary>
        <div class="data-table">
          <table>
            <thead>
              <tr>
                <th>候选名称</th>
                <th>来源数据库</th>
                <th>加合形式</th>
                <th>同位素阶数</th>
                <th>二级状态</th>
                <th>依据</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="annotation in selected.annotations"
                :key="`${annotation.candidate_id}:${annotation.adduct}:${annotation.isotope_order}`"
              >
                <td>{{ annotation.display_name || annotation.name }}</td>
                <td>{{ annotation.database_filename || annotation.database_id }}</td>
                <td>{{ annotation.adduct }}</td>
                <td>M+{{ annotation.isotope_order }}</td>
                <td>{{ ms2Label(annotation.ms2_status) }}</td>
                <td>{{ annotation.manual_group_assertion ? '人工关联断言' : '数据库候选' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <details :open="!!featureId">
        <summary>审核关联关系（{{ selectedRelations.length }} 条）</summary>
        <p class="muted">
          已确认关系参与组内联动；待审核关系保留为候选。人工接受关系不替代化学鉴定。
        </p>
        <div class="data-table">
          <table>
            <thead>
              <tr>
                <th>关系</th>
                <th>来源峰</th>
                <th>关联峰</th>
                <th>样本</th>
                <th>候选来源</th>
                <th>审核状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="relation in visibleRelations" :key="relation.id">
                <td>{{ relation.type === 'isotope' ? '同位素' : '加合离子' }}</td>
                <td>
                  <button
                    class="preview"
                    :disabled="store.busy"
                    @click="emit('select', relation.source)"
                  >
                    {{ relation.source }}
                  </button>
                </td>
                <td>
                  <button
                    class="preview"
                    :disabled="store.busy"
                    @click="emit('select', relation.target)"
                  >
                    {{ relation.target }}
                  </button>
                </td>
                <td>
                  {{ relation.sample || (relation.type === 'adduct' ? '质量候选关系' : '未指定') }}
                </td>
                <td :title="relation.candidate_ids.join(' / ')">
                  {{
                    relation.name
                      ? `${relation.name} ${relation.adduct || ''}`
                      : relation.candidate_ids.join(' / ') || '离子目录关系'
                  }}
                </td>
                <td>{{ stateName(relation.review) }}</td>
                <td>
                  <div class="actions">
                    <button :disabled="store.busy" @click="emit('review', relation.id, 'accepted')">
                      接受关联</button
                    ><button
                      :disabled="store.busy"
                      @click="emit('review', relation.id, 'rejected')"
                    >
                      否定关联</button
                    ><button :disabled="store.busy" @click="emit('review', relation.id, 'pending')">
                      恢复待审核
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!selectedRelations.length" class="muted">当前峰没有可审核的关联关系。</p>
        <div v-if="selectedRelations.length > 30" class="actions">
          <button :disabled="relationPage === 0" @click="relationPage--">关联上一页</button
          ><span>{{ relationPage + 1 }} / {{ Math.ceil(selectedRelations.length / 30) }}</span
          ><button
            :disabled="(relationPage + 1) * 30 >= selectedRelations.length"
            @click="relationPage++"
          >
            关联下一页
          </button>
        </div>
      </details>
      <p v-if="data.review_conflicts.length" class="state-note">
        关联组存在 {{ data.review_conflicts.length }} 项候选冲突；请逐项审核，冲突峰保留待定。
      </p>
    </template>
  </section>
</template>

<style scoped>
.annotation-spectrum {
  min-width: 0;
  border-top: 1px solid var(--line, #dce2e9);
  margin-top: 16px;
  padding-top: 16px;
}
.spectrum-settings {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.spectrum-settings label {
  display: grid;
  gap: 4px;
  min-width: 150px;
}
.selected-peak {
  overflow-wrap: anywhere;
  border-left: 3px solid #c0392b;
  padding-left: 10px;
}
td .actions {
  min-width: 190px;
}
</style>
