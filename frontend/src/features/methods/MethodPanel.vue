<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AnalysisInfo, PluginKind, PluginValue, QC } from '../../api/types'
import { useWorkspace } from '../../stores/workspace'
import PlotView from '../../components/PlotView.vue'
import OperationFeedback from '../../components/OperationFeedback.vue'
import MethodFields from './MethodFields.vue'
import MethodReport from './MethodReport.vue'

const props = defineProps<{ kind: PluginKind; info?: AnalysisInfo; source?: string }>()
const emit = defineEmits<{ completed: [] }>()
const store = useWorkspace()
const methods = computed(
  () => store.configuration?.methods.filter((item) => item.kind === props.kind) ?? [],
)
const selected = ref(''),
  layer = ref(''),
  embedding = ref(''),
  outputKey = ref('')
const options = ref<Record<string, PluginValue>>({})
const method = computed(() => methods.value.find((item) => item.id === selected.value))
const preview = ref<{ signature: string; qc: QC }>()
const result = ref<{ report?: string; candidates?: number; key?: string }>()
const hasOutputKey = computed(() => props.kind === 'clustering' || props.kind === 'reduction')
const signature = computed(() =>
  JSON.stringify([store.current?.revision, selected.value, layer.value, options.value]),
)
watch(method, (value) => {
  options.value = Object.fromEntries(
    value?.parameters.map((field) => [field.key, field.default]) ?? [],
  )
  outputKey.value = value?.id.split(':').at(-1)?.replaceAll('-', '_') ?? ''
  result.value = undefined
})
watch(
  () => [store.project?.path, store.project?.dataset?.id, props.source],
  () => {
    result.value = undefined
    preview.value = undefined
  },
)

async function run(check = false) {
  if (!method.value) return
  const expected = signature.value
  const payload = {
    method_id: method.value.id,
    version: method.value.version,
    options: options.value,
    source: props.source ?? '',
    layer: layer.value || null,
    embedding: embedding.value || null,
    output_key: hasOutputKey.value ? outputKey.value : '',
    preview: check,
  }
  let completed = false
  if (check) preview.value = undefined
  await store.analysisTransaction(async (api) => {
    const value = await api.command<{
      qc?: QC
      report?: string
      candidates?: number
      key?: string
    }>('/methods/run', payload)
    if (!value) return
    if (check && value.qc) preview.value = { signature: expected, qc: value.qc }
    if (!check) {
      preview.value = undefined
      result.value = value
      completed = true
    }
  })
  if (completed) emit('completed')
}
</script>

<template>
  <details v-if="methods.length" class="card">
    <summary>插件方法</summary>
    <div class="actions">
      <label class="field">
        <FieldLabel name="选择方法" />
        <select v-model="selected" aria-label="选择插件方法" :disabled="store.busy">
          <option value="">请选择</option>
          <option v-for="item in methods" :key="item.id" :value="item.id">
            {{ item.label }} · {{ item.version }}
          </option>
        </select>
      </label>
      <template v-if="method">
        <label v-if="kind !== 'annotation'" class="field">
          <FieldLabel name="输入强度层" />
          <select v-model="layer" aria-label="输入强度层" :disabled="store.busy || !!embedding">
            <option value="">当前 X</option>
            <option v-for="key in info?.layers" :key="key">{{ key }}</option>
          </select>
        </label>
        <template v-if="hasOutputKey">
          <label class="field">
            <FieldLabel name="输入嵌入（可选）" />
            <select
              v-model="embedding"
              aria-label="输入嵌入"
              :disabled="store.busy"
              @change="layer = ''"
            >
              <option value="">使用矩阵</option>
              <option v-for="key in info?.embeddings" :key="key">{{ key }}</option>
            </select>
          </label>
          <label class="field">
            <FieldLabel name="输出名称" />
            <input v-model.trim="outputKey" aria-label="输出名称" :disabled="store.busy" />
          </label>
        </template>
        <MethodFields
          v-model="options"
          :method="method"
          :observations="Object.keys(info?.observations ?? {})"
          :disabled="store.busy"
        />
      </template>
    </div>
    <div v-if="method" class="actions">
      <button
        v-if="kind === 'preprocessing'"
        class="preview"
        :disabled="store.busy"
        @click="run(true)"
      >
        检查影响
      </button>
      <button
        class="primary"
        :disabled="
          store.busy ||
          (kind === 'preprocessing' && preview?.signature !== signature) ||
          (hasOutputKey && !outputKey)
        "
        :title="
          kind === 'preprocessing' && preview?.signature !== signature
            ? '请先检查当前参数的影响'
            : ''
        "
        @click="run(false)"
      >
        {{ kind === 'preprocessing' ? '应用到当前数据' : '运行插件方法' }}
      </button>
    </div>
    <OperationFeedback :labels="['运行插件方法']" />
    <PlotView
      v-if="preview?.signature === signature"
      :figure="preview!.qc.figure"
      compact
      readonly
    />
    <p v-if="result?.candidates !== undefined" role="status">
      已生成 {{ result.candidates }} 条候选，可在当前注释版本审核。
    </p>
    <p v-else-if="result?.key" role="status">已应用结果 {{ result.key }}。</p>
    <p v-else-if="result && kind === 'preprocessing'" role="status">已应用到当前数据。</p>
    <MethodReport v-if="result?.report" :report-id="result.report" />
  </details>
</template>
