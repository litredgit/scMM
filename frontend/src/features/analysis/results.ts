import type { AnalysisOperation, PlotKind, ResultName } from './types'
export const operations: Record<AnalysisOperation, { result?: ResultName; plots: PlotKind[] }> = {
  reduce: { plots: ['embedding'] },
  cluster: { plots: ['embedding'] },
  differential: { result: 'differential', plots: ['volcano'] },
  markers: { result: 'markers', plots: [] },
  network: { result: 'network', plots: ['network_plot'] },
  train: { result: 'supervised', plots: ['roc', 'pr', 'calibration', 'confusion'] },
  explain_shap: {
    result: 'shap',
    plots: ['shap_plot', 'shap_beeswarm', 'shap_waterfall', 'shap_dependence'],
  },
  save_latent: { plots: [] },
}
export const resultPlots: Record<ResultName, PlotKind[]> = {
  differential: ['volcano', 'violin'],
  markers: [],
  network: ['network_plot'],
  supervised: ['roc', 'pr', 'calibration', 'confusion'],
  shap: ['shap_plot', 'shap_beeswarm', 'shap_waterfall', 'shap_dependence'],
}
export const resultDownloads: Record<ResultName, string> = {
  differential: 'differential.csv',
  markers: 'markers.csv',
  network: 'network.csv',
  supervised: 'supervised.json',
  shap: 'shap.csv',
}
