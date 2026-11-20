<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWorkspace } from '../../stores/workspace'
import ProfileReviewResult from './ProfileReviewResult.vue'
import type { ProfileCandidate, ProfileReview } from './profileReview'

const props = defineProps<{
  source: string
  version: string
  candidates: ProfileCandidate[]
}>()
const emit = defineEmits<{ clear: [] }>()
const store = useWorkspace()
const dialog = ref<HTMLDialogElement>()
const sample = ref('')
const scan = ref<number | ''>('')
const width = ref<number | ''>('')
const offset = ref<number | ''>(0)
const result = ref<ProfileReview>()
const error = ref('')
const running = ref(false)
const samples = computed(() =>
  (store.project?.manifest.samples ?? []).filter((row) => !row.result_only && row.path),
)
const invalid = computed(
  () =>
    props.candidates.length !== 2 ||
    !samples.value.some((row) => row.id === sample.value) ||
    scan.value === '' ||
    !Number.isInteger(scan.value) ||
    scan.value < 0 ||
    (width.value !== '' && (width.value <= 0 || width.value > 0.5)) ||
    (offset.value !== '' && Math.abs(offset.value) > 100),
)
watch(
  () => [
    props.source,
    props.version,
    props.candidates,
    sample.value,
    scan.value,
    width.value,
    offset.value,
  ],
  () => {
    result.value = undefined
    error.value = ''
  },
)
watch(
  () => store.project?.path,
  () => {
    dialog.value?.close()
    sample.value = ''
    scan.value = ''
  },
)
async function run() {
  if (invalid.value || running.value) return
  running.value = true
  error.value = ''
  result.value = undefined
  try {
    result.value = await store.command<ProfileReview>('/lipids/spectrum/profile-review', {
      source: props.source,
      version: props.version,
      candidate_ids: props.candidates.map((row) => row.candidate_id),
      sample_id: sample.value,
      scan_index: scan.value,
      fwhm: width.value === '' ? null : width.value,
      offset_ppm: offset.value || 0,
    })
    if (!result.value) error.value = store.error
  } finally {
    running.value = false
  }
}
</script>

<template>
  <button
    class="preview"
    :disabled="store.busy || !version"
    :title="version ? '选择两个候选与一条项目原始扫描' : '先运行查库并选择有效版本'"
    @click="dialog?.showModal()"
  >
    原始谱复核 · {{ candidates.length }}/2
  </button>
  <Teleport to="body">
    <dialog ref="dialog" class="card profile-dialog" aria-labelledby="profile-heading">
      <div class="section-heading">
        <h2 id="profile-heading">原始谱重叠复核</h2>
        <button @click="dialog?.close()">返回候选审核</button>
      </div>
      <p v-if="candidates.length < 2" class="state-note">
        在候选列表选入两个候选。先选质量较低的母峰或竞争峰均可。
      </p>
      <div v-if="candidates.length" class="actions selected-candidates">
        <span v-for="row in candidates" :key="row.candidate_id">
          {{ row.feature_id }} · {{ row.name }} {{ row.adduct }}
        </span>
        <button :disabled="running" @click="emit('clear')">清空所选</button>
      </div>
      <p v-if="!samples.length" class="state-note">请在项目样本中登记或重新定位可读的原始文件。</p>
      <div class="field-grid">
        <label>
          项目样本
          <select v-model="sample" :disabled="running">
            <option value="">选择项目样本</option>
            <option v-for="row in samples" :key="row.id" :value="row.id">{{ row.name }}</option>
          </select>
        </label>
        <label>
          MS1 扫描索引（从 0 开始）
          <input v-model.number="scan" type="number" min="0" step="1" :disabled="running" />
        </label>
        <label>
          半高宽（Da）
          <input
            v-model.number="width"
            type="number"
            min="0"
            max="0.5"
            step="any"
            placeholder="留空从母峰测量"
            :disabled="running"
          />
        </label>
        <label>
          模板偏移（ppm）
          <input
            v-model.number="offset"
            type="number"
            min="-100"
            max="100"
            step="any"
            :disabled="running"
          />
        </label>
      </div>
      <p class="muted">可在细胞提取的原始预览核对索引。质量偏移用于模型谱线。</p>
      <div class="actions">
        <button class="primary" :disabled="store.busy || invalid || running" @click="run">
          {{ running ? '正在读取和拟合…' : '运行并记录复核' }}
        </button>
        <RouterLink
          v-if="result?.id"
          :to="{ path: '/annotation/evidence', query: { record: result.id } }"
          @click="dialog?.close()"
          >打开证据记录 →</RouterLink
        >
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
      <ProfileReviewResult v-if="result" :result="result" />
    </dialog>
  </Teleport>
</template>

<style scoped>
.profile-dialog {
  width: min(960px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  margin: auto;
  overflow: auto;
  padding: 14px;
  background: var(--surface);
  color: var(--text);
}
.profile-dialog::backdrop {
  background: rgb(12 26 34 / 45%);
}
.profile-dialog .field-grid {
  grid-template-columns: minmax(160px, 1.5fr) repeat(3, minmax(125px, 1fr));
}
.selected-candidates {
  flex-wrap: wrap;
  overflow-wrap: anywhere;
}
</style>
