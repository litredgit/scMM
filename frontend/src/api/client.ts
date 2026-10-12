export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function request<T>(
  path: string,
  options: {
    method?: string
    body?: unknown
    workspace?: string
    signal?: AbortSignal
  } = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: options.method ?? 'GET',
    headers: {
      'X-SCMM-Client': 'web',
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(options.workspace ? { 'X-SCMM-Workspace': options.workspace } : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    cache: 'no-store',
  })
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    const error = value.error ?? {}
    const details = error.details
      ?.map((item: { field: string; message: string }) => `${item.field}: ${item.message}`)
      .join('；')
    throw new ApiError(
      [error.message ?? `请求失败（${response.status}）`, details].filter(Boolean).join(' '),
      error.code ?? 'http_error',
      response.status,
    )
  }
  return response.status === 204 ? (undefined as T) : response.json()
}
