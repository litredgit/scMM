<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { Figure } from '../../../../api/types'
import { displayName } from '../../../../help/labels'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import ReportView from '../../../../components/ReportView.vue'
import PlotView from '../../../../components/PlotView.vue'
import ResultTable from '../../components/ResultTable.vue'
const {
  train,
  ldaSolver,
  validation,
  latentKey,
  shap,
  legend,
  store,
  info,
  tab,
  observed,
  figures,
  modelReport,
  has,
  help,
  execute,
  trainModel,
  loadResult,
  draw,
  loadWithPlot,
} = useAnalysisContext()
const shapView = reactive({ class_index: 0, cell_index: 0, feature: '' })
const validationWarnings = computed(() => {
  const audit = modelReport.value?.validation_audit as { warnings?: string[] } | undefined
  return audit?.warnings ?? []
})
async function showConfusion(normalize: boolean) {
  const value = await store.command<Figure>('/analysis/plot', {
    kind: 'confusion',
    options: { normalize },
  })
  if (value) figures.value.confusion = value
}
async function showShap(kind: string) {
  const value = await store.command<Figure>('/analysis/plot', {
    kind,
    options: { ...shapView, feature: shapView.feature || null },
  })
  if (value) figures.value[kind] = value
}
</script>
<template>
  <div class="card">
    <h2>监督学习与模型诊断</h2>
    <h3>输入与参数</h3>
    <p class="page-note">
      训练、测试及 CV
      折均须包含全部类别。分组划分不能补救提前在全数据上插补或选特征造成的泄漏；反复调参后的 holdout
      不再是独立测试。 分组留出加至少两折 CV 要求每类至少有 3
      个来源组；这是划分所需的下限，不代表生物重复充足。
    </p>
    <div class="field-grid">
      <label
        ><FieldLabel name="random_state" /><input
          aria-label="random_state"
          v-model.number="train.random_state"
          type="number"
          min="0"
          :disabled="store.busy"
      /></label>
      <label
        ><FieldLabel name="label_key" /><select
          aria-label="label_key"
          v-model="train.label_key"
          :disabled="store.busy"
        >
          <option v-for="v in observed" :key="v" :value="v">{{ displayName(v) }}</option>
        </select></label
      ><label
        ><FieldLabel name="验证方式" /><select
          aria-label="验证方式"
          v-model="validation"
          :disabled="store.busy"
        >
          <option value="grouped">按独立来源分组验证</option>
          <option value="cell">仅细胞级探索（可能泄漏）</option>
        </select></label
      ><label v-if="validation === 'grouped'"
        ><FieldLabel name="group_key" help-key="validation_group" /><select
          aria-label="group_key"
          v-model="train.group_key"
          :disabled="store.busy"
        >
          <option :value="null" disabled>选择独立样本 / 来源列</option>
          <option v-for="v in observed" :key="v" :value="v">{{ displayName(v) }}</option>
        </select></label
      ><label
        ><FieldLabel name="layer" /><select
          aria-label="layer"
          v-model="train.layer"
          :disabled="store.busy"
        >
          <option :value="null">当前矩阵</option>
          <option v-for="v in info?.layers" :key="v" :value="v">{{ displayName(v) }}</option>
        </select></label
      ><label
        ><FieldLabel name="model" /><select
          aria-label="model"
          v-model="train.model"
          :disabled="store.busy"
        >
          <option v-for="v in ['logistic', 'lda', 'plsda', 'random_forest']" :key="v" :value="v">
            {{ displayName(v) }}
          </option>
        </select></label
      ><label
        ><FieldLabel name="cv" /><input
          aria-label="cv"
          v-model.number="train.cv"
          type="number"
          min="2"
          :disabled="store.busy" /></label
      ><label
        ><FieldLabel name="test_size" /><input
          aria-label="test_size"
          v-model.number="train.test_size"
          type="number"
          min="0.01"
          max="0.99"
          step="any"
          :disabled="store.busy"
      /></label>
    </div>
    <details>
      <summary>监督高级参数</summary>
      <div class="field-grid">
        <label v-if="train.model === 'lda'"
          ><FieldLabel name="LDA solver" /><select
            aria-label="LDA solver"
            v-model="ldaSolver"
            :disabled="store.busy"
          >
            <option>svd</option>
            <option>lsqr</option>
            <option>eigen</option>
          </select></label
        ><label
          ><FieldLabel name="calibration_bins" /><input
            aria-label="calibration_bins"
            v-model.number="train.calibration_bins"
            type="number"
            min="2"
            :disabled="store.busy"
        /></label>
      </div>
      <div class="check-list">
        <label
          ><input
            v-model="train.smote"
            type="checkbox"
            aria-label="训练折内 SMOTE"
            :disabled="store.busy" />训练折内 SMOTE
          <HelpTip
            label="SMOTE"
            text="仅在每个训练折内部生成合成少数类细胞，测试集保持不变。少数类样本数须满足近邻条件，不能增加独立生物重复数。"
        /></label>
      </div>
    </details>
    <div class="actions">
      <button
        class="primary"
        :disabled="store.busy || !train.label_key || (validation === 'grouped' && !train.group_key)"
        @click="trainModel"
      >
        训练并验证</button
      ><button
        class="preview"
        v-if="has('supervised')"
        :disabled="store.busy"
        @click="loadResult('supervised')"
      >
        读取监督诊断
      </button>
    </div>
    <h3>图表与报告</h3>
    <aside v-if="validationWarnings.length" aria-label="监督验证解释" class="page-note">
      <p v-for="warning in validationWarnings" :key="warning">{{ warning }}</p>
    </aside>
    <ReportView v-if="modelReport" :value="modelReport" />
    <button
      class="preview"
      v-if="has('supervised')"
      :disabled="store.busy"
      @click="showConfusion(true)"
    >
      显示按真实类别归一的混淆矩阵
    </button>
    <button
      class="preview"
      v-if="has('supervised')"
      :disabled="store.busy"
      @click="showConfusion(false)"
    >
      显示计数混淆矩阵
    </button>
    <template v-for="kind in ['roc', 'pr', 'calibration', 'confusion'] as const" :key="kind"
      ><button
        class="preview"
        v-if="has('supervised') && !figures[kind]"
        :disabled="store.busy"
        @click="draw(kind)"
      >
        显示
        {{
          { roc: 'ROC 曲线', pr: '精确率–召回率', calibration: '校准曲线', confusion: '混淆矩阵' }[
            kind
          ]
        }}</button
      ><PlotView
        v-if="figures[kind] && tab === 'supervised'"
        :figure="figures[kind]!"
        :legend="legend"
        :name="kind"
    /></template>
    <div class="field-grid">
      <label
        ><FieldLabel name="latent_key" /><input
          aria-label="latent_key"
          v-model="latentKey"
          :disabled="store.busy"
      /></label>
    </div>
    <button
      class="save"
      :disabled="store.busy || !info?.latent_supported"
      @click="execute('save_latent', { key: latentKey })"
    >
      保存潜变量和 train/test 标识
    </button>
    <p class="muted">lsqr 可做分类但不支持潜变量。项目重载仅保留只读报告，不保存可执行模型。</p>
    <h3>SHAP 特征解释</h3>
    <p class="muted">
      训练集背景解释测试集；绝对贡献跨样本和类别取平均，不表示效应方向或因果。图显示前 30
      项，下载包含全部。
    </p>
    <div class="field-grid">
      <label
        ><FieldLabel name="shap_background" /><input
          aria-label="shap_background"
          v-model.number="shap.max_background"
          type="number"
          min="1"
          max="1000"
          :disabled="store.busy" /></label
      ><label
        ><FieldLabel name="shap_samples" /><input
          aria-label="shap_samples"
          v-model.number="shap.max_samples"
          type="number"
          min="1"
          max="1000"
          :disabled="store.busy"
      /></label>
    </div>
    <div class="actions">
      <button
        class="primary"
        :disabled="store.busy || !info?.live_results.includes('supervised')"
        @click="execute('explain_shap', { ...shap, seed: train.random_state })"
      >
        解释当前模型（SHAP）</button
      ><button
        class="preview"
        v-if="has('shap')"
        :disabled="store.busy"
        @click="loadWithPlot('shap', 'shap_plot')"
      >
        读取 SHAP
      </button>
    </div>
    <div class="field-grid">
      <label
        >解释类别序号（从 0 开始）<input
          v-model.number="shapView.class_index"
          type="number"
          min="0" /></label
      ><label
        >细胞序号（从 0 开始）<input
          v-model.number="shapView.cell_index"
          type="number"
          min="0" /></label
      ><label>依赖图特征编号<input v-model="shapView.feature" /></label>
    </div>
    <template
      v-for="kind in ['shap_plot', 'shap_beeswarm', 'shap_waterfall', 'shap_dependence'] as const"
      :key="kind"
      ><button class="preview" :disabled="store.busy || !has('shap')" @click="showShap(kind)">
        {{
          {
            shap_plot: '全局重要性',
            shap_beeswarm: '类别蜂群图',
            shap_waterfall: '单细胞瀑布图',
            shap_dependence: '特征依赖图',
          }[kind]
        }}</button
      ><PlotView
        v-if="figures[kind] && tab === 'supervised'"
        :figure="figures[kind]!"
        :name="kind"
        :legend="legend" /></template
    ><ResultTable name="shap" />
  </div>
</template>
