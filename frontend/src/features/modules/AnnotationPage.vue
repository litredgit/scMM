<script setup lang="ts">
import { ref } from 'vue'
import AnnotationHeader from '../annotation/AnnotationHeader.vue'
import MethodPanel from '../methods/MethodPanel.vue'
import { useAnnotationSource } from '../annotation/useAnnotationSource'
import LipidPanel from '../preprocess/LipidPanel.vue'
import IonsPage from '../ions/IonsPage.vue'
import CompoundSourcePanel from '../ions/CompoundSourcePanel.vue'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
const { source, selectedTarget } = useAnnotationSource()
const groupsOpen = ref(false)
const groupsMounted = ref(false)
const annotationRun = ref(0)
function toggleGroups() {
  groupsMounted.value = true
  groupsOpen.value = !groupsOpen.value
}
</script>

<template>
  <section class="module-home">
    <MethodPanel v-if="source" kind="annotation" :source="source.id" @completed="annotationRun++" />
    <LipidPanel v-if="source" :key="annotationRun" :source="source">
      <template #grouping-action>
        <button
          class="preview"
          :aria-expanded="groupsOpen"
          :disabled="!source.quantitation_available"
          :title="source.quantitation_available ? '' : '需要测量定量矩阵'"
          @click="toggleGroups"
        >
          {{ groupsOpen ? '收起离子关系设置' : '生成离子关系' }}
        </button>
      </template>
      <template #grouping-settings>
        <IonsPage
          v-if="groupsMounted"
          v-show="groupsOpen"
          surface="review"
          :focus-feature="
            selectedTarget?.featureId ??
            (selectedTarget?.kind === 'feature' ? selectedTarget.id : '')
          "
        />
      </template>
      <template #group-search>
        <details v-if="source.id !== 'current'">
          <summary>使用本地化合物库</summary>
          <IonsPage surface="search" />
        </details>
      </template>
      <template #group-relations>
        <button class="preview" :disabled="!source.quantitation_available" @click="toggleGroups">
          {{ groupsOpen ? '收起离子组审核' : '查看离子组审核' }}
        </button>
      </template>
    </LipidPanel>
    <template v-else>
      <AnnotationHeader title="候选与关系审核" />
      <section class="card">
        <button class="preview" disabled title="当前缺少可用的实测 m/z 来源">查看完整谱图</button>
        <p>
          完整谱图需要独立 m/z 特征表或可访问的测量根。仅有源 L2 时可在定量视图核对 EC
          和代表离子映射。
        </p>
      </section>
      <CompoundSourcePanel v-if="store.project" />
    </template>
  </section>
</template>
