<script setup lang="ts">
import { displayName } from '../../../../help/labels'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import PlotView from '../../../../components/PlotView.vue'
defineProps<{ panel: string }>()
const {
  projection,
  embedding,
  colorSource,
  color,
  search,
  sort,
  descending,
  featureTotal,
  featureOffset,
  legend,
  store,
  info,
  tab,
  colors,
  figures,
  draw,
  pageFeatures,
} = useAnalysisContext()
</script>
<template>
  <div>
    <div class="field-grid">
      <label
        >显示维度<select v-model="projection.threeD">
          <option :value="false">二维</option>
          <option :value="true">三维</option>
        </select></label
      >
      <label v-for="axis in projection.threeD ? ['x', 'y', 'z'] : ['x', 'y']" :key="axis"
        >{{ axis.toUpperCase() }} 轴<input
          v-model.number="projection[axis as 'x' | 'y' | 'z']"
          type="number"
          min="1"
          :max="info?.embedding_dimensions?.[embedding] || 2"
      /></label>
    </div>
    <table v-if="info?.embedding_variance?.[embedding]?.length">
      <thead>
        <tr>
          <th>主成分</th>
          <th>解释率</th>
          <th>累计解释率</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(value, i) in info.embedding_variance[embedding]" :key="i">
          <td>PC{{ i + 1 }}</td>
          <td>{{ (value * 100).toFixed(2) }}%</td>
          <td>
            {{
              (
                info.embedding_variance[embedding]!.slice(0, i + 1).reduce((a, b) => a + b, 0) * 100
              ).toFixed(2)
            }}%
          </td>
        </tr>
      </tbody>
    </table>
    <div class="field-grid">
      <label
        ><FieldLabel name="查看嵌入" /><select
          aria-label="查看嵌入"
          v-model="embedding"
          :disabled="store.busy"
        >
          <option v-for="v in info?.embeddings" :key="v" :value="v">{{ displayName(v) }}</option>
        </select></label
      ><label
        ><FieldLabel name="Color source" /><select aria-label="Color source" v-model="colorSource">
          <option value="annotation">列标签</option>
          <option value="feature">Feature</option>
          <option value="none">无</option>
        </select></label
      ><label v-if="colorSource !== 'none'"
        ><FieldLabel name="Search" /><input
          aria-label="Search"
          v-model="search"
          placeholder="筛选列标签 / feature / m/z" /></label
      ><template v-if="colorSource === 'feature'"
        ><label
          ><FieldLabel name="Feature order" /><select aria-label="Feature order" v-model="sort">
            <option
              v-for="v in ['mean', 'total', 'median', 'detection', 'mz', 'name']"
              :key="v"
              :value="v"
            >
              {{ displayName(v) }}
            </option>
          </select></label
        ><label
          ><FieldLabel name="Descending" /><select aria-label="Descending" v-model="descending">
            <option :value="true">降序</option>
            <option :value="false">升序</option>
          </select></label
        ></template
      ><label v-if="colorSource !== 'none'"
        ><FieldLabel name="Color" /><select v-model="color" aria-label="Color">
          <option value="">无</option>
          <option v-if="color && !colors.some((c) => c.value === color)" :value="color">
            {{ color }}
          </option>
          <option v-for="v in colors" :key="v.value" :value="v.value">{{ v.label }}</option>
        </select></label
      >
    </div>
    <div class="actions">
      <button v-if="search" @click="search = ''">清除筛选</button
      ><template v-if="colorSource === 'feature'"
        ><span
          >{{ featureOffset + 1 }}–{{ Math.min(featureOffset + 200, featureTotal) }} /
          {{ featureTotal }} 特征</span
        ><button :disabled="featureOffset === 0" @click="pageFeatures(-200)">上一页特征</button
        ><button :disabled="featureOffset + 200 >= featureTotal" @click="pageFeatures(200)">
          下一页特征
        </button></template
      ><button class="primary" :disabled="store.busy || !embedding" @click="draw('embedding')">
        更新嵌入图
      </button>
    </div>
    <h3>图表与报告</h3>
    <PlotView
      v-if="figures.embedding && tab === panel"
      :figure="figures.embedding"
      :legend="legend"
      :name="embedding"
      view-key="analysis.embedding_plot"
    />
  </div>
</template>
