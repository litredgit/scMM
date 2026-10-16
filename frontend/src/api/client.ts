import { pageId } from './pageIdentity'

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message)
  }
}

let csrf = ''
let generation = 0
let sessionController = new AbortController()
let userActivity = 0
let sentActivity = 0
for (const name of ['pointerdown', 'keydown']) {
  window.addEventListener(
    name,
    () => {
      userActivity += 1
    },
    { passive: true },
  )
}

export function setSession(token: string) {
  sessionController.abort()
  sessionController = new AbortController()
  generation += 1
  csrf = token
}

export function sessionVersion() {
  return generation
}
export function ensureSession(version: number) {
  if (version !== generation)
    throw new ApiError('登录状态已改变，旧请求结果已丢弃。', 'session_changed', 409)
}

export function sessionHeaders(activity = true): Record<string, string> {
  const active = activity && userActivity > sentActivity
  if (active) sentActivity = userActivity
  return {
    'X-SCMM-Client': 'web',
    'X-SCMM-Page-ID': pageId,
    ...(csrf ? { 'X-SCMM-CSRF': csrf } : {}),
    ...(active ? { 'X-SCMM-Activity': 'user' } : {}),
  }
}

export async function authenticatedFetch(path: string, options: RequestInit = {}) {
  const epoch = generation
  const hadSession = Boolean(csrf)
  const response = await fetch(path, {
    ...options,
    headers: { ...sessionHeaders(), ...options.headers },
    credentials: 'same-origin',
    cache: 'no-store',
    signal: options.signal
      ? AbortSignal.any([options.signal, sessionController.signal])
      : sessionController.signal,
  })
  if (epoch !== generation)
    throw new ApiError('登录状态已改变，旧请求结果已丢弃。', 'session_changed', 409)
  if (response.status === 401 && hadSession && !path.endsWith('/auth/login')) {
    setSession('')
    window.dispatchEvent(new Event('scmm-auth-expired'))
  }
  return response
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
  const version = sessionVersion()
  const response = await authenticatedFetch(`/api/v1${path}`, {
    method: options.method ?? 'GET',
    headers: {
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(options.workspace ? { 'X-SCMM-Workspace': options.workspace } : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })
  if (!response.ok) {
    const value = await response.json().catch(() => ({}))
    if (response.status !== 401) ensureSession(version)
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
  const value = response.status === 204 ? (undefined as T) : await response.json()
  ensureSession(version)
  return value
}
