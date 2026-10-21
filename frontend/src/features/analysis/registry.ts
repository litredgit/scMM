import StabilityPanel from './modules/StabilityPanel.vue'
import FeatureEmbeddingPanel from './modules/FeatureEmbeddingPanel.vue'
import FeatureScatterPanel from './modules/FeatureScatterPanel.vue'
import HeatmapPanel from './modules/HeatmapPanel.vue'
import ClusteringPanel from './modules/embedding/ClusteringPanel.vue'
import LipidPanel from '../preprocess/LipidPanel.vue'
import EmbeddingPanel from './modules/embedding/EmbeddingPanel.vue'
import DifferentialPanel from './modules/differential/DifferentialPanel.vue'
import NetworkPanel from './modules/network/NetworkPanel.vue'
import SupervisedPanel from './modules/supervised/SupervisedPanel.vue'
import type { AnalysisModule } from './types'
export const analysisModules: readonly AnalysisModule[] = [
  {
    id: 'embedding',
    name: '降维',
    group: '探索',
    component: EmbeddingPanel,
    requires: ['matrix'],
  },
  {
    id: 'feature_scatter',
    name: '双特征散点',
    group: '探索',
    component: FeatureScatterPanel,
    requires: ['matrix'],
  },
  {
    id: 'feature_embedding',
    name: '特征距离嵌入',
    group: '探索',
    component: FeatureEmbeddingPanel,
    requires: ['matrix'],
  },
  {
    id: 'stability',
    name: '采集稳定性 QC',
    group: '探索',
    component: StabilityPanel,
    requires: ['matrix'],
  },
  { id: 'heatmap', name: '热图', group: '探索', component: HeatmapPanel, requires: ['matrix'] },
  {
    id: 'clustering',
    name: '聚类',
    group: '探索',
    component: ClusteringPanel,
    requires: ['matrix'],
  },
  {
    id: 'lipids',
    name: '注释与同位素',
    group: '注释',
    component: LipidPanel,
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
