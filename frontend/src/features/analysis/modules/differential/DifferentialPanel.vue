<script setup lang="ts">
import CalculationPanel from '../../components/CalculationPanel.vue'
import FeaturePicker from '../../components/FeaturePicker.vue'
import { computed } from 'vue'
import { displayName } from '../../../../help/labels'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import PlotView from '../../../../components/PlotView.vue'
import ResultTable from '../../components/ResultTable.vue'
import PlotScope from '../../components/PlotScope.vue'
const {
  diff,
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
  plotScope,
  toggleFeature,
} = useAnalysisContext()
const violinStale = computed(() => {
  const meta = figures.value.violin?.layout.meta as { selection_signature?: string } | undefined
  return (
    !meta ||
    meta.selection_signature !==
      JSON.stringify([selectedFeatures.value, hideZero.value, plotScope.value])
  )
})
</script>
<template>
  <div>
    <div class="card">
      <CalculationPanel :has-result="has('differential') || has('markers')">
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
        <div class="actions">
          <button
            class="primary"
            :disabled="
              store.busy || !diff.group_a || !diff.group_b || diff.group_a === diff.group_b
            "
            @click="execute('differential', { ...diff })"
          >
            计算两组差异并绘制火山图
          </button>
        </div>
      </CalculationPanel>
    </div>
    <div class="card">
      <h2>两组差异与火山图</h2>
      <details>
        <summary>
          比较与检验说明 · {{ displayName(diff.group_a) }} 对 {{ displayName(diff.group_b) }}
        </summary>
        <p class="result-context">
          比较 {{ displayName(diff.group_a) || '待选 A 组' }} 与
          {{ displayName(diff.group_b) || '待选 B 组' }}；正 log₂FC 表示前者更高。<br />
          ① 计算全部特征差异并自动绘制火山图 → ② 选择特征 → ③ 绘制小提琴图。
        </p>
        <p class="muted">
          当前数据层：{{ diff.layer ? displayName(diff.layer) : '当前矩阵' }}；检验：{{
            diff.method === 'welch' ? 'Welch t 检验' : 'Mann–Whitney U 检验'
          }}；对全部特征进行 BH-FDR 校正。
        </p>
      </details>
      <div class="actions">
        <button
          class="preview"
          v-if="has('differential')"
          :disabled="store.busy"
          @click="loadResult('differential')"
        >
          读取差异报告
        </button>
      </div>
      <p v-if="!has('differential')" class="muted">
        运行两组比较后生成火山图；若仅绘图失败，可单独重试。
      </p>
      <template v-if="has('differential')">
        <p class="muted">细胞级探索；正 log₂FC 表示前者更高；BH-FDR 针对全部特征。</p>
        <details>
          <summary>火山图显示 · 阈值与标签</summary>
          <div class="field-grid">
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
          <button class="primary" :disabled="store.busy" @click="draw('volcano')">
            更新火山图
          </button>
        </details>
        <PlotView
          v-if="figures.volcano && tab === 'differential'"
          :figure="figures.volcano"
          :legend="legend"
          name="volcano"
          @select="toggleFeature"
        />
        <p class="muted">调整阈值或标签后点击“更新火山图”；仅更新显示，不重新进行检验。</p>
        <FeaturePicker v-model="selectedFeatures" />
        <PlotScope
          v-model="plotScope"
          :observations="info?.observations ?? {}"
          :disabled="store.busy"
        />
        <p class="muted">
          小提琴图可筛选展示范围，检验与全局 FDR 沿用原比较；火山图使用完整比较结果。
        </p>
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
          绘制小提琴图
        </button>
        <p v-if="violinStale && selectedFeatures.length" role="status">
          选择或显示设置已变更，点击“绘制小提琴图”更新。
        </p>
        <PlotView
          v-if="figures.violin && tab === 'differential'"
          :figure="figures.violin"
          :legend="legend"
          name="violin"
        />
        <p class="muted">特征选择和隐藏零值不重新检验，两图共享同一份全特征 FDR。</p></template
      >
      <ResultTable name="differential" heading />
    </div>
    <div class="card">
      <h2>各组差异 Marker</h2>
      <p class="muted">
        每组与其余已标记细胞比较，每次比较对全部特征做 BH-FDR 校正；结果是 Marker 表。
      </p>
      <button
        class="primary"
        :disabled="store.busy || !diff.group_key"
        @click="
          execute('markers', { group_key: diff.group_key, method: diff.method, layer: diff.layer })
        "
      >
        计算全部簇 Marker
      </button>
    </div>
    <div class="card">
      <h2>分类权重 Marker</h2>
      <p class="muted">
        每组对其余组训练正则化逻辑回归，按正权重排序；交叉验证中标准化仅拟合训练折。
      </p>
      <button
        class="primary"
        :disabled="store.busy || !diff.group_key"
        @click="
          execute('markers', { group_key: diff.group_key, method: 'classifier', layer: diff.layer })
        "
      >
        计算分类权重 Marker
      </button>
    </div>
    <div class="card" v-if="has('markers')">
      <h2>当前 Marker 结果</h2>
      <p class="muted">
        上面两种 Marker 共用此结果位置，重新计算会更新当前 Marker 报告；保存项目保留当前结果。
      </p>
      <button class="preview" :disabled="store.busy" @click="loadResult('markers')">
        读取 Marker 报告
      </button>
      <ResultTable name="markers" heading />
    </div>
  </div>
</template>
