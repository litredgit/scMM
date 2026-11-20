<script setup lang="ts">
import { computed } from 'vue'
import PlotView from '../../components/PlotView.vue'
import type { Figure } from '../../api/types'
import type { ProfileReview } from './profileReview'

const props = defineProps<{ result: ProfileReview }>()
const figure = computed<Figure | undefined>(() => {
  const profile = props.result.profile
  if (!profile) return
  const series = [
    ['observed', 'Observed', '#263b45'],
    ['parent_only', 'Parent only', '#b86814'],
    ['mixed', 'Two-ion fit', '#147b79'],
    ['residual', 'Residual', '#697b92'],
  ] as const
  const data = (['parent', 'overlap'] as const).flatMap((region, panel) => {
    const points = profile.region.flatMap((value, i) => (value === region ? [i] : []))
    const suffix = panel ? '2' : ''
    return series.map(([key, title, color]) => ({
      type: 'scatter',
      mode: 'lines',
      x: points.map((i) => profile.mz[i]),
      y: points.map((i) => profile[key][i]),
      xaxis: 'x' + suffix,
      yaxis: 'y' + suffix,
      name: title,
      legendgroup: key,
      showlegend: !panel,
      line: { color, width: key === 'observed' ? 2 : 1.5 },
    }))
  })
  return {
    data,
    layout: {
      height: 310,
      margin: { l: 65, r: 138, t: 22, b: 54 },
      grid: { rows: 1, columns: 2, pattern: 'independent', xgap: 0.14 },
      xaxis: { title: { text: 'Parent m/z' } },
      xaxis2: { title: { text: 'Overlap m/z' } },
      yaxis: { title: { text: 'Intensity' } },
      yaxis2: { matches: 'y' },
    },
  }
})
const percent = (value: number | undefined) =>
  value === undefined ? '—' : (value * 100).toFixed(2)
const intensity = (value?: number) => value?.toPrecision(4) ?? '—'
</script>

<template>
  <section class="profile-result" aria-label="原始谱复核结果">
    <p>
      {{ result.native_id || '原始扫描' }} · 索引 {{ result.scan_index }} ·
      {{ result.rt_seconds.toFixed(2) }} s · M+{{
        result.isotope_order
      }}
      主组分与竞争单同位素峰理论相差 {{ (result.separation_da * 1000).toFixed(2) }} mDa
      <template v-if="result.fwhm_da != null">
        · 半高宽 {{ (result.fwhm_da * 1000).toFixed(2) }} mDa（{{
          result.fwhm_source === 'entered' ? '手动填写' : '同扫描母峰'
        }}）
      </template>
      · 模板偏移 {{ result.offset_ppm }} ppm
    </p>
    <div class="profile-candidates">
      <span v-for="candidate in result.candidates" :key="candidate.candidate_id">
        {{ candidate.feature_id }} · {{ candidate.name }} {{ candidate.adduct }} · m/z
        {{ candidate.mono_mz.toFixed(6) }}
      </span>
    </div>
    <p v-if="result.status === 'unresolved'" class="state-note" role="status">
      {{ result.reason }}
    </p>
    <template v-else>
      <p>
        单母峰相对 RMSE {{ percent(result.parent_only_relative_rmse) }}% · 双组分相对 RMSE
        {{ percent(result.mixed_relative_rmse) }}% · 竞争组分峰高
        {{ intensity(result.competing_height) }}（模板扰动范围
        {{ result.competing_height_sensitivity?.map(intensity).join('–') }}）
      </p>
      <PlotView
        v-if="figure"
        :figure="figure"
        name="ms1-profile-review"
        legend="right"
        compact
        readonly
      />
      <p class="muted">峰高取决于选定模板。扰动范围反映模板敏感性，化学身份仍待审阅。</p>
    </template>
  </section>
</template>

<style scoped>
.profile-result p {
  margin: 5px 0;
}
.profile-candidates {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  overflow-wrap: anywhere;
}
</style>
