<script setup lang="ts">
import { computed, onDeactivated, onUnmounted, ref, shallowRef, watch } from 'vue'
import { sessionVersion } from '../api/client'
import { saveBlob } from '../api/workspaceDownload'
import ExportDialog from './ExportDialog.vue'
import type { ExportImage, ImageFormat } from './plotExport'

const props = defineProps<{
  settings: string
  render: (format: ImageFormat, signal: AbortSignal) => Promise<ExportImage>
  isCurrent: () => boolean
  disabled?: boolean
  filenameLabel?: string
}>()
const filename = defineModel<string>({ required: true })
const dialog = ref<InstanceType<typeof ExportDialog>>()
const format = ref<ImageFormat>('svg')
const preview = ref('')
const file = shallowRef<ExportImage>()
const busy = ref(false)
const error = ref('')
const session = ref<number>()
const stale = computed(() => session.value !== sessionVersion() || !props.isCurrent())
let operation: AbortController | undefined
function clear() {
  operation?.abort()
  operation = undefined
  busy.value = false
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  file.value = undefined
  error.value = ''
}
watch([() => props.settings, format], clear)
onDeactivated(() => dialog.value?.close())
onUnmounted(clear)
function open() {
  clear()
  session.value = sessionVersion()
  dialog.value?.open()
}
defineExpose({ open })

async function run(download: boolean) {
  const controller = new AbortController()
  operation = controller
  busy.value = true
  error.value = ''
  const check = () => {
    controller.signal.throwIfAborted()
    if (stale.value) throw new Error('图形来源已改变，请重新打开导出窗口。')
  }
  try {
    check()
    const output = file.value ?? (await props.render(format.value, controller.signal))
    check()
    file.value = output
    if (download) {
      await output.verify?.()
      check()
      const name = filename.value.trim().replace(/\.(?:svg|png|pdf)$/i, '')
      saveBlob(output.file, `${name}.${format.value}`)
    } else if (!preview.value) {
      preview.value = URL.createObjectURL(output.preview ?? output.file)
    }
  } catch (cause) {
    if (!controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (operation === controller) busy.value = false
  }
}
</script>

<template>
  <ExportDialog ref="dialog" title="图片导出" @close="clear">
    <div class="image-export-grid">
      <fieldset class="image-settings" :disabled="busy || disabled || stale">
        <div class="field-grid">
          <label
            >文件名<input
              v-model="filename"
              maxlength="180"
              :aria-label="filenameLabel ?? '文件名'"
          /></label>
          <label
            >格式<select v-model="format" aria-label="图片格式">
              <option value="svg">SVG</option>
              <option value="png">PNG</option>
              <option value="pdf">PDF</option>
            </select></label
          >
        </div>
        <slot :format="format" />
      </fieldset>
      <section class="image-preview" aria-label="图片导出预览">
        <img v-if="preview && !stale" :src="preview" alt="按导出设置生成的图片预览" />
        <p v-else-if="!busy && !error && !stale" class="muted">选择版式后点击「预览图片」。</p>
        <p v-if="stale" role="status">图形来源已改变，请重新打开导出窗口。</p>
        <p v-if="busy" role="status">正在生成 {{ format.toUpperCase() }}…</p>
        <p v-if="error" role="alert" class="state-note">{{ error }}</p>
      </section>
    </div>
    <template #footer>
      <button class="preview" :disabled="busy || disabled || stale" @click="run(false)">
        预览图片
      </button>
      <button
        class="download"
        :disabled="busy || disabled || stale || !filename.trim()"
        @click="run(true)"
      >
        下载图片
      </button>
    </template>
  </ExportDialog>
</template>

<style scoped>
.image-export-grid {
  display: grid;
  grid-template-columns: minmax(310px, 380px) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.image-settings {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 0;
  margin: 0;
  border: 0;
}
.image-settings :deep(.field-grid) {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.image-preview {
  min-height: 320px;
  display: grid;
  align-content: center;
  justify-items: center;
  padding: 10px;
  border: 1px solid #dbe4ed;
  background: #f4f7fa;
  overflow: auto;
}
.image-preview img {
  max-width: 100%;
  max-height: 650px;
  object-fit: contain;
}
</style>
