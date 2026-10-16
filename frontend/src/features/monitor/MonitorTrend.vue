<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
const svg = ref<SVGSVGElement>()
const width = ref(800)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(() => {
    width.value = Math.max(220, svg.value?.clientWidth ?? 800)
  })
  if (svg.value) observer.observe(svg.value)
})
onUnmounted(() => observer?.disconnect())
const props = defineProps<{
  points: {
    at: number
    instance: string
    metrics: Record<string, { mean: number; peak: number }>
  }[]
  metric: string
  bytes?: boolean
}>()
const max = computed(() =>
  Math.max(1, ...props.points.map((p) => p.metrics[props.metric]?.peak ?? 0)),
)
const paths = computed(() => {
  const end = Date.now() / 1000,
    start = end - 86400
  const result: { mean: string; peak: string; x: number; y: number }[] = []
  let last: (typeof props.points)[number] | undefined
  for (const point of props.points) {
    const value = point.metrics[props.metric]
    if (!value) {
      last = undefined
      continue
    }
    if (!last || point.at - last.at > 90 || point.instance !== last.instance)
      result.push({ mean: '', peak: '', x: 0, y: 0 })
    const item = result[result.length - 1]!
    const x = 40 + Math.max(0, (point.at - start) / 86400) * (width.value - 80)
    const y = (v: number) => 170 - Math.min(1, v / max.value) * 140
    for (const key of ['mean', 'peak'] as const)
      item[key] += `${item[key] ? 'L' : 'M'}${x.toFixed(1)},${y(value[key]).toFixed(1)} `
    item.x = x
    item.y = y(value.mean)
    last = point
  }
  return result
})
const ceiling = computed(() =>
  props.bytes ? `${(max.value / 1024 ** 3).toFixed(1)} GiB` : max.value.toFixed(1),
)
</script>
<template>
  <svg
    ref="svg"
    class="trend"
    :viewBox="`0 0 ${width} 200`"
    role="img"
    aria-label="最近24小时每分钟均值与峰值曲线；断线表示缺少采样或服务重启"
  >
    <text x="5" y="24">{{ ceiling }}</text>
    <text x="22" y="174">0</text>
    <path :d="`M40,30 V170 H${width - 30}`" class="axis" />
    <g v-for="(segment, i) in paths" :key="i">
      <path :d="segment.peak" class="peak" />
      <path :d="segment.mean" class="mean" />
      <circle :cx="segment.x" :cy="segment.y" r="2" fill="#2563eb" />
    </g>
    <text x="40" y="194">24 小时前</text>
    <text :x="width - 64" y="194">现在</text>
  </svg>
  <p class="muted">
    蓝线：分钟均值 · 虚线：分钟峰值 · 断线：无采样或服务重启。无历史数据时保持空白。
  </p>
</template>
<style scoped>
.trend {
  width: 100%;
  height: 200px;
}
path {
  fill: none;
  stroke-width: 2;
}
.axis {
  stroke: #cbd5e1;
  stroke-width: 1;
}
.mean {
  stroke: #2563eb;
}
.peak {
  stroke: #64748b;
  stroke-dasharray: 4 3;
}
text {
  font-size: 12px;
  fill: #64748b;
}
</style>
