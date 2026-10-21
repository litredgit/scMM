<script setup lang="ts">
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import { displayName } from '../../../../help/labels'
import EmbeddingView from './EmbeddingView.vue'
const { cluster, info, tab, store, execute } = useAnalysisContext()
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>聚类</h2>
      <div class="field-grid">
        <label
          >输入表示<select v-model="cluster.use_rep">
            <option value="X">当前矩阵</option>
            <option v-for="key in info?.embeddings" :key="key" :value="key">{{ key }}</option>
          </select></label
        ><label>随机种子<input type="number" min="0" v-model.number="cluster.random_state" /></label
        ><label>邻居数<input type="number" min="1" v-model.number="cluster.n_neighbors" /></label>
      </div>
      <div class="field-grid">
        <label
          ><FieldLabel name="clustering" /><select
            aria-label="clustering"
            v-model="cluster.method"
            :disabled="store.busy"
          >
            <option
              v-for="v in ['kmeans', 'hierarchical', 'dbscan', 'leiden', 'louvain']"
              :key="v"
              :value="v"
            >
              {{ displayName(v) }}
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
          })
        "
      >
        运行聚类
      </button>
      <p class="muted">
        DBSCAN 使用现有固定参数 0.5 / 5；图聚类 resolution 为 1。实验轨迹方法继续暂缓。
      </p>
    </section>
    <section class="analysis-visualization">
      <EmbeddingView v-if="tab === 'clustering'" panel="clustering" />
    </section>
  </div>
</template>
