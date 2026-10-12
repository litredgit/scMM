import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError, request } from '../api/client'
import type { Configuration, WorkspaceView } from '../api/types'

export const useWorkspace = defineStore('workspace', () => {
  const current = ref<WorkspaceView | null>(null)
  const configuration = ref<Configuration | null>(null)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const project = computed(() => current.value?.project ?? null)
  let heartbeat: ReturnType<typeof setInterval> | undefined

  async function run<T>(action: () => Promise<T>, success = ''): Promise<T | undefined> {
    if (busy.value) return
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await action()
      notice.value = success
      return result
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      if (cause instanceof ApiError && cause.code === 'workspace_missing') {
        current.value = null
        if (heartbeat) clearInterval(heartbeat)
      }
    } finally {
      busy.value = false
    }
  }

  async function start() {
    await run(async () => {
      configuration.value = await request<Configuration>('/configuration')
      current.value = await request<WorkspaceView>('/workspaces', { method: 'POST' })
      if (heartbeat) clearInterval(heartbeat)
      heartbeat = setInterval(async () => {
        if (busy.value || !current.value) return
        try {
          // Keep the workspace alive; never replace state with an older heartbeat.
          await request('/workspace', { workspace: current.value.workspace_id })
        } catch (cause) {
          if (cause instanceof ApiError && cause.code === 'workspace_missing') {
            error.value = cause.message
            current.value = null
            clearInterval(heartbeat)
          }
        }
      }, 30_000)
    })
  }

  async function mutate(
    path: string,
    body: Record<string, unknown> = {},
    method = 'POST',
    success = '',
  ) {
    if (!current.value) return
    return run(async () => {
      current.value = await request<WorkspaceView>(`/workspace${path}`, {
        method,
        workspace: current.value!.workspace_id,
        body: { ...body, revision: current.value!.revision },
      })
      return current.value
    }, success)
  }

  async function refresh() {
    if (!current.value) return
    await run(async () => {
      current.value = await request<WorkspaceView>('/workspace', {
        workspace: current.value!.workspace_id,
      })
    })
  }

  function release() {
    if (heartbeat) clearInterval(heartbeat)
    if (!current.value) return
    void fetch('/api/v1/workspace', {
      method: 'DELETE',
      keepalive: true,
      headers: { 'X-SCMM-Client': 'web', 'X-SCMM-Workspace': current.value.workspace_id },
    }).catch(() => {})
  }

  return {
    current,
    configuration,
    project,
    busy,
    error,
    notice,
    start,
    mutate,
    refresh,
    run,
    release,
  }
})
