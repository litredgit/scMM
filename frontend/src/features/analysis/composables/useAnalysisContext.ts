import { inject } from 'vue'
import { analysisKey } from '../types'
export function useAnalysisContext() {
  const context = inject(analysisKey)
  if (!context) throw new Error('分析面板必须位于 AnalysisPage 内。')
  return context
}
