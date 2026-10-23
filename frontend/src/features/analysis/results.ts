import type { AnalysisOperation, PlotKind, ResultName } from './types'
import contract from './results.contract.json'

// Explicit browser contracts are checked against the application catalog.
export const operations = contract.operations as Record<
  AnalysisOperation,
  { result?: ResultName; plots: PlotKind[] }
>
export const resultPlots = contract.resultPlots as Record<ResultName, PlotKind[]>
export const resultDownloads: Record<ResultName, string> = contract.resultDownloads

export const resultTitles: Record<ResultName, string> = {
  differential: '两组差异分析表',
  markers: '各组标记特征表',
  network: '特征相关网络表',
  supervised: '监督模型诊断报告',
  shap: 'SHAP 特征贡献表',
}
