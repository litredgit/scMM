import { ApiError, authenticatedFetch, sessionVersion, ensureSession } from './client'

type DownloadOptions = {
  workspace: string
  method?: string
  body?: Record<string, unknown>
  isCurrent(): boolean
}
/** Binary response ownership is checked after both the network wait and body decoding. */
export async function workspaceBlob(path: string, options: DownloadOptions): Promise<Blob> {
  const version = sessionVersion()
  const check = () => {
    ensureSession(version)
    if (!options.isCurrent())
      throw new ApiError('工作区或来源已改变，旧下载已丢弃。', 'operation_stale', 409)
  }
  check()
  const response = await authenticatedFetch(`/api/v1/workspace${path}`, {
    method: options.method ?? 'GET',
    headers: {
      'X-SCMM-Workspace': options.workspace,
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  check()
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    check()
    throw new ApiError(
      value.error?.message ?? '下载失败。',
      value.error?.code ?? 'http_error',
      response.status,
    )
  }
  const blob = await response.blob()
  check()
  return blob
}
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.click()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
