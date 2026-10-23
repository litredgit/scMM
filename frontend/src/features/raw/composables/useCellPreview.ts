import { ref, onMounted, onUnmounted, onActivated, onDeactivated, type Ref } from 'vue'
import { useWorkspace } from '../../../stores/workspace'
import { serialPolling } from '../../../api/polling'
import type { Job, Figure, DataTable } from '../../../api/types'

export type CellPreviewValue = {
  figure: Figure
  table: DataTable
  parameters: Record<string, unknown>
  cell_count: number
  reused: boolean
}
type Options = {
  sample: Ref<string>
  parameters(): Record<string, unknown>
  collected(value: CellPreviewValue): void
  invalidate(): void
}
export function useCellPreview(options: Options) {
  const store = useWorkspace()
  const job = ref<Job>(),
    jobNote = ref(''),
    cellCount = ref<number>()
  let editGeneration = 0,
    jobGeneration = 0
  function edited() {
    editGeneration++
    options.invalidate()
    cellCount.value = undefined
    if (job.value) jobNote.value = '参数已编辑；运行中的旧预览完成后不会应用。'
  }
  function reset() {
    job.value = undefined
    cellCount.value = undefined
    jobNote.value = ''
    editGeneration++
  }
  async function startPreview() {
    const value = await store.command<Job>('/raw/preview', {
      sample_id: options.sample.value,
      parameters: options.parameters(),
    })
    if (value) {
      job.value = value
      jobGeneration = editGeneration
      jobNote.value = '细胞预览已启动，可继续操作其他步骤。'
    }
  }
  async function poll(isCurrent: () => boolean) {
    if (!job.value || !store.project) return
    const status = await store.read<Job | null>('/raw/preview', undefined, isCurrent)
    if (!isCurrent() || !status || !job.value || status.id !== job.value.id) return
    job.value = status
    if (status.status === 'failed') {
      jobNote.value = status.message
      store.task = `细胞预览：${status.message}`
      job.value = undefined
      return
    }
    if (status.status !== 'ready') {
      jobNote.value = status.message
      store.task = `细胞预览：${status.message}`
      return
    }
    if (store.busy) return
    if (jobGeneration !== editGeneration || status.revision !== store.current?.revision) {
      jobNote.value = '样本或参数已改变，旧预览未应用，请重新预览。'
      job.value = undefined
      return
    }
    const value = await store.command<{
      figure: Figure
      table: DataTable
      parameters: Record<string, unknown>
      cell_count: number
      reused: boolean
    }>('/raw/preview/collect', { job_id: status.id })
    job.value = undefined
    if (value) {
      options.collected(value)
      cellCount.value = value.cell_count
      jobNote.value = `预览完成，${value.cell_count} 个细胞${value.reused ? '，已复用有效缓存' : ''}。项目仍需主动保存。`
    }
  }

  const polling = serialPolling(poll, 1500, (cause) => {
    store.error = cause instanceof Error ? cause.message : String(cause)
  })
  function startPolling() {
    polling.start(false)
  }
  onMounted(startPolling)
  onActivated(startPolling)
  onDeactivated(polling.stop)
  onUnmounted(polling.stop)
  return { job, jobNote, cellCount, startPreview, edited, reset }
}
