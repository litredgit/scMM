<script setup lang="ts">
import { provide } from 'vue'
import { useAnalysis } from './composables/useAnalysis'
import { analysisKey } from './types'
import { analysisModules } from './registry'
const analysis = useAnalysis()
provide(analysisKey, analysis)
const { store, tab, legend, saveSettings, reloadAnalysis } = analysis
</script>
<template>
  <section v-if="store.project?.dataset">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 05 / 分析</p>
        <h1>探索与分析</h1>
        <p>
          {{ store.project.dataset.cells }} 细胞 × {{ store.project.dataset.features }} 特征 ·
          结果随数据与依赖字段失效。
        </p>
      </div>
      <span class="step-badge">05 / 06</span>
    </div>
    <div class="card">
      <div class="section-heading">
        <label class="field"
          ><FieldLabel name="图例" /><select aria-label="图例" v-model="legend">
            <option value="right">图右侧</option>
            <option value="top_left">图内左上</option>
            <option value="top_right">图内右上</option>
            <option value="bottom_left">图内左下</option>
            <option value="bottom_right">图内右下</option>
            <option value="hidden">隐藏</option>
          </select></label
        >
      </div>
      <button class="primary" :disabled="store.busy" @click="saveSettings">应用视图设置</button>
      <button :disabled="store.busy" @click="reloadAnalysis">重新读取分析状态</button>
    </div>
    <div class="analysis-layout">
      <nav class="analysis-navigation" aria-label="分析功能">
        <button
          v-for="entry in analysisModules"
          :key="entry.id"
          :aria-label="entry.name"
          :class="{ selected: tab === entry.id }"
          :aria-current="tab === entry.id ? 'page' : undefined"
          @click="tab = entry.id"
        >
          {{ entry.name }}<small>{{ entry.group }}</small>
        </button>
      </nav>
      <label class="analysis-mobile field"
        >分析功能<select aria-label="分析功能" v-model="tab">
          <option v-for="entry in analysisModules" :key="entry.id" :value="entry.id">
            {{ entry.name }}
          </option>
        </select></label
      >
      <div class="analysis-content">
        <component
          v-for="entry in analysisModules"
          :key="entry.id"
          :is="entry.component"
          v-show="tab === entry.id"
        />
      </div>
    </div>
  </section>
  <div v-else class="card empty-state">
    <h1>尚未建立当前数据集</h1>
    <RouterLink to="/extraction">前往提取审核 →</RouterLink>
  </div>
</template>
<style scoped>
.analysis-layout {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}
.analysis-navigation {
  display: grid;
  gap: 0.5rem;
  position: sticky;
  top: 1rem;
}
.analysis-navigation button {
  text-align: left;
}
.analysis-navigation .selected {
  color: var(--blue);
  border-color: var(--blue);
  background: #eff6ff;
}
.analysis-navigation small {
  display: block;
  color: var(--muted);
}
.analysis-content {
  min-width: 0;
}
.analysis-mobile {
  display: none;
}
@media (max-width: 800px) {
  .analysis-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .analysis-navigation {
    display: none;
  }
  .analysis-mobile {
    display: grid;
  }
}
</style>
