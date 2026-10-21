<script setup lang="ts">
import { displayName } from '../../../../help/labels'
import { useAnalysisContext } from '../../composables/useAnalysisContext'
import EmbeddingView from './EmbeddingView.vue'
const { reduction, usePca, store, info, tab, reduce } = useAnalysisContext()
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
      <h2>降维</h2>
      <h3>输入与参数</h3>
      <div class="field-grid">
        <label
          ><FieldLabel name="reduction" /><select
            aria-label="reduction"
            v-model="reduction.method"
            :disabled="store.busy"
          >
            <option v-for="v in ['pca', 'umap', 'tsne', 'isomap', 'lle']" :key="v" :value="v">
              {{ displayName(v) }}
            </option>
          </select></label
        ><label
          ><FieldLabel name="use_rep" /><select
            aria-label="use_rep"
            v-model="reduction.use_rep"
            :disabled="store.busy"
          >
            <option value="X">当前矩阵</option>
            <option v-for="v in info?.embeddings" :key="v" :value="v">{{ displayName(v) }}</option>
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
    </section>
    <section class="analysis-visualization">
      <EmbeddingView v-if="tab === 'embedding'" panel="embedding" />
    </section>
  </div>
</template>
