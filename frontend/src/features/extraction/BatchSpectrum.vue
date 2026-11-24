<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Batch, Figure } from '../../api/types'
import { useReadScope } from '../../api/readScope'
import { openCsvText } from '../../api/csvExport'
import PlotView from '../../components/PlotView.vue'
import { useWorkspace } from '../../stores/workspace'

type Feature = {
  mz: number
  status: 'candidate' | 'retained' | 'unretained' | 'outside'
  retained_samples: number
  detected_cells: number
  summed_intensity: number | null
}
type Spectrum = {
  figure: Figure
  features: Feature[]
  contributors: string[]
  source: { name: string } | null
}

const props = defineProps<{ batch: Batch }>()
const store = useWorkspace()
const sample = ref('')
const spectrum = ref<Spectrum>()
const plot = ref<InstanceType<typeof PlotView>>()
const search = ref('')
const filter = ref('')
const page = ref(0)
const name = ref('')
const samples = computed(() => props.batch.samples.filter((row) => row.spectrum_sha256))
const available = computed(() => !!props.batch.spectrum_sha256 || samples.value.length > 0)
watch(
  samples,
  (available) => {
    if (!props.batch.spectrum_sha256 && !available.some((row) => row.id === sample.value))
      sample.value = available[0]?.id ?? ''
  },
  { immediate: true },
)
const context = () => [
  store.current?.workspace_id,
  store.project?.path,
  props.batch.path,
  sample.value,
]
const reads = useReadScope(context)
const labels = {
  candidate: '候选峰',
  retained: '已保留',
  unretained: '未保留',
  outside: '提取范围外',
}
const visible = computed(() =>
  (spectrum.value?.features ?? []).filter(
    (row) =>
      (!filter.value || row.status === filter.value) &&
      String(row.mz).includes(search.value.trim()),
  ),
)
watch([search, filter], () => (page.value = 0))
watch(sample, () => {
  spectrum.value = undefined
  page.value = 0
})

async function draw() {
  const accept = reads.begin()
  const result = await store.inspect<{ value: Spectrum }>(
    '/extraction/spectrum',
    { path: props.batch.path, sample_id: sample.value || null },
    accept,
  )
  if (accept() && result) {
    spectrum.value = result.value
    name.value = `${sample.value ? samples.value.find((row) => row.id === sample.value)?.name : '批次'} m/z 清单`
    page.value = 0
  }
}

async function saveList() {
  const result = await store.command('/extraction/spectrum/save-list', {
    path: props.batch.path,
    sample_id: sample.value || null,
    name: name.value,
  })
  if (result) store.notice = '清单已加入此项目的特征来源。'
}

function exportFeatures() {
  const source = spectrum.value
  const meta = source?.figure.layout.meta as { export_tables?: { features?: string } } | undefined
  if (meta?.export_tables?.features)
    openCsvText(
      'extraction-features.csv',
      meta.export_tables.features,
      () => source === spectrum.value,
    )
}
</script>

<template>
  <section class="batch-spectrum">
    <div class="actions">
      <h3>叠加谱与特征</h3>
      <template v-if="available">
        <label v-if="samples.length" class="inline-field">
          谱图来源
          <select v-model="sample" :disabled="store.busy">
            <option value="" :disabled="!batch.spectrum_sha256">批次叠加谱</option>
            <option v-for="row in samples" :key="row.id" :value="row.id">{{ row.name }}</option>
          </select>
        </label>
        <button
          class="preview"
          :disabled="store.busy || (!sample && !batch.spectrum_sha256)"
          @click="spectrum ? (spectrum = undefined) : draw()"
        >
          {{ spectrum ? '收起叠加谱' : '查看叠加谱' }}
        </button>
      </template>
    </div>
    <p v-if="!available" class="muted">此批次没有叠加谱产物。新批次会记录叠加谱及特征。</p>
    <template v-if="spectrum">
      <p class="muted">
        {{ spectrum.source?.name ?? '叠加谱寻峰' }} · 合谱样本
        {{ spectrum.contributors.join('、') }}
      </p>
      <div class="spectrum-grid">
        <PlotView ref="plot" :figure="spectrum.figure" name="extraction-summed-spectrum" />
        <section class="feature-table">
          <div class="actions">
            <input v-model="search" aria-label="查找 m/z" placeholder="查找 m/z" />
            <select v-model="filter" aria-label="特征状态">
              <option value="">全部特征</option>
              <option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option>
            </select>
          </div>
          <div class="feature-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>m/z</th>
                  <th>状态</th>
                  <th>样本数</th>
                  <th>检出细胞</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in visible.slice(page * 25, (page + 1) * 25)" :key="row.mz">
                  <td>
                    <button
                      v-if="row.summed_intensity !== null && row.status !== 'outside'"
                      :title="String(row.mz)"
                      @click="plot?.focusMz(row.mz)"
                    >
                      {{ row.mz.toPrecision(10) }}
                    </button>
                    <span v-else :title="String(row.mz)">{{ row.mz.toPrecision(10) }}</span>
                  </td>
                  <td>{{ labels[row.status] }}</td>
                  <td>{{ row.retained_samples }}</td>
                  <td>{{ row.detected_cells }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="actions">
            <button :disabled="page === 0" @click="page--">上一页</button>
            <span
              >{{ visible.length ? page * 25 + 1 : 0 }}–{{
                Math.min((page + 1) * 25, visible.length)
              }}
              / {{ visible.length }}</span
            >
            <button :disabled="(page + 1) * 25 >= visible.length" @click="page++">下一页</button>
          </div>
          <div class="actions">
            <input v-model="name" maxlength="100" aria-label="保存的 m/z 清单名称" />
            <button class="save" :disabled="store.busy || !name.trim()" @click="saveList">
              保存为清单
            </button>
            <button class="download" @click="exportFeatures">特征 CSV 导出</button>
          </div>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.batch-spectrum h3 {
  margin: 0;
}
.spectrum-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(0, 2fr) minmax(290px, 1fr);
  align-items: start;
}
.feature-table {
  display: grid;
  gap: 8px;
}
.feature-table-scroll {
  max-height: 410px;
  overflow: auto;
}
.feature-table-scroll thead {
  position: sticky;
  top: 0;
}
.feature-table input {
  width: 125px;
}
.feature-table select {
  width: 150px;
}
.feature-table td button {
  padding: 2px 5px;
  font-variant-numeric: tabular-nums;
}
</style>
