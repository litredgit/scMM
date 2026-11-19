<script setup lang="ts">
import { provide } from 'vue'
import { useAnalysis } from '../analysis/composables/useAnalysis'
import { analysisKey } from '../analysis/types'
import AnnotationEvidencePanel from '../analysis/modules/AnnotationEvidencePanel.vue'
const analysis = useAnalysis()
provide(analysisKey, analysis)
const { store } = analysis
</script>

<template>
  <div class="page-title">
    <div>
      <p class="eyebrow">特征注释 · 外部证据</p>
      <h1>外部注释与二级谱图</h1>
    </div>
    <RouterLink to="/annotation">返回谱图与人工审核 →</RouterLink>
  </div>
  <AnnotationEvidencePanel
    v-if="store.project?.dataset && store.project.dataset.quantitation_available !== false"
  />
  <section v-else class="card empty-state">
    <p>
      当前数据可在注释板块进行精确质量候选检索。外部注释与实测二级谱图匹配需要关联到定量数据集。
    </p>
    <RouterLink to="/annotation">选择或导入数据 →</RouterLink>
  </section>
</template>
