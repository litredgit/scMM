import { pageId } from './pageIdentity'

// One lease per document, including logged-out and hidden documents.
let token = ''
let closing = false
let sending = false
let queued = false
let route = '/login'
let workspaceId: string | undefined
let ready: Promise<void> | undefined
const validRoutes = new Set([
  '/projects',
  '/samples',
  '/raw',
  '/extraction',
  '/preprocess',
  '/analysis',
  '/results',
  '/parameters',
  '/account',
  '/admin/monitor',
  '/login',
])
function body(closed = false, suspended = false) {
  return {
    id: pageId,
    route,
    workspace_id: workspaceId,
    visibility: suspended ? 'suspended' : document.visibilityState,
    ...(token ? { token, closed } : {}),
  }
}
async function send(closed = false, suspended = false) {
  if (closing && !closed) return
  if (sending && !closed && !suspended) {
    queued = true
    return
  }
  sending = true
  try {
    const response = await fetch(`/api/v1/presence/${token ? 'heartbeat' : 'register'}`, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      keepalive: closed || suspended,
      headers: { 'Content-Type': 'application/json', 'X-SCMM-Client': 'web' },
      body: JSON.stringify(body(closed, suspended)),
    })
    if (response.ok && !token) token = (await response.json()).token
  } catch {
    /* An unconfirmed lease remains visible to administrators. */
  } finally {
    sending = false
    if (queued && !closing) {
      queued = false
      void send()
    }
  }
}
export function updatePresence(path: string, authenticated: boolean, workspace?: string) {
  route = authenticated && validRoutes.has(path) ? path : '/login'
  workspaceId = authenticated ? workspace : undefined
  void send()
}
export function startPresence() {
  ready ??= send()
  const timer = window.setInterval(() => void send(), 20000)
  const visibility = () => void send()
  const hide = (event: PageTransitionEvent) => {
    if (!event.persisted) {
      closing = true
      void send(true)
    } else void send(false, true)
  }
  const show = () => {
    closing = false
    void send()
  }
  document.addEventListener('visibilitychange', visibility)
  window.addEventListener('pagehide', hide)
  window.addEventListener('pageshow', show)
  return {
    ready,
    stop: () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', visibility)
      window.removeEventListener('pagehide', hide)
      window.removeEventListener('pageshow', show)
    },
  }
}
