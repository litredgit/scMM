<script setup lang="ts">
import { displayName } from '../../../../help/labels'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import PlotView from '../../../../components/PlotView.vue'
import ResultTable from '../../components/ResultTable.vue'
const {
  diff,
  featureOptions,
  selectedFeatures,
  hideZero,
  volcano,
  legend,
  store,
  info,
  tab,
  observed,
  groups,
  figures,
  has,
  execute,
  loadResult,
  draw,
  toggleFeature,
} = useAnalysisContext()
</script>
<template>
  <div>
    <div class="card">
      <h2>比较输入</h2>
      <div class="field-grid">
        <label
          ><FieldLabel name="group_key" /><select
            aria-label="group_key"
            v-model="diff.group_key"
            :disabled="store.busy"
          >
            <option v-for="v in observed" :key="v" :value="v">{{ displayName(v) }}</option>
          </select></label
        ><label
          ><FieldLabel name="group_a（fold change 分子）" /><select
            aria-label="group_a（fold change 分子）"
            v-model="diff.group_a"
            :disabled="store.busy"
          >
            <option v-for="v in groups" :key="v" :value="v">{{ displayName(v) }}</option>
          </select></label
        ><label
          ><FieldLabel name="group_b" /><select
            aria-label="group_b"
            v-model="diff.group_b"
            :disabled="store.busy"
          >
            <option v-for="v in groups" :key="v" :value="v">{{ displayName(v) }}</option>
          </select></label
        ><label
          ><FieldLabel name="layer" /><select
            aria-label="layer"
            v-model="diff.layer"
            :disabled="store.busy"
          >
            <option :value="null">当前矩阵</option>
            <option v-for="v in info?.layers" :key="v" :value="v">{{ displayName(v) }}</option>
          </select></label
        ><label
          ><FieldLabel name="differential_method" /><select
            aria-label="differential_method"
            v-model="diff.method"
            :disabled="store.busy"
          >
            <option>mannwhitney</option>
            <option>welch</option>
          </select></label
        >
      </div>
      <p class="page-note">
        细胞数不等于生物重复。细胞级差异用于探索，来源层面推断须先按重复聚合；精确质量注释只是候选。
      </p>
    </div>
    <div class="card">
      <h2>全特征差异与 Marker</h2>
      <button
        class="primary"
        :disabled="store.busy || !diff.group_key"
        @click="
          execute('markers', { group_key: diff.group_key, method: 'classifier', layer: diff.layer })
        "
      >
        计算分类权重 Marker
      </button>
      <p class="muted">
        逐组对其余组训练正则化逻辑回归；正权重越高越支持本组，交叉验证中标准化只拟合训练折。
      </p>
      <div class="actions">
        <button
          class="primary"
          :disabled="store.busy || !diff.group_a || !diff.group_b"
          @click="execute('differential', { ...diff })"
        >
          比较全部特征</button
        ><button
          class="primary"
          :disabled="store.busy || !diff.group_key"
          @click="
            execute('markers', {
              group_key: diff.group_key,
              method: diff.method,
              layer: diff.layer,
            })
          "
        >
          计算全部簇 Marker</button
        ><button
          class="preview"
          v-if="has('differential')"
          :disabled="store.busy"
          @click="loadResult('differential')"
        >
          读取差异报告</button
        ><button
          class="preview"
          v-if="has('markers')"
          :disabled="store.busy"
          @click="loadResult('markers')"
        >
          读取 Marker 报告
        </button>
      </div>
      <p class="muted">
        差异检验对全部特征做 BH-FDR。Marker 为每簇对其余已标记细胞，每个比较内做 BH-FDR。
      </p>
      <template v-if="has('differential')"
        ><div class="field-grid">
          <label
            ><FieldLabel name="FDR threshold" /><input
              aria-label="FDR threshold"
              v-model.number="volcano.fdr"
              type="number"
              min="0"
              max="1"
              step="any" /></label
          ><label
            ><FieldLabel name="abs(log2FC)" /><input
              aria-label="abs(log2FC)"
              v-model.number="volcano.fold_change"
              type="number"
              min="0"
              step="any" /></label
          ><label
            ><FieldLabel name="Label count" /><input
              aria-label="Label count"
              v-model.number="volcano.labels"
              type="number"
              min="0"
              max="100" /></label
          ><label
            ><FieldLabel name="Label order" /><select
              aria-label="Label order"
              v-model="volcano.order"
            >
              <option>fdr</option>
              <option>effect</option>
              <option>p_value</option>
              <option>intensity</option>
            </select></label
          >
        </div>
        <button class="primary" :disabled="store.busy" @click="draw('volcano')">更新火山图</button
        ><PlotView
          v-if="figures.volcano && tab === 'differential'"
          :figure="figures.volcano"
          :legend="legend"
          name="volcano"
          @select="toggleFeature"
        /><label class="field"
          ><FieldLabel name="小提琴特征（最多 12 个；也可点击火山图）" /><select
            aria-label="小提琴特征（最多 12 个；也可点击火山图）"
            v-model="selectedFeatures"
            multiple
            size="6"
          >
            <option v-for="v in featureOptions" :key="v.value" :value="v.value">
              {{ v.label }}
            </option>
          </select></label
        >
        <div class="check-list">
          <label
            ><input
              v-model="hideZero"
              type="checkbox"
              aria-label="仅显示时隐藏零值" />仅显示时隐藏零值
            <HelpTip
              label="隐藏零值"
              text="只从小提琴图显示中排除零值，不修改矩阵，也不重新计算检验或 FDR。"
          /></label>
        </div>
        <button
          class="primary"
          :disabled="store.busy || !selectedFeatures.length"
          @click="draw('violin')"
        >
          更新小提琴图</button
        ><PlotView
          v-if="figures.violin && tab === 'differential'"
          :figure="figures.violin"
          :legend="legend"
          name="violin"
        />
        <p class="muted">特征选择和隐藏零值不重新检验，两图共享同一份全特征 FDR。</p></template
      ><template v-for="name in ['differential', 'markers'] as const" :key="name"
        ><ResultTable :name="name" heading
      /></template>
    </div>
  </div>
</template>
