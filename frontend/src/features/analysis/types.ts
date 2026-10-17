import type { Component, InjectionKey } from 'vue'
import type { useAnalysis } from './composables/useAnalysis'
export type AnalysisOperation =
  | 'reduce'
  | 'cluster'
  | 'differential'
  | 'markers'
  | 'network'
  | 'train'
  | 'explain_shap'
  | 'save_latent'
export type ResultName = 'differential' | 'markers' | 'network' | 'supervised' | 'shap'
export type PlotKind =
  'embedding' | 'volcano' | 'violin' | 'network_plot' | 'roc' | 'pr' | 'calibration' | 'shap_plot'
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
