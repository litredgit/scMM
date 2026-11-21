import ExplorationPanel from './modules/ExplorationPanel.vue'
import StabilityPanel from './modules/StabilityPanel.vue'
import FeatureEmbeddingPanel from './modules/FeatureEmbeddingPanel.vue'
import FeatureScatterPanel from './modules/FeatureScatterPanel.vue'
import HeatmapPanel from './modules/HeatmapPanel.vue'
import ClusteringPanel from './modules/embedding/ClusteringPanel.vue'
import EmbeddingPanel from './modules/embedding/EmbeddingPanel.vue'
import DifferentialPanel from './modules/differential/DifferentialPanel.vue'
import { bundledAnalysis } from './bundledAnalysis'
import type { AnalysisModule } from './types'
export const analysisModules: readonly AnalysisModule[] = [
  {
    id: 'embedding',
    name: '降维',
    group: '探索 / QC',
    component: EmbeddingPanel,
    requires: ['matrix'],
  },
  {
    id: 'feature_scatter',
    name: '双特征散点',
    group: '探索 / QC',
    component: FeatureScatterPanel,
    requires: ['matrix'],
  },
  {
    id: 'feature_embedding',
    name: '特征距离嵌入',
    group: '探索 / QC',
    component: FeatureEmbeddingPanel,
    requires: ['matrix'],
  },
  {
    id: 'stability',
    name: '采集稳定性 QC',
    group: '探索 / QC',
    component: StabilityPanel,
    requires: ['matrix'],
  },
  {
    id: 'heatmap',
    name: '热图',
    group: '探索 / QC',
    component: HeatmapPanel,
    requires: ['matrix'],
  },
  {
    id: 'clustering',
    name: '聚类',
    group: '探索 / QC',
    component: ClusteringPanel,
    requires: ['matrix'],
  },
  {
    id: 'exploration',
    name: '相关性与集合',
    group: '统计比较',
    component: ExplorationPanel,
    requires: ['matrix'],
  },
  {
    id: 'differential',
    name: '差异与 Marker',
    group: '统计比较',
    component: DifferentialPanel,
    requires: ['matrix', 'observations'],
  },
  ...bundledAnalysis,
]
