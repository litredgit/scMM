export type OperationOutcome<T> =
  | { status: 'succeeded'; value: T }
  | { status: 'failed'; error: string }
  | { status: 'skipped'; reason: 'busy'; active: string }
  | { status: 'stale' }

export type OperationPhase =
  | 'submitting'
  | 'running'
  | 'reading'
  | 'collecting'
  | 'refreshing'
  | 'plotting'
  | 'recovering'
  | 'downloading'
  | 'succeeded'
  | 'failed'
  | 'stale'
export type OperationDetails = { label: string; phase: OperationPhase }
export type OperationState = OperationDetails & { id: number }
export type OperationScope = {
  isCurrent(): boolean
  update(details: Partial<OperationDetails>): void
}
export const phaseLabels: Record<OperationPhase, string> = {
  submitting: '提交中',
  running: '执行中',
  reading: '读取中',
  collecting: '收集结果中',
  refreshing: '刷新状态中',
  plotting: '绘图中',
  recovering: '恢复状态中',
  downloading: '准备下载中',
  succeeded: '已完成',
  failed: '失败',
  stale: '已过期',
}
export function operationValue<T>(outcome: OperationOutcome<T>): T | undefined {
  return outcome.status === 'succeeded' ? outcome.value : undefined
}
const operations: Record<string, string> = {
  reduce: '降维',
  cluster: '聚类',
  differential: '差异分析',
  markers: '标记分析',
  network: '相关网络',
  train: '训练模型',
  explain_shap: 'SHAP 解释',
  save_latent: '保存潜变量',
  subset: '筛选细胞与特征',
  normalize: '归一化',
  impute: '缺失值填补',
  filter: '过滤数据',
  restore: '恢复历史层',
  reset: '恢复完整起点',
  remove_outliers: '离群检测',
}
/** Product labels only; HTTP paths and internal parameter keys stay out of task feedback. */
export function operationDetails(
  path: string,
  body: Record<string, unknown> = {},
): OperationDetails {
  if (path === '/analysis/operation')
    return {
      label: operations[String(body.operation)] ?? '分析数据',
      phase: body.preview ? 'reading' : 'running',
    }
  if (path.includes('/plot') || path.includes('/figure'))
    return { label: '绘制图形', phase: 'plotting' }
  if (path.endsWith('/collect')) return { label: '接收计算结果', phase: 'collecting' }
  if (path === '/extraction/review')
    return { label: body.compare ? '比较提取 QC' : '建立当前数据集', phase: 'collecting' }
  if (path === '/extraction/start') return { label: '启动后台提取', phase: 'submitting' }
  if (path === '/extraction/stop') return { label: '停止后续样本', phase: 'submitting' }
  if (path === '/raw/preview') return { label: '启动细胞预览', phase: 'submitting' }
  if (path === '/raw/diagnostic') return { label: '原始信号诊断', phase: 'running' }
  if (path.startsWith('/lipids'))
    return {
      label: '脂质注释与同位素分析',
      phase: path.endsWith('/query') || path.endsWith('/database') ? 'reading' : 'running',
    }
  if (path === '/raw/open') return { label: '打开原始文件', phase: 'reading' }
  if (path.startsWith('/dataset/merge'))
    return {
      label: path.endsWith('/apply') ? '合并已处理矩阵' : '检查矩阵合并',
      phase: path.endsWith('/apply') ? 'running' : 'reading',
    }
  if (path === '/project/save') return { label: '保存项目', phase: 'submitting' }
  if (path === '/project/open') return { label: '打开项目', phase: 'reading' }
  if (path === '/project/close') return { label: '关闭项目', phase: 'submitting' }
  if (path === '/project') return { label: '创建项目', phase: 'submitting' }
  if (path === '/dataset/import') return { label: '导入独立结果', phase: 'reading' }
  if (path.startsWith('/samples')) return { label: '更新样本信息', phase: 'submitting' }
  if (path.startsWith('/parameters')) return { label: '更新处理参数', phase: 'submitting' }
  if (path.startsWith('/saved')) return { label: '管理已保存内容', phase: 'running' }
  if (path.startsWith('/analysis/time')) return { label: '时间与趋势分析', phase: 'running' }
  return { label: '处理当前操作', phase: 'running' }
}
