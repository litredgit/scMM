<script setup lang="ts">
import DataViewSelector from '../ions/DataViewSelector.vue'
import CellSpectraPanel from './components/CellSpectraPanel.vue'
import { computed, provide, watch } from 'vue'
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
const moduleGroups = [...new Set(analysisModules.map((entry) => entry.group))]
watch(
  tab,
  (value) => {
    if (!analysisModules.some((entry) => entry.id === value)) tab.value = 'embedding'
  },
  { immediate: true },
)
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
  <DataViewSelector />
  <section
    v-if="store.project?.dataset && store.project.dataset.quantitation_available !== false"
    class="analysis-page"
  >
    <div class="page-title">
      <div>
        <h1>探索与分析</h1>
        <p>
          {{ store.project.dataset.cells }}
          {{ store.project.dataset.observation_kind === 'sample' ? '样本' : '细胞' }} ×
          {{ store.project.dataset.features }} 特征 · 结果随数据与依赖字段失效。
        </p>
      </div>
      <RouterLink to="/annotation" class="muted">查看特征注释 →</RouterLink>
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
      <Teleport to="#method-menu"
        ><nav class="analysis-navigation" aria-label="分析功能">
          <div v-for="group in moduleGroups" :key="group" class="analysis-group">
            <h2 class="analysis-group-name">{{ group }}</h2>
            <div class="actions">
              <button
                v-for="entry in analysisModules.filter((entry) => entry.group === group)"
                :key="entry.id"
                :aria-label="entry.name"
                :class="{ selected: tab === entry.id }"
                :aria-current="tab === entry.id ? 'page' : undefined"
                @click="tab = entry.id"
              >
                {{ entry.name }}
              </button>
            </div>
          </div>
        </nav></Teleport
      >
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
    <h1>{{ store.project?.dataset ? '当前仅有特征表' : '尚未建立当前数据集' }}</h1>
    <p>统计分析需要定量矩阵及相应元数据。可直接导入外部矩阵，或使用审核纳入的提取结果。</p>
    <RouterLink to="/statistics">选择或导入统计数据 →</RouterLink>
  </div>
</template>
<style scoped>
.analysis-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.analysis-navigation {
  position: static;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: #fff;
  overflow: hidden;
}
.analysis-group {
  padding: 0 0 8px;
}
.analysis-group + .analysis-group {
  border-top: 1px solid var(--border);
}
.analysis-group-name {
  margin: 0 0 5px;
  padding: 9px 12px;
  background: var(--panel-soft);
  color: #42535b;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
}
.analysis-group .actions {
  display: grid;
  gap: 1px;
  margin: 0;
}
.analysis-navigation button {
  justify-content: flex-start;
  min-height: 34px;
  margin: 0 6px;
  padding: 5px 8px;
  border: 1px solid transparent;
  border-radius: 2px;
  font-size: 13px;
  text-align: left;
}
.analysis-navigation .selected {
  color: var(--teal);
  border-color: #cee3e7;
  background: #edf7f8;
  font-weight: 600;
}
.analysis-content {
  min-width: 0;
}
.analysis-toolbar {
  gap: 8px;
  align-items: center;
  background: var(--panel-soft);
}
.analysis-toolbar .field {
  margin: 0;
}
.analysis-mobile {
  display: none;
}
@media (max-width: 1050px) {
  .analysis-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .analysis-mobile {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 12px;
    padding: 9px 12px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: var(--panel-soft);
  }
}
</style>
