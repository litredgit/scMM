<script setup lang="ts">
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import PlotView from '../../../../components/PlotView.vue'
const {
  reduction,
  usePca,
  cluster,
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
  execute,
  reduce,
  draw,
  pageFeatures,
} = useAnalysisContext()
</script>
<template>
  <div class="card">
    <h2>降维与聚类</h2>
    <h3>输入与参数</h3>
    <div class="field-grid">
      <label
        ><FieldLabel name="reduction" /><select
          aria-label="reduction"
          v-model="reduction.method"
          :disabled="store.busy"
        >
          <option v-for="v in ['pca', 'umap', 'tsne', 'isomap', 'lle']" :key="v">{{ v }}</option>
        </select></label
      ><label
        ><FieldLabel name="use_rep" /><select
          aria-label="use_rep"
          v-model="reduction.use_rep"
          :disabled="store.busy"
        >
          <option>X</option>
          <option v-for="v in info?.embeddings" :key="v">{{ v }}</option>
        </select></label
      ><label
        ><FieldLabel name="n_components" /><input
          aria-label="n_components"
          v-model.number="reduction.n_components"
          type="number"
          min="1"
          :disabled="store.busy" /></label
      ><label
        ><FieldLabel name="store_key" /><input
          aria-label="store_key"
          v-model="reduction.store_key"
          :disabled="store.busy" /></label
      ><label
        ><FieldLabel name="random_state" /><input
          aria-label="random_state"
          v-model.number="reduction.random_state"
          type="number"
          min="0"
          :disabled="store.busy" /></label
      ><label
        ><FieldLabel name="scale" /><select
          aria-label="scale"
          v-model="reduction.scale"
          :disabled="store.busy"
        >
          <option :value="false">不标准化</option>
          <option :value="true">降维前标准化</option>
        </select></label
      >
    </div>
    <details>
      <summary>降维高级参数</summary>
      <div class="field-grid">
        <label v-if="['umap', 'isomap', 'lle'].includes(reduction.method)"
          ><FieldLabel name="n_neighbors" /><input
            aria-label="n_neighbors"
            v-model.number="reduction.n_neighbors"
            type="number"
            min="2"
            :disabled="store.busy" /></label
        ><label v-if="reduction.method === 'umap'"
          ><FieldLabel name="PCA preprocessing" /><select
            aria-label="PCA preprocessing"
            v-model="usePca"
            :disabled="store.busy"
          >
            <option :value="true">启用</option>
            <option :value="false">关闭</option>
          </select></label
        ><label v-if="reduction.method === 'umap' && usePca"
          ><FieldLabel name="PCA input dimensions" /><input
            aria-label="PCA input dimensions"
            v-model.number="reduction.pca_components"
            type="number"
            min="1"
            :disabled="store.busy" /></label
        ><label v-if="reduction.method === 'pca' || (reduction.method === 'umap' && usePca)"
          ><FieldLabel name="whiten" /><select
            aria-label="whiten"
            v-model="reduction.whiten"
            :disabled="store.busy"
          >
            <option :value="false">关闭</option>
            <option :value="true">启用</option>
          </select></label
        ><label v-if="reduction.method === 'umap'"
          ><FieldLabel name="min_dist" /><input
            aria-label="min_dist"
            v-model.number="reduction.min_dist"
            type="number"
            min="0"
            max="1"
            step="any"
            :disabled="store.busy" /></label
        ><label v-if="['umap', 'tsne', 'isomap'].includes(reduction.method)"
          ><FieldLabel name="metric" /><select
            aria-label="metric"
            v-model="reduction.metric"
            :disabled="store.busy"
          >
            <option>euclidean</option>
            <option>manhattan</option>
            <option>cosine</option>
          </select></label
        ><template v-if="reduction.method === 'tsne'"
          ><label
            ><FieldLabel name="perplexity" /><input
              aria-label="perplexity"
              v-model.number="reduction.perplexity"
              type="number"
              min="1"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="learning_rate" /><input
              aria-label="learning_rate"
              v-model="reduction.learning_rate"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="max_iter" /><input
              aria-label="max_iter"
              v-model.number="reduction.max_iter"
              type="number"
              min="250"
              :disabled="store.busy" /></label
        ></template>
      </div>
    </details>
    <button class="primary" :disabled="store.busy" @click="reduce">运行降维</button>
    <div class="field-grid">
      <label
        ><FieldLabel name="clustering" /><select
          aria-label="clustering"
          v-model="cluster.method"
          :disabled="store.busy"
        >
          <option v-for="v in ['kmeans', 'hierarchical', 'dbscan', 'leiden', 'louvain']" :key="v">
            {{ v }}
          </option>
        </select></label
      ><label v-if="['kmeans', 'hierarchical'].includes(cluster.method)"
        ><FieldLabel name="n_clusters" /><input
          aria-label="n_clusters"
          v-model.number="cluster.n_clusters"
          type="number"
          min="2"
          :disabled="store.busy" /></label
      ><label
        ><FieldLabel name="cluster_key" /><input
          aria-label="cluster_key"
          v-model="cluster.key"
          :disabled="store.busy"
      /></label>
    </div>
    <button
      class="primary"
      :disabled="store.busy"
      @click="
        execute('cluster', {
          ...cluster,
          use_rep: reduction.use_rep,
          n_neighbors: reduction.n_neighbors,
          random_state: reduction.random_state,
        })
      "
    >
      运行聚类
    </button>
    <p class="muted">
      DBSCAN 使用现有固定参数 0.5 / 5；图聚类 resolution 为 1。实验轨迹方法继续暂缓。
    </p>
    <div class="field-grid">
      <label
        ><FieldLabel name="查看嵌入" /><select
          aria-label="查看嵌入"
          v-model="embedding"
          :disabled="store.busy"
        >
          <option v-for="v in info?.embeddings" :key="v">{{ v }}</option>
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
            <option v-for="v in ['mean', 'total', 'median', 'detection', 'mz', 'name']" :key="v">
              {{ v }}
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
      ><button class="preview" :disabled="store.busy || !embedding" @click="draw('embedding')">
        更新嵌入图
      </button>
    </div>
    <h3>图表与报告</h3>
    <PlotView
      v-if="figures.embedding && tab === 'embedding'"
      :figure="figures.embedding"
      :legend="legend"
      :name="embedding"
      view-key="analysis.embedding_plot"
    />
  </div>
</template>
