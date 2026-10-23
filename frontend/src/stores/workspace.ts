import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { serialPolling } from '../api/polling'
import { operationDetails, operationValue, phaseLabels } from '../api/operation'
import type {
  OperationDetails,
  OperationOutcome,
  OperationScope,
  OperationState,
} from '../api/operation'
import {
  ApiError,
  request,
  authenticatedFetch,
  sessionHeaders,
  sessionVersion,
  ensureSession,
} from '../api/client'
import type { AnalysisTransport } from '../features/analysis/types'
import type { Batch, Configuration, WorkspaceView } from '../api/types'

export const useWorkspace = defineStore('workspace', () => {
  const current = ref<WorkspaceView | null>(null)
  const configuration = ref<Configuration | null>(null)
  const busy = ref(false)
  const operation = ref<OperationState>()
  let operationGeneration = 0
  const operationMessage = computed(() =>
    busy.value && operation.value
      ? `${operation.value.label}：${phaseLabels[operation.value.phase]}`
      : '',
  )
  const maintenancePaused = ref(false)
  const error = ref('')
  const notice = ref('')
  const analysisDraft = ref<{
    path: string
    analysis: Record<string, unknown>
    legend: string
  } | null>(null)
  const selectedCells = ref<string[]>([])
  function selectCell(cell: string) {
    selectedCells.value = [...selectedCells.value.filter((c) => c !== cell), cell].slice(-2)
  }
  const task = ref('暂无活动任务')
  const batches = ref<Batch[] | null>(null)
  let batchesRequest: { key: string; promise: Promise<Batch[] | undefined> } | undefined
  async function refreshBatches() {
    if (!current.value || !project.value) return
    const key = JSON.stringify([
      current.value.workspace_id,
      project.value.path,
      current.value.revision,
    ])
    if (batchesRequest?.key === key) return batchesRequest.promise
    const promise = read<Batch[]>('/extraction/batches').then((value) => {
      if (value) batches.value = value
      return value
    })
    batchesRequest = { key, promise }
    try {
      return await promise
    } finally {
      if (batchesRequest?.promise === promise) batchesRequest = undefined
    }
  }
  const project = computed(() => current.value?.project ?? null)
  watch(
    () =>
      JSON.stringify([
        project.value?.path,
        project.value?.dataset?.id,
        project.value?.dataset?.revision,
      ]),
    () => (selectedCells.value = []),
  )

  watch(
    () => project.value?.path,
    () => {
      analysisDraft.value = null
      batches.value = null
      task.value = '暂无活动任务'
    },
    { flush: 'sync' },
  )
  let heartbeat: ReturnType<typeof serialPolling> | undefined

  async function run<T>(
    action: (scope: OperationScope) => Promise<T>,
    success = '',
    details: OperationDetails = { label: '处理当前操作', phase: 'running' },
  ): Promise<OperationOutcome<T>> {
    if (busy.value)
      return { status: 'skipped', reason: 'busy', active: operation.value?.label ?? '当前操作' }
    const id = ++operationGeneration
    const session = sessionVersion()
    const originWorkspace = current.value?.workspace_id
    let open = true
    const valid = () => open && operationGeneration === id && sessionVersion() === session
    const scope: OperationScope = {
      isCurrent: valid,
      update(value) {
        if (valid() && operation.value?.id === id)
          operation.value = { ...operation.value, ...value }
      },
    }
    operation.value = { id, ...details }
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      const value = await action(scope)
      if (!valid()) return { status: 'stale' }
      if (error.value) {
        notice.value = ''
        scope.update({ phase: 'failed' })
        return { status: 'failed', error: error.value }
      }
      if (success) notice.value = success
      scope.update({ phase: 'succeeded' })
      return { status: 'succeeded', value }
    } catch (cause) {
      if (!valid()) return { status: 'stale' }
      if (cause instanceof ApiError && cause.code === 'operation_stale') {
        scope.update({ phase: 'stale' })
        return { status: 'stale' }
      }
      const message = cause instanceof Error ? cause.message : String(cause)
      error.value = message
      notice.value = ''
      if (cause instanceof ApiError && cause.code === 'extraction_not_started' && current.value) {
        const workspace = current.value.workspace_id
        scope.update({ phase: 'recovering' })
        try {
          const value = await request<WorkspaceView>('/workspace', { workspace })
          if (valid() && current.value?.workspace_id === workspace) current.value = value
        } catch {
          if (valid()) error.value = `${message} 状态刷新失败，请手动刷新。`
        }
      }
      if (!valid()) return { status: 'stale' }
      if (
        cause instanceof ApiError &&
        cause.code === 'workspace_missing' &&
        current.value?.workspace_id === originWorkspace
      ) {
        current.value = null
        heartbeat?.stop()
      }
      scope.update({ phase: 'failed' })
      return { status: 'failed', error: error.value }
    } finally {
      if (operationGeneration === id && !valid() && operation.value?.id === id)
        operation.value = { ...operation.value, phase: 'stale' }
      open = false
      if (operationGeneration === id) busy.value = false
    }
  }

  async function start() {
    return run(
      async (scope) => {
        const config = await request<Configuration>('/configuration')
        if (!scope.isCurrent()) return
        configuration.value = config
        const previous = sessionStorage.getItem('scmm-workspace')
        if (previous) {
          try {
            const resumed = await request<WorkspaceView>('/workspaces/resume', {
              method: 'POST',
              body: { workspace_id: previous },
            })
            if (!scope.isCurrent()) return
            current.value = resumed
          } catch (cause) {
            if (!(cause instanceof ApiError) || ![403, 404].includes(cause.status)) throw cause
            if (!scope.isCurrent()) return
            current.value = null
          }
        }
        if (!current.value) {
          const created = await request<WorkspaceView>('/workspaces', { method: 'POST' })
          if (!scope.isCurrent()) return
          current.value = created
        }
        sessionStorage.setItem('scmm-workspace', current.value.workspace_id)
        heartbeat?.stop()
        heartbeat = serialPolling(
          async (isCurrent) => {
            const selected = current.value
            if (busy.value || !selected) return
            try {
              // Keep alive without publishing an older heartbeat as scientific state.
              await request('/workspace', { workspace: selected.workspace_id })
            } catch (cause) {
              if (
                isCurrent() &&
                current.value?.workspace_id === selected.workspace_id &&
                cause instanceof ApiError &&
                cause.code === 'workspace_missing'
              ) {
                error.value = cause.message
                current.value = null
                heartbeat?.stop()
              }
            }
          },
          30_000,
          (cause) => {
            error.value = cause instanceof Error ? cause.message : String(cause)
          },
        )
        heartbeat.start(false)
      },
      '',
      { label: '连接工作区', phase: 'reading' },
    )
  }

  async function mutate(
    path: string,
    body: Record<string, unknown> = {},
    method = 'POST',
    success = '',
  ) {
    if (!current.value) return
    return operationValue(
      await run(
        async (scope) => {
          const original = current.value!
          let expectedRevision = original.revision
          const valid = () =>
            scope.isCurrent() &&
            current.value?.workspace_id === original.workspace_id &&
            current.value?.revision === expectedRevision
          if (path === '/project/save' && analysisDraft.value?.path === project.value?.path) {
            const saved = await request<WorkspaceView>('/workspace/analysis/settings', {
              method: 'PUT',
              workspace: current.value!.workspace_id,
              body: {
                revision: current.value!.revision,
                analysis: analysisDraft.value!.analysis,
                legend: analysisDraft.value!.legend,
              },
            })
            if (!valid())
              throw new ApiError('项目已改变，旧保存请求已丢弃。', 'operation_stale', 409)
            current.value = saved
            expectedRevision = saved.revision
          }
          const value = await request<WorkspaceView>(`/workspace${path}`, {
            method,
            workspace: current.value!.workspace_id,
            body: { ...body, revision: current.value!.revision },
          })
          if (!valid()) throw new ApiError('项目已改变，旧操作结果已丢弃。', 'operation_stale', 409)
          current.value = value
          return value
        },
        success,
        operationDetails(path, body),
      ),
    )
  }

  // Hold the shared lock across calculation, workspace update, report and plots.
  async function analysisTransaction(action: (api: AnalysisTransport) => Promise<unknown>) {
    if (!current.value) return
    const workspace = current.value.workspace_id
    const projectPath = project.value?.path
    const datasetId = project.value?.dataset?.id
    let expectedRevision = current.value.revision
    let scopeCurrent = () => true
    const valid = () =>
      scopeCurrent() &&
      current.value?.workspace_id === workspace &&
      project.value?.path === projectPath &&
      project.value?.dataset?.id === datasetId &&
      current.value?.revision === expectedRevision
    const check = () => {
      if (!valid()) throw new Error('当前项目或数据已改变，旧分析请求已丢弃。')
    }
    return run(async (scope) => {
      scopeCurrent = scope.isCurrent
      const api: AnalysisTransport = {
        isCurrent: valid,
        async read<T>(path: string, body?: Record<string, unknown>) {
          check()
          scope.update(body ? operationDetails(path, body) : { phase: 'refreshing' })
          const value = await request<T>(`/workspace${path}`, {
            workspace,
            method: body ? 'POST' : 'GET',
            body,
          })
          check()
          return value
        },
        async mutate(path, body, method = 'POST') {
          check()
          scope.update(operationDetails(path, body))
          const value = await request<WorkspaceView>(`/workspace${path}`, {
            workspace,
            method,
            body: { ...body, revision: current.value!.revision },
          })
          check()
          current.value = value
          expectedRevision = value.revision
          return value
        },
        async command<T>(path: string, body: Record<string, unknown>) {
          check()
          scope.update(operationDetails(path, body))
          const response = await request<{ workspace: WorkspaceView; value: T }>(
            `/workspace${path}`,
            {
              workspace,
              method: 'POST',
              body: { ...body, revision: current.value!.revision },
            },
          )
          check()
          current.value = response.workspace
          expectedRevision = response.workspace.revision
          return response.value
        },
      }
      try {
        await action(api)
      } catch (cause) {
        if (valid()) throw cause
        scope.update({ phase: 'stale' })
        throw new ApiError('当前项目或数据已改变，旧操作结果已丢弃。', 'operation_stale', 409)
      }
    })
  }

  async function refresh() {
    if (!current.value) return
    const snapshot = current.value
    return run(
      async (scope) => {
        const value = await request<WorkspaceView>('/workspace', {
          workspace: snapshot.workspace_id,
        })
        if (
          !scope.isCurrent() ||
          current.value?.workspace_id !== snapshot.workspace_id ||
          current.value?.revision !== snapshot.revision
        )
          throw new ApiError('工作区已改变，旧刷新结果已丢弃。', 'operation_stale', 409)
        current.value = value
      },
      '',
      { label: '刷新工作区', phase: 'refreshing' },
    )
  }

  async function read<T>(
    path: string,
    body?: Record<string, unknown>,
    accept: () => boolean = () => true,
  ): Promise<T | undefined> {
    if (!current.value) return
    const snapshot = current.value
    const feedback = operationGeneration
    const valid = () =>
      accept() &&
      current.value?.workspace_id === snapshot.workspace_id &&
      current.value?.revision === snapshot.revision
    try {
      const value = await request<T>(`/workspace${path}`, {
        workspace: snapshot.workspace_id,
        method: body ? 'POST' : 'GET',
        body,
      })
      if (valid()) return value
    } catch (cause) {
      if (valid() && feedback === operationGeneration && !busy.value && !error.value)
        error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function command<T>(
    path: string,
    body: Record<string, unknown> = {},
    method = 'POST',
  ): Promise<T | undefined> {
    if (!current.value) return
    const snapshot = current.value
    return operationValue(
      await run(
        async (scope) => {
          const response = await request<{ workspace: WorkspaceView; value: T }>(
            `/workspace${path}`,
            {
              workspace: current.value!.workspace_id,
              method,
              body: { ...body, revision: current.value!.revision },
            },
          )
          if (
            !scope.isCurrent() ||
            current.value?.workspace_id !== snapshot.workspace_id ||
            current.value?.revision !== snapshot.revision
          )
            throw new ApiError('项目已改变，旧操作结果已丢弃。', 'operation_stale', 409)
          current.value = response.workspace
          return response.value
        },
        '',
        operationDetails(path, body),
      ),
    )
  }

  async function inspect<T>(
    path: string,
    body: Record<string, unknown> = {},
  ): Promise<T | undefined> {
    if (!current.value) return
    const original = current.value
    return operationValue(
      await run(
        async (scope) => {
          const value = await request<T>(`/workspace${path}`, {
            workspace: original.workspace_id,
            method: 'POST',
            body: { ...body, revision: original.revision },
          })
          if (
            !scope.isCurrent() ||
            current.value?.workspace_id !== original.workspace_id ||
            current.value?.revision !== original.revision
          )
            throw new ApiError('项目已改变，旧检查结果已丢弃。', 'operation_stale', 409)
          return value
        },
        '',
        operationDetails(path, body),
      ),
    )
  }

  async function download(kind: string, filename: string, key = '') {
    if (!current.value) return
    const snapshot = current.value
    return run(
      async (scope) => {
        const version = sessionVersion()
        const query = new URLSearchParams({ kind, filename, key })
        const response = await authenticatedFetch(`/api/v1/workspace/results/download?${query}`, {
          headers: { 'X-SCMM-Workspace': current.value!.workspace_id },
          cache: 'no-store',
        })
        if (!response.ok) {
          const value = await response.json()
          throw new Error(value.error?.message ?? '下载失败。')
        }
        const blob = await response.blob()
        ensureSession(version)
        if (
          !scope.isCurrent() ||
          current.value?.workspace_id !== snapshot.workspace_id ||
          current.value?.revision !== snapshot.revision
        )
          throw new ApiError('工作区已改变，旧下载已丢弃。', 'operation_stale', 409)
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = filename
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      },
      '',
      { label: '下载结果', phase: 'downloading' },
    )
  }

  function release() {
    heartbeat?.stop()
    if (!current.value) return
    void fetch('/api/v1/workspace', {
      method: 'DELETE',
      keepalive: true,
      headers: { ...sessionHeaders(false), 'X-SCMM-Workspace': current.value.workspace_id },
    }).catch(() => {})
  }

  function reset() {
    operationGeneration++
    busy.value = false
    operation.value = undefined
    heartbeat?.stop()
    current.value = null
    configuration.value = null
    analysisDraft.value = null
    batches.value = null
    error.value = ''
    notice.value = ''
    task.value = '暂无活动任务'
  }

  return {
    selectedCells,
    selectCell,
    maintenancePaused,
    current,
    configuration,
    project,
    busy,
    operation,
    operationMessage,
    error,
    notice,
    start,
    mutate,
    refresh,
    run,
    release,
    reset,
    read,
    command,
    inspect,
    download,
    analysisDraft,
    analysisTransaction,
    task,
    batches,
    refreshBatches,
  }
})
