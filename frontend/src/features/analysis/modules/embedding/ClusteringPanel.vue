<script setup lang="ts">
import OperationFeedback from '../../../../components/OperationFeedback.vue'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import { displayName } from '../../../../help/labels'
import EmbeddingView from './EmbeddingView.vue'
const { cluster, info, tab, store, execute, clusterConflict } = useAnalysisContext()
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>聚类</h2>
      <div class="field-grid">
        <label
          >输入表示<select v-model="cluster.use_rep" :disabled="store.busy">
            <option value="X">当前矩阵</option>
            <option v-for="key in info?.embeddings" :key="key" :value="key">{{ key }}</option>
          </select></label
        ><label
          >随机种子<input
            type="number"
            min="0"
            v-model.number="cluster.random_state"
            :disabled="store.busy" /></label
        ><label v-if="['leiden', 'louvain'].includes(cluster.method)"
          >邻居数<input
            type="number"
            min="1"
            v-model.number="cluster.n_neighbors"
            :disabled="store.busy"
        /></label>
      </div>
      <div class="field-grid">
        <template v-if="cluster.method === 'dbscan'">
          <label
            ><FieldLabel name="eps" /><input
              aria-label="eps"
              type="number"
              min="0"
              step="any"
              v-model.number="cluster.eps"
              :disabled="store.busy"
          /></label>
          <label
            ><FieldLabel name="min_samples" /><input
              aria-label="min_samples"
              type="number"
              min="1"
              v-model.number="cluster.min_samples"
              :disabled="store.busy"
          /></label>
        </template>
        <label v-if="['leiden', 'louvain'].includes(cluster.method)"
          ><FieldLabel name="聚类分辨率" help-key="cluster_resolution" /><input
            aria-label="聚类分辨率"
            type="number"
            min="0"
            step="any"
            v-model.number="cluster.resolution"
            :disabled="store.busy"
        /></label>
      </div>
      <details>
        <summary>聚类高级参数</summary>
        <div class="field-grid">
          <template v-if="cluster.method === 'kmeans'">
            <label
              ><FieldLabel name="n_init" /><input
                aria-label="n_init"
                type="number"
                min="1"
                v-model.number="cluster.n_init"
                :disabled="store.busy"
            /></label>
            <label
              ><FieldLabel name="聚类最大迭代" help-key="cluster_max_iter" /><input
                aria-label="聚类最大迭代"
                type="number"
                min="1"
                v-model.number="cluster.max_iter"
                :disabled="store.busy"
            /></label>
            <label
              ><FieldLabel name="tol" /><input
                aria-label="tol"
                type="number"
                min="0"
                step="any"
                v-model.number="cluster.tol"
                :disabled="store.busy"
            /></label>
          </template>
          <label v-if="['dbscan', 'hierarchical'].includes(cluster.method)"
            ><FieldLabel name="metric" /><select
              aria-label="聚类距离"
              v-model="cluster.metric"
              :disabled="store.busy"
            >
              <option
                v-for="value in ['euclidean', 'manhattan', 'cosine']"
                :key="value"
                :value="value"
              >
                {{ displayName(value) }}
              </option>
            </select></label
          >
          <label v-if="cluster.method === 'hierarchical'"
            ><FieldLabel name="linkage" /><select
              aria-label="linkage"
              v-model="cluster.linkage"
              :disabled="store.busy"
            >
              <option
                v-for="value in ['ward', 'complete', 'average', 'single']"
                :key="value"
                :value="value"
              >
                {{ displayName(value) }}
              </option>
            </select></label
          >
          <label v-if="cluster.method === 'leiden'"
            ><FieldLabel name="n_iterations" /><input
              aria-label="n_iterations"
              type="number"
              min="-1"
              v-model.number="cluster.n_iterations"
              :disabled="store.busy"
          /></label>
          <template v-if="cluster.method === 'louvain'">
            <label
              ><FieldLabel name="threshold" /><input
                aria-label="Louvain 停止阈值"
                type="number"
                min="0"
                step="any"
                v-model.number="cluster.threshold"
                :disabled="store.busy"
            /></label>
            <label
              ><FieldLabel name="max_level" /><input
                aria-label="max_level"
                type="number"
                min="1"
                :value="cluster.max_level ?? ''"
                @input="
                  cluster.max_level =
                    ($event.target as HTMLInputElement).value === ''
                      ? null
                      : Number(($event.target as HTMLInputElement).value)
                "
                :disabled="store.busy"
                placeholder="不限"
            /></label>
          </template>
        </div>
      </details>
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
      <p v-if="clusterConflict" role="status" class="state-note">{{ clusterConflict }}</p>
      <button
        class="primary"
        :disabled="store.busy || !!clusterConflict"
        @click="
          execute('cluster', {
            ...cluster,
          })
        "
      >
        运行聚类
      </button>
      <p class="muted">
        参数草稿需点击“运行聚类”才生效。DBSCAN 的 -1
        表示噪声；过大的最小邻域样本数可能使全部细胞成为噪声。 Ward 仅支持欧氏距离；Leiden
        迭代次数为 -1 或正整数。已有聚类列不能覆盖。
      </p>
      <OperationFeedback :labels="['聚类', '绘制图形']" />
    </section>
    <section class="analysis-visualization">
      <EmbeddingView v-if="tab === 'clustering'" panel="clustering" />
    </section>
  </div>
</template>
