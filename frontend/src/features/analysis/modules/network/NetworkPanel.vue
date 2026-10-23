<script setup lang="ts">
import OperationFeedback from '../../../../components/OperationFeedback.vue'
import { displayName } from '../../../../help/labels'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import PlotView from '../../../../components/PlotView.vue'
import ResultTable from '../../components/ResultTable.vue'
const { network, legend, store, info, tab, figures, has, execute, loadWithPlot } =
  useAnalysisContext()
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>特征相关网络</h2>
      <h3>输入与参数</h3>
      <div class="field-grid">
        <label
          ><FieldLabel name="layer" /><select
            aria-label="layer"
            v-model="network.layer"
            :disabled="store.busy"
          >
            <option :value="null">当前矩阵</option>
            <option v-for="v in info?.layers" :key="v" :value="v">{{ displayName(v) }}</option>
          </select></label
        >
        <label
          ><FieldLabel name="network_method" /><select
            aria-label="network_method"
            v-model="network.method"
            :disabled="store.busy"
          >
            <option>pearson</option>
            <option>spearman</option>
            <option>kendall</option>
          </select></label
        ><label
          ><FieldLabel name="network_threshold" /><input
            aria-label="network_threshold"
            v-model.number="network.min_abs_correlation"
            type="number"
            min="0"
            max="1"
            step="any"
            :disabled="store.busy" /></label
        ><label
          ><FieldLabel name="network_top_features" /><input
            aria-label="network_top_features"
            v-model.number="network.top_features"
            type="number"
            min="1"
            max="1000"
            :disabled="store.busy"
        /></label>
      </div>
      <p class="muted">按方差筛选特征；相关不代表因果，也不是轨迹分析。</p>
      <div class="actions">
        <button class="primary" :disabled="store.busy" @click="execute('network', { ...network })">
          计算相关网络</button
        ><button
          class="preview"
          v-if="has('network')"
          :disabled="store.busy"
          @click="loadWithPlot('network', 'network_plot')"
        >
          读取相关网络
        </button>
      </div>
      <OperationFeedback :labels="['相关网络', '绘制图形']" />
    </section>
    <section class="analysis-visualization">
      <h3>图表与报告</h3>
      <PlotView
        v-if="figures.network_plot && tab === 'network'"
        :figure="figures.network_plot"
        :legend="legend"
        name="network"
      /><ResultTable name="network" />
    </section>
  </div>
</template>
