import type { AnalysisOperation, PlotKind, ResultName } from './types'
import contract from './results.contract.json'

// Explicit browser contracts are checked against the application catalog.
export const operations = contract.operations as Record<
  AnalysisOperation,
  { result?: ResultName; plots: PlotKind[] }
>
export const resultPlots = contract.resultPlots as Record<ResultName, PlotKind[]>
export const resultDownloads: Record<ResultName, string> = contract.resultDownloads
