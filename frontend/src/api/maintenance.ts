import { captureViews, restoreViews, clearPendingViews, viewRevision } from './viewState'
import { watch, nextTick } from 'vue'
import { pageId } from './pageIdentity'
import { request, sessionHeaders } from './client'
import { useWorkspace } from '../stores/workspace'
import { useAuth } from '../stores/auth'
import type { Router } from 'vue-router'

type Control = { key: string; value: string; checked: boolean }
function controls(): Control[] {
  const counts = new Map<string, number>()
  return Array.from(
    document.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
      'main input,main select,main textarea',
    ),
  )
    .filter((el) => !['password', 'file'].includes(el.type))
    .map((el) => {
      const name =
        el.getAttribute('aria-label') ||
        el.id ||
        el.closest('label')?.textContent?.trim() ||
        el.tagName
      const count = counts.get(name) || 0
      counts.set(name, count + 1)
      return {
        key: name + '#' + count,
        value: el.value,
        checked: el instanceof HTMLInputElement && el.checked,
      }
    })
}
function restoreControls(saved: Control[]) {
  const values = new Map(saved.map((v) => [v.key, v])),
    counts = new Map<string, number>()
  for (const el of document.querySelectorAll<
    HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
  >('main input,main select,main textarea')) {
    if (['password', 'file'].includes(el.type)) continue
    const name =
        el.getAttribute('aria-label') ||
        el.id ||
        el.closest('label')?.textContent?.trim() ||
        el.tagName,
      count = counts.get(name) || 0
    counts.set(name, count + 1)
    const value = values.get(name + '#' + count)
    if (!value) continue
    el.value = value.value
    if (el instanceof HTMLInputElement) el.checked = value.checked
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }
}
export function startMaintenance(router: Router) {
  const tabId = sessionStorage.getItem('scmm-tab-id') || pageId
  sessionStorage.setItem('scmm-tab-id', tabId)
  const store = useWorkspace(),
    auth = useAuth()
  let stopped = false,
    timer: ReturnType<typeof setTimeout> | undefined,
    nonce = '',
    restored = '',
    working = false
  let restoredForms = false
  const appliedRoutes = new Set<string>()
  let savedRevision = -1,
    formRevision = 0
  const forms: Record<string, Control[]> = {}
  const capture = () => {
    if (auth.user && store.current && router.currentRoute.value.path !== '/account') {
      forms[router.currentRoute.value.path] = controls()
      formRevision++
    }
  }
  const stopOwner = watch(
    () => JSON.stringify([auth.user?.id, store.current?.workspace_id, store.project?.path]),
    (value, previous) => {
      const scope = JSON.parse(value),
        before = previous ? JSON.parse(previous) : []
      if (scope[0] !== before[0] || scope[1] !== before[1]) restored = ''
      clearPendingViews()
      for (const key of Object.keys(forms)) delete forms[key]
      restoredForms = false
      appliedRoutes.clear()
      if (value !== previous) savedRevision = -1
      formRevision++
      nonce = ''
    },
    { flush: 'sync' },
  )
  document.addEventListener('input', capture)
  document.addEventListener('change', capture)
  const identity = () =>
    JSON.stringify([auth.user?.id, store.current?.workspace_id, store.project?.path])
  const unwatch = watch(
    () => router.currentRoute.value.path,
    async () => {
      await nextTick()
      const saved = forms[router.currentRoute.value.path]
      if (restoredForms && saved && !appliedRoutes.has(router.currentRoute.value.path)) {
        appliedRoutes.add(router.currentRoute.value.path)
        const target = identity(),
          route = router.currentRoute.value.path,
          edits = formRevision
        setTimeout(() => {
          if (
            identity() === target &&
            router.currentRoute.value.path === route &&
            edits === formRevision
          )
            restoreControls(saved)
        }, 200)
      }
    },
  )
  async function poll() {
    try {
      if (!auth.user || auth.user.must_change) return
      if (store.current && restored !== store.current.workspace_id) {
        restored = store.current.workspace_id
        const target = identity(),
          edits = formRevision,
          workspaceRevision = store.current.revision
        const current = () =>
          identity() === target &&
          formRevision === edits &&
          store.current?.revision === workspaceRevision
        const value = await request<{
          project_path?: string
          raw_unavailable?: string
          route?: string
          forms?: Record<string, Control[]>
          analysisDraft?: typeof store.analysisDraft
          selectedCells?: string[]
          views?: Parameters<typeof restoreViews>[0]
        }>('/workspace/maintenance/draft', { workspace: restored })
        if (!current()) return
        if (value.raw_unavailable) store.notice = value.raw_unavailable
        if (value.forms && value.project_path === (store.project?.path || '')) {
          restoredForms = true
          if (value.views) await restoreViews(value.views, current)
          if (!current()) return
          Object.assign(forms, value.forms)
          store.analysisDraft = value.analysisDraft || null
          store.selectedCells = value.selectedCells || []
          if (value.route) await router.replace(value.route)
          await nextTick()
          if (!current()) return
          const route = router.currentRoute.value.path
          const restoredEdits = formRevision
          setTimeout(() => {
            if (
              identity() === target &&
              router.currentRoute.value.path === route &&
              formRevision === restoredEdits
            )
              restoreControls(forms[route] || [])
          }, 500)
        }
      }
      const status = await request<{ request: { id: string } | null }>('/maintenance/status')
      store.maintenancePaused = Boolean(status.request)
      if (status.request?.id && nonce !== status.request.id && !store.busy && !working) {
        working = true
        try {
          const detail = { promises: [] as Promise<unknown>[] }
          window.dispatchEvent(new CustomEvent('scmm-before-maintenance', { detail }))
          await Promise.all(detail.promises)
          capture()
          await request(store.current ? '/workspace/maintenance/draft' : '/maintenance/draft', {
            method: 'PUT',
            workspace: store.current?.workspace_id,
            body: {
              tab_id: tabId,
              nonce: status.request.id,
              state: {
                project_path: store.project?.path || '',
                route: router.currentRoute.value.path,
                forms,
                views: captureViews(),
                analysisDraft: store.analysisDraft,
                selectedCells: store.selectedCells,
              },
            },
          })
          nonce = status.request.id
          store.notice = '会话已暂存，等待管理员完成维护。'
        } finally {
          working = false
        }
      }
      if (!status.request) {
        nonce = ''
        const revision = viewRevision() + formRevision
        if (store.current && !store.busy && revision !== savedRevision) {
          const owner = auth.user.id,
            workspace = store.current,
            target = identity()
          await request('/workspace/draft', {
            method: 'PUT',
            workspace: workspace.workspace_id,
            body: {
              revision: workspace.revision,
              state: {
                project_path: store.project?.path || '',
                route: router.currentRoute.value.path,
                forms,
                views: captureViews(),
                analysisDraft: store.analysisDraft,
                selectedCells: store.selectedCells,
              },
            },
          })
          if (auth.user?.id === owner && identity() === target) savedRevision = revision
        }
      }
    } catch (cause) {
      if (working) store.error = String(cause)
    } finally {
      if (!stopped) timer = setTimeout(poll, 2000)
    }
  }
  const suspend = () => {
    if (!store.current || !auth.user) return
    capture()
    const body = JSON.stringify({
      revision: store.current.revision,
      partial: true,
      state: {
        project_path: store.project?.path || '',
        route: router.currentRoute.value.path,
        forms,
        analysisDraft: store.analysisDraft,
        selectedCells: store.selectedCells,
      },
    })
    if (new TextEncoder().encode(body).length > 48000) return
    void fetch('/api/v1/workspace/draft', {
      method: 'PUT',
      headers: {
        ...sessionHeaders(false),
        'Content-Type': 'application/json',
        'X-SCMM-Workspace': store.current.workspace_id,
      },
      body,
      keepalive: true,
    }).catch(() => {})
  }
  window.addEventListener('pagehide', suspend)
  void poll()
  return () => {
    window.removeEventListener('pagehide', suspend)
    stopped = true
    clearTimeout(timer)
    unwatch()
    stopOwner()
    document.removeEventListener('input', capture)
    document.removeEventListener('change', capture)
  }
}
