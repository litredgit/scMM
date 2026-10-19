<script setup lang="ts">
import { computed } from 'vue'
import PlotView from '../../components/PlotView.vue'
import type { Figure } from '../../api/types'
const props = defineProps<{
  points: {
    at: number
    instance: string
    metrics: Record<string, { mean: number; peak: number }>
  }[]
  metric: string
  bytes?: boolean
}>()
const figure = computed<Figure>(() => {
  const x: (string | null)[] = [],
    mean: (number | null)[] = [],
    peak: (number | null)[] = []
  const ids: (string[] | null)[] = []
  let previous: (typeof props.points)[number] | undefined
  for (const point of props.points) {
    const value = point.metrics[props.metric]
    if (!value) {
      if (previous) {
        x.push(null)
        mean.push(null)
        peak.push(null)
        ids.push(null)
      }
      previous = undefined
      continue
    }
    if (previous && (point.at - previous.at > 90 || point.instance !== previous.instance)) {
      x.push(null)
      mean.push(null)
      peak.push(null)
      ids.push(null)
    }
    x.push(new Date(point.at * 1000).toISOString())
    mean.push(value.mean / (props.bytes ? 1024 ** 3 : 1))
    peak.push(value.peak / (props.bytes ? 1024 ** 3 : 1))
    ids.push([point.instance, String(point.at)])
    previous = point
  }
  return {
    data: [
      {
        type: 'scatter',
        mode: 'lines',
        x,
        y: mean,
        customdata: ids,
        name: '分钟均值',
        line: { color: '#0072b2' },
      },
      {
        type: 'scatter',
        mode: 'lines',
        x,
        y: peak,
        customdata: ids,
        name: '分钟峰值',
        line: { color: '#666666', dash: 'dash' },
      },
    ],
    layout: {
      title: '最近 24 小时',
      paper_bgcolor: 'white',
      plot_bgcolor: 'white',
      xaxis: { title: { text: '时间（UTC）' }, showline: true },
      yaxis: { title: { text: props.bytes ? '用量（GiB）' : '用量' }, showline: true },
      meta: {
        metric: props.metric,
        unit: props.bytes ? 'GiB' : 'percent',
        raw_points: props.points,
      },
    },
  }
})
</script>
<template>
  <PlotView :figure="figure" :name="`monitor-${metric}`" readonly />
  <p class="muted">
    实线为分钟均值，虚线为分钟峰值；断线表示无采样或服务重启。下载包含完整采样来源。
  </p>
</template>
