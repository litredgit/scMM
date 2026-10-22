import { pageId, renewPageIdentity } from './pageIdentity'

// One lease per document, including logged-out and hidden documents.
function freshSecret() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('')
}
let token = freshSecret()
let hasLease = false
let closing = false
let sending = false
let queued = false
let suspended = false
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
    closed,
  }
}
function post(closed: boolean, suspend: boolean) {
  return fetch(`/api/v1/presence/${hasLease ? 'heartbeat' : 'register'}`, {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    keepalive: true,
    headers: { 'Content-Type': 'application/json', 'X-SCMM-Client': 'web' },
    body: JSON.stringify({
      ...body(closed, suspend),
      ...(hasLease ? { token } : { registration_secret: token }),
    }),
  })
}
async function send(closed = false, suspend = false) {
  if (closing && !closed) return
  if (closed) closing = true
  suspended = suspend
  queued = true
  if (sending) {
    // Unload may destroy this JS context before registration's response arrives.
    // A credential chosen before registering lets this terminal message win in
    // either arrival order, without waiting for that response.
    if (closed) void post(true, suspend).catch(() => {})
    return
  }
  sending = true
  try {
    let renewed = false
    while (queued) {
      queued = false
      const registered = hasLease
      const identity = pageId
      const response = await post(closing, suspended)
      if (response.ok && !registered) {
        hasLease = true
        // pagehide can arrive while registration is in flight. Close that same
        // lease after receiving its token, rather than registering a second time.
        if (closing) queued = true
      } else if (
        (response.status === 409 || (registered && response.status === 403)) &&
        !closing &&
        identity === pageId &&
        !renewed
      ) {
        // A resumed cached document may have been explicitly confirmed closed.
        // Acquire a new identity; never reopen a closed lease with a late heartbeat.
        token = freshSecret()
        hasLease = false
        renewPageIdentity()
        renewed = true
        queued = true
      }
    }
  } catch {
    /* An unconfirmed lease remains visible to administrators. */
  } finally {
    sending = false
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
