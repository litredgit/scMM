<script setup lang="ts">
import { computed } from 'vue'
import type { DataTable } from '../../api/types'
const props = defineProps<{ before: DataTable; after: DataTable }>()
const statistics = [
  ['mean', '均值'],
  ['median', '中位数'],
  ['std', '标准差'],
  ['min', '最小值'],
  ['max', '最大值'],
] as const
const rows = computed(() => {
  const identity = (row: Record<string, unknown>) => JSON.stringify([row.source_path, row.metric])
  const after = new Map(props.after.rows.map((row) => [identity(row), row]))
  return props.before.rows.map((row) => ({ before: row, after: after.get(identity(row)) }))
})
function format(value: unknown, metric: unknown, signed = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const text =
    metric === '检出特征数'
      ? value.toLocaleString('en-US', { maximumFractionDigits: 1, useGrouping: false })
      : value.toExponential(1)
  return signed && value > 0 ? `+${text}` : text
}
function change(before: unknown, after: unknown) {
  return typeof before === 'number' && typeof after === 'number' ? after - before : undefined
}
</script>
<template>
  <p class="muted">
    按来源文件与指标逐项对照；检出特征数最多显示 1
    位小数，强度使用科学计数法。无候选细胞或无法估计时显示 —。
  </p>
  <div class="data-table">
    <table aria-label="操作前后 QC 对比">
      <thead>
        <tr>
          <th>来源文件</th>
          <th>指标</th>
          <th>统计量</th>
          <th>操作前</th>
          <th>候选后</th>
          <th>变化</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(row, i) in rows" :key="i">
          <tr v-for="([key, label], j) in statistics" :key="key">
            <td v-if="j === 0" :rowspan="statistics.length">
              {{ row.before.source_file
              }}<HelpTip
                :text="String(row.before.source_path ?? row.before.source_file)"
                label="完整路径"
              />
            </td>
            <td v-if="j === 0" :rowspan="statistics.length">{{ row.before.metric }}</td>
            <td>{{ label }}</td>
            <td>{{ format(row.before[key], row.before.metric) }}</td>
            <td>{{ format(row.after?.[key], row.before.metric) }}</td>
            <td>
              {{ format(change(row.before[key], row.after?.[key]), row.before.metric, true) }}
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
