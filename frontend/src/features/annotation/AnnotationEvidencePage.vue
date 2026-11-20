<script setup lang="ts">
import AnnotationHeader from './AnnotationHeader.vue'
import AnnotationEvidencePanel from '../analysis/modules/AnnotationEvidencePanel.vue'
import IonsPage from '../ions/IonsPage.vue'
import { useWorkspace } from '../../stores/workspace'
const store = useWorkspace()
</script>

<template>
  <section class="module-home">
    <AnnotationHeader title="证据与导入" />
    <template v-if="store.project">
      <AnnotationEvidencePanel />
      <IonsPage surface="evidence" />
    </template>
  </section>
</template>
