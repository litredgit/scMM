import EmbeddingPanel from './modules/embedding/EmbeddingPanel.vue'
import DifferentialPanel from './modules/differential/DifferentialPanel.vue'
import NetworkPanel from './modules/network/NetworkPanel.vue'
import SupervisedPanel from './modules/supervised/SupervisedPanel.vue'
import type { AnalysisModule } from './types'
export const analysisModules: readonly AnalysisModule[] = [
  {
    id: 'embedding',
    name: '降维与聚类',
    group: '探索',
    component: EmbeddingPanel,
    requires: ['matrix'],
  },
  {
    id: 'differential',
    name: '差异与 Marker',
    group: '统计',
    component: DifferentialPanel,
    requires: ['matrix', 'observations'],
  },
  { id: 'network', name: '相关网络', group: '探索', component: NetworkPanel, requires: ['matrix'] },
  {
    id: 'supervised',
    name: '监督与 SHAP',
    group: '建模',
    component: SupervisedPanel,
    requires: ['matrix', 'observations'],
  },
]
