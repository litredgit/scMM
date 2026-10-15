<script setup lang="ts">
import type { DataTable } from '../api/types'
const labels: Record<string, string> = {
  source_file: '文件名',
  reference_mz: '参考 m/z',
  cell_count: '细胞数',
  metric: '指标',
  mean: '均值',
  median: '中位数',
  std: '标准差',
  min: '最小值',
  max: '最大值',
}
const headerHelp: Record<string, string> = {
  source_file: '按原始来源文件分组；文件名后的问号可查看完整路径。同名文件仍按不同来源分别统计。',
  reference_mz: '该文件的参考离子 m/z；参考强度来自提取记录，不随当前矩阵归一化重新计算。',
  cell_count: '当前矩阵中属于该来源文件的细胞数，不等于独立生物重复数。',
  metric:
    '总强度为当前矩阵每细胞强度之和；检出特征数按当前强度 >0 计算；参考强度保留提取时的参考通道记录。',
  mean: '该来源文件内此指标的算术平均值；表格格式仅影响显示，下载保留原始精度。',
  median: '该来源文件内此指标的中位数；一半细胞不高于此值。',
  std: '该来源文件内此指标的样本标准差（ddof=1）；只有一个有效细胞时无法估计。',
  min: '该来源文件内此指标的最小有效值。',
  max: '该来源文件内此指标的最大有效值。',
  fdr: '对全部检验特征进行 Benjamini–Hochberg 校正后的 p 值；只筛选图形不会重新校正。',
  p_value: '未进行多重检验校正的 p 值，不是效应量或结论正确的概率。',
  log2_fold_change: 'group_a 相对 group_b 的 log2 丰度倍数变化；正数表示分子组更高。',
  operation: '成功应用到当前数据的处理操作。恢复历史层与恢复完整起点的语义不同。',
  parameters: '该次实际执行使用的参数记录；不是当前尚未应用的表单值。',
  revision: '数据集处理修订号，区别于项目磁盘保存修订。',
  shape: '该次处理后的细胞数与特征数；行对应细胞，列对应特征。',
  at: '处理记录的时间戳；时间戳携带原始时区信息。',
  mean_abs_shap: '跨解释样本及类别平均的 SHAP 绝对贡献，不表示效应方向或因果。',
}
const props = withDefaults(defineProps<{ table: DataTable; qc?: boolean }>(), { qc: false })
function formatted(value: unknown, key: string, row: Record<string, unknown>) {
  if (key === 'extraction_method' && value === 'snr_v1') return 'snr'
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    if (key === 'p_value' || key === 'fdr') return value === 0 ? '0' : value.toExponential(2)
    if (
      props.qc &&
      /强度|intensity/.test(String(row.metric)) &&
      ['mean', 'median', 'std', 'min', 'max'].includes(key)
    )
      return value.toExponential(3)
    if (props.qc && row.metric === '检出特征数')
      return value.toLocaleString('en-US', { maximumFractionDigits: 1, useGrouping: false })
    if (/intensity|mean_abs_shap|mean_a|mean_b/.test(key)) return value.toExponential(3)
    return Number.isInteger(value)
      ? String(value)
      : value.toLocaleString('en-US', { maximumSignificantDigits: 6, useGrouping: false })
  }
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
function span(table: DataTable, index: number) {
  const row = table.rows[index]!
  if (index > 0 && table.rows[index - 1]?.source_path === row.source_path) return 0
  let end = index + 1
  while (end < table.rows.length && table.rows[end]?.source_path === row.source_path) end++
  return end - index
}
</script>
<template>
  <div class="data-table">
    <table>
      <thead>
        <tr>
          <th v-for="key in table.columns.filter((c) => c !== 'source_path')" :key="key">
            <FieldLabel
              :name="qc ? (labels[key] ?? key) : key"
              :help-key="key"
              :text="headerHelp[key]"
            />
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in table.rows" :key="i">
          <template v-for="key in table.columns.filter((c) => c !== 'source_path')" :key="key"
            ><td
              v-if="
                !qc ||
                !['source_file', 'reference_mz', 'cell_count'].includes(key) ||
                span(table, i) > 0
              "
              :rowspan="
                props.qc && ['source_file', 'reference_mz', 'cell_count'].includes(key)
                  ? span(table, i)
                  : 1
              "
            >
              {{ formatted(row[key], key, row)
              }}<HelpTip
                v-if="key === 'source_file'"
                :text="String(row.source_path ?? row.source_file)"
                label="完整路径"
              /></td
          ></template>
        </tr>
      </tbody>
    </table>
    <p v-if="!table.rows.length" class="muted">暂无记录</p>
  </div>
  <p v-if="table.total > table.rows.length" class="muted">
    当前显示 {{ table.rows.length }} / {{ table.total }} 行；下载保留完整精度和全部记录。
  </p>
</template>
