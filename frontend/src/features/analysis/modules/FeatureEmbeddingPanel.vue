<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisContext } from '../composables/useAnalysisContext'
import StoredAnalysisPlot from './StoredAnalysisPlot.vue'
import { displayName } from '../../../help/labels'
const { store, info, featureEmbedding: options, selectedFeatures } = useAnalysisContext()
const features = computed({
  get: () => options.features.join('\n'),
  set: (v: string) => {
    options.features = v
      .split(/[\n,;]+/)
      .map((v) => v.trim())
      .filter(Boolean)
  },
})
</script>
<template>
  <StoredAnalysisPlot kind="feature_embedding" title="特征距离嵌入" :options="{ ...options }">
    <p>每点代表特征。Pearson 距离使用绝对相关，Euclidean 使用当前强度；不是相关阈值网络。</p>
    <label
      >特征 ID（空白使用全部）<textarea
        aria-label="距离嵌入特征ID"
        v-model="features"
        :disabled="store.busy"
        rows="4"
      />
    </label>
    <button
      class="preview"
      :disabled="store.busy"
      @click="options.features = [...selectedFeatures]"
    >
      使用已选特征
    </button>
    <p class="muted">
      最多 500 个特征、200 万个输入数值。Pearson 拒绝常量特征；缺失名称回退到 ID。
    </p>
    <div class="field-grid">
      <label
        >距离<select aria-label="特征嵌入距离" v-model="options.metric" :disabled="store.busy">
          <option value="pearson">Pearson 绝对相关距离</option>
          <option value="euclidean">Euclidean 欧氏距离</option>
        </select></label
      >
      <label
        >强度层<select v-model="options.layer" :disabled="store.busy">
          <option :value="null">当前矩阵</option>
          <option v-for="key in info?.layers" :value="key" :key="key">
            {{ displayName(key) }}
          </option>
        </select></label
      >
      <label v-for="field in ['name_key', 'class_key'] as const" :key="field"
        >{{ field === 'name_key' ? '名称来源' : '类别来源'
        }}<select v-model="options[field]" :disabled="store.busy">
          <option :value="null">{{ field === 'name_key' ? '稳定特征 ID' : '统一颜色' }}</option>
          <option v-for="key in info?.feature_columns" :key="key" :value="key">
            {{ displayName(key) }}
          </option>
        </select></label
      >
      <label
        ><span title="n_neighbors：留空使用 min(15,特征数−1)，显式整数为 2 至特征数−1"
          >近邻数（空白自动）</span
        ><input
          aria-label="特征嵌入近邻数"
          type="number"
          min="2"
          :value="options.n_neighbors ?? ''"
          @input="
            options.n_neighbors =
              ($event.target as HTMLInputElement).value === ''
                ? null
                : Number(($event.target as HTMLInputElement).value)
          "
          :disabled="store.busy"
      /></label>
      <label
        ><span title="min_dist：UMAP 最小距离，0 至 1，不改变输入距离定义">最小距离</span
        ><input
          aria-label="特征嵌入最小距离"
          v-model.number="options.min_dist"
          type="number"
          min="0"
          max="1"
          step="0.01"
          :disabled="store.busy"
      /></label>
      <label
        ><span title="random_state：UMAP 随机种子，记录并保存">随机种子</span
        ><input
          aria-label="特征嵌入随机种子"
          v-model.number="options.random_state"
          type="number"
          min="0"
          step="1"
          :disabled="store.busy"
      /></label>
    </div>
  </StoredAnalysisPlot>
</template>
