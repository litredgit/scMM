<script setup lang="ts">
import CellSpectraPanel from './components/CellSpectraPanel.vue'
import { computed, provide } from 'vue'
import { useAnalysis } from './composables/useAnalysis'
import { analysisKey } from './types'
import { analysisModules } from './registry'
const analysis = useAnalysis()
provide(analysisKey, analysis)
const {
  store,
  info,
  tab,
  legend,
  saveSettings,
  reloadAnalysis,
  invalidated,
  recovery,
  retryPresentation,
} = analysis
const names: Record<string, string> = {
  differential: '差异分析',
  markers: 'Marker',
  network: '相关网络',
  supervised: '监督模型',
  shap: 'SHAP',
}
const resultStates = computed(() => {
  const relevant =
    tab.value === 'differential'
      ? ['differential', 'markers']
      : tab.value === 'supervised'
        ? ['supervised', 'shap']
        : tab.value === 'network'
          ? ['network']
          : []
  return relevant.map((name) => ({
    name: names[name],
    state: invalidated.value[name]
      ? '需重算 · 已失效'
      : !info.value?.results.includes(name)
        ? '无结果'
        : info.value.live_results.includes(name)
          ? '有效'
          : '重载只读',
    reason:
      invalidated.value[name] ??
      (!info.value?.results.includes(name)
        ? '设置输入后运行计算。'
        : info.value.live_results.includes(name)
          ? '当前结果可查看及下载。'
          : '已保存报告可查看及下载；模型与 SHAP 扩展需重新训练。'),
  }))
})
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
    <div class="analysis-toolbar actions" aria-label="分析视图工具">
      <div>
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
      <button :disabled="store.busy" @click="reloadAnalysis" class="preview">
        重新读取分析状态
      </button>
    </div>
    <p class="state-note" role="status">
      {{
        store.drafts['分析设置']
          ? '未应用草稿：点击“应用视图设置”记入工作区；保存项目也会纳入当前分析设置，但不启动计算。'
          : store.project.unsaved
            ? '已应用未保存：请主动保存项目。'
            : '已保存：分析设置已写入项目。'
      }}
    </p>
    <div v-if="recovery" class="state-note" role="status">
      {{ recovery.message
      }}<button class="preview" :disabled="store.busy" @click="retryPresentation">
        仅重试读取与绘图
      </button>
    </div>
    <p v-if="store.busy" role="status" class="state-note">{{ store.operationMessage }}</p>
    <div v-for="state in resultStates" :key="state.name" class="result-state" role="status">
      <strong>{{ state.name }} · {{ state.state }}</strong> · {{ state.reason }}
    </div>
    <p v-if="!info" role="status">正在读取当前数据的分析状态…</p>
    <div v-else class="analysis-layout">
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
    <CellSpectraPanel />
  </section>
  <div v-else class="card empty-state">
    <h1>尚未建立当前数据集</h1>
    <RouterLink to="/extraction">前往提取审核 →</RouterLink>
  </div>
</template>
<style scoped>
.analysis-layout {
  display: grid;
  grid-template-columns: 170px minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}
.analysis-navigation {
  display: grid;
  gap: 0.5rem;
  position: sticky;
  top: 7rem;
}
.analysis-navigation button {
  text-align: left;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
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
