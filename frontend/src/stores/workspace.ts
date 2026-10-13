import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { ApiError, request } from '../api/client'
import type { Configuration, WorkspaceView } from '../api/types'

export const useWorkspace = defineStore('workspace', () => {
  const current = ref<WorkspaceView | null>(null)
  const configuration = ref<Configuration | null>(null)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const analysisDraft = ref<{
    path: string
    analysis: Record<string, unknown>
    legend: string
  } | null>(null)
  const task = ref('暂无活动任务')
  const project = computed(() => current.value?.project ?? null)
  watch(
    () => project.value?.path,
    () => {
      analysisDraft.value = null
      task.value = '暂无活动任务'
    },
    { flush: 'sync' },
  )
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
      if (cause instanceof ApiError && cause.code === 'extraction_not_started' && current.value) {
        current.value = await request<WorkspaceView>('/workspace', {
          workspace: current.value.workspace_id,
        })
      }
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
      if (path === '/project/save' && analysisDraft.value?.path === project.value?.path) {
        current.value = await request<WorkspaceView>('/workspace/analysis/settings', {
          method: 'PUT',
          workspace: current.value!.workspace_id,
          body: {
            revision: current.value!.revision,
            analysis: analysisDraft.value!.analysis,
            legend: analysisDraft.value!.legend,
          },
        })
      }
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

  async function read<T>(path: string, body?: Record<string, unknown>): Promise<T | undefined> {
    if (!current.value) return
    try {
      return await request<T>(`/workspace${path}`, {
        workspace: current.value.workspace_id,
        method: body ? 'POST' : 'GET',
        body,
      })
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function command<T>(
    path: string,
    body: Record<string, unknown> = {},
    method = 'POST',
  ): Promise<T | undefined> {
    if (!current.value) return
    return run(async () => {
      const response = await request<{ workspace: WorkspaceView; value: T }>(`/workspace${path}`, {
        workspace: current.value!.workspace_id,
        method,
        body: { ...body, revision: current.value!.revision },
      })
      current.value = response.workspace
      return response.value
    })
  }

  async function inspect<T>(
    path: string,
    body: Record<string, unknown> = {},
  ): Promise<T | undefined> {
    if (!current.value) return
    return run(() =>
      request<T>(`/workspace${path}`, {
        workspace: current.value!.workspace_id,
        method: 'POST',
        body: { ...body, revision: current.value!.revision },
      }),
    )
  }

  async function download(kind: string, filename: string, key = '') {
    if (!current.value) return
    await run(async () => {
      const query = new URLSearchParams({ kind, filename, key })
      const response = await fetch(`/api/v1/workspace/results/download?${query}`, {
        headers: { 'X-SCMM-Workspace': current.value!.workspace_id },
        cache: 'no-store',
      })
      if (!response.ok) {
        const value = await response.json()
        throw new Error(value.error?.message ?? '下载失败。')
      }
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
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
    read,
    command,
    inspect,
    download,
    analysisDraft,
    task,
  }
})
