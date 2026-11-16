<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
const props = defineProps<{ sample: string; summary?: Record<string, unknown> }>()
const model = defineModel<Record<string, unknown>>({ required: true })
const emit = defineEmits<{ edited: [] }>()
const store = useWorkspace()
const hints = ref<{ windows: number[][]; resolutions: number[]; note: string }>()
watch(
  () => props.sample,
  () => {
    hints.value = undefined
  },
)
async function read() {
  const sample = props.sample
  const value = await store.read<typeof hints.value>(
    `/raw/acquisition?sample_id=${encodeURIComponent(sample)}`,
  )
  if (sample === props.sample && value) hints.value = value
}
function bound(key: string, index: number, event: Event) {
  const bounds = [
    ...((model.value[key] as number[] | null) ??
      (key === 'rt_range'
        ? [Number(props.summary?.rt_min_seconds ?? 0), Number(props.summary?.rt_max_seconds ?? 0)]
        : [0, Number(props.summary?.scan_count ?? 1) - 1])),
  ]
  bounds[index] = Number((event.target as HTMLInputElement).value)
  if (bounds[0]! > bounds[1]!) bounds[1 - index] = bounds[index]!
  model.value[key] = bounds
  emit('edited')
}
</script>
<template>
  <section v-if="sample" class="parameter-section">
    <h4>逐文件提取范围与采集信息</h4>
    <p>
      滑块修改正式提取参数，需按页面所选作用域应用；不是原始图的显示缩放。RT 单位为秒，帧号从 0
      开始并包含 MS2 原始位置。
    </p>
    <template v-if="summary"
      ><div v-for="key in ['rt_range', 'frame_range']" :key="key">
        <span>{{ key === 'rt_range' ? '保留时间范围（秒）' : '原始帧范围' }}</span
        ><input
          v-for="i in [0, 1]"
          :key="i"
          type="range"
          :aria-label="`${key}_slider_${i}`"
          :min="key === 'rt_range' ? Number(summary.rt_min_seconds ?? 0) : 0"
          :max="
            key === 'rt_range'
              ? Number(summary.rt_max_seconds ?? 0)
              : Number(summary.scan_count ?? 1) - 1
          "
          :step="key === 'rt_range' ? 'any' : 1"
          :value="
            (model[key] as number[] | null)?.[i] ??
            (i === 0
              ? key === 'rt_range'
                ? Number(summary.rt_min_seconds ?? 0)
                : 0
              : key === 'rt_range'
                ? Number(summary.rt_max_seconds ?? 0)
                : Number(summary.scan_count ?? 1) - 1)
          "
          :disabled="store.busy"
          @input="bound(key, i, $event)"
        /></div
    ></template>
    <button class="preview" :disabled="store.busy" @click="read">读取采集信息</button
    ><template v-if="hints"
      ><p>采集质量窗：{{ hints.windows.map((v) => v.join('–')).join('；') || '未读取到' }} m/z</p>
      <p>分辨率记录值：{{ hints.resolutions.join('、') || '未读取到' }}</p>
      <p>{{ hints.note }}</p></template
    >
  </section>
</template>
