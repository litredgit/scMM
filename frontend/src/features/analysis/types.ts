import type { Component, InjectionKey } from 'vue'
import type contract from './results.contract.json'
import type { useAnalysis } from './composables/useAnalysis'
export type AnalysisOperation = keyof typeof contract.operations
export type ResultName = keyof typeof contract.resultPlots
export type PlotKind =
  | 'embedding'
  | 'volcano'
  | 'violin'
  | 'network_plot'
  | 'roc'
  | 'pr'
  | 'calibration'
  | 'shap_plot'
  | 'confusion'
  | 'shap_beeswarm'
  | 'shap_waterfall'
  | 'shap_dependence'
export interface AnalysisTransport {
  isCurrent?(): boolean
  read<T>(path: string): Promise<T | undefined>
  mutate(path: string, body: Record<string, unknown>): Promise<unknown>
  command<T>(path: string, body: Record<string, unknown>): Promise<T | undefined>
}
export interface AnalysisModule {
  id: string
  name: string
  group: string
  component: Component
  requires: readonly string[]
}
export const analysisKey: InjectionKey<ReturnType<typeof useAnalysis>> = Symbol('analysis')
