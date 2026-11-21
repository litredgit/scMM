import { defineAsyncComponent } from 'vue'
import type { AnalysisModule } from './types'

export const bundledAnalysis: readonly AnalysisModule[] = [
  {
    id: 'network',
    plugin: 'network',
    name: '相关网络',
    group: '探索 / QC',
    component: defineAsyncComponent(() => import('./modules/network/NetworkPanel.vue')),
    requires: ['matrix'],
  },
  {
    id: 'supervised',
    plugin: 'supervised',
    name: '监督与 SHAP',
    group: '监督建模',
    component: defineAsyncComponent(() => import('./modules/supervised/SupervisedPanel.vue')),
    requires: ['matrix', 'observations'],
  },
  {
    id: 'time',
    plugin: 'time',
    name: '伪时间与轨迹',
    group: '时间与趋势',
    component: defineAsyncComponent(() => import('./modules/TimePanel.vue')),
    requires: ['matrix'],
  },
]
