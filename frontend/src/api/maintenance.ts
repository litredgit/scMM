import { captureViews, restoreViews, clearPendingViews, viewRevision } from './viewState'
import { watch, nextTick } from 'vue'
import { pageId } from './pageIdentity'
import { request, sessionHeaders } from './client'
import { useWorkspace } from '../stores/workspace'
import { useAuth } from '../stores/auth'
import type { Router } from 'vue-router'

export const BEFORE_MAINTENANCE = 'scmm-before-maintenance'
export interface BeforeMaintenanceDetail {
  promises: Promise<unknown>[]
}
declare global {
  interface WindowEventMap {
    [BEFORE_MAINTENANCE]: CustomEvent<BeforeMaintenanceDetail>
  }
}

type Control = { key: string; value: string; checked: boolean }
type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
const controlsSelector = 'main input,main select,main textarea'
const draftOwner = '[data-scmm-draft-owner]'
const draftControl = 'input,select,textarea,option'

function namedControls() {
  const counts = new Map<string, number>()
  return Array.from(document.querySelectorAll<Field>(controlsSelector))
    .filter(
      (field) =>
        !['password', 'file'].includes(field.type) && !field.closest('[data-scmm-view-state]'),
    )
    .map((field) => {
      const owner = field.closest(draftOwner)?.getAttribute('data-scmm-draft-owner')
      const name =
        field.getAttribute('aria-label') ||
        field.id ||
        field.closest('label')?.textContent?.trim() ||
        field.tagName
      const prefix = owner ? [owner, name].join('::') : name
      const count = counts.get(prefix) || 0
      counts.set(prefix, count + 1)
      // The legacy first occurrence of these controls belonged to the embedding panel.
      const legacy =
        owner === 'analysis/embedding' &&
        count === 0 &&
        ['random_state', 'store_key'].includes(name)
          ? name + '#0'
          : undefined
      return { field, owner, key: prefix + '#' + count, legacy }
    })
}

export function startMaintenance(router: Router) {
  const tabId = sessionStorage.getItem('scmm-tab-id') || pageId
  sessionStorage.setItem('scmm-tab-id', tabId)
  const store = useWorkspace(),
    auth = useAuth()
  let stopped = false,
    polling = false,
    timer: ReturnType<typeof setTimeout> | undefined,
    nonce = '',
    restored = '',
    working = false,
    observedMaintenance = false,
    reportedRestoration = false
  let restoredForms = false
  const appliedRoutes = new Set<string>()
  let savedRevision = -1,
    formRevision = 0
  const forms: Record<string, Control[]> = {}
  let applied = new WeakSet<Field>()
  let applyingControls = false
  let mayRestoreScoped = false
  let standaloneRestored = ''
  function restoreControls(saved: Control[], scopeOnly = false) {
    const values = new Map(saved.map((v) => [v.key, v]))
    applyingControls = true
    try {
      for (const { field, owner, key, legacy } of namedControls()) {
        if ((scopeOnly && !owner) || (owner && applied.has(field))) continue
        const value = values.get(key) ?? (legacy ? values.get(legacy) : undefined)
        if (!value) continue
        if (
          field instanceof HTMLSelectElement &&
          !Array.from(field.options).some((option) => option.value === value.value)
        )
          continue
        if (owner) applied.add(field)
        const previousValue = field.value
        const previousChecked = field instanceof HTMLInputElement && field.checked
        field.value = value.value
        if (field instanceof HTMLInputElement) field.checked = value.checked
        if (
          field.value === previousValue &&
          (!(field instanceof HTMLInputElement) || field.checked === previousChecked)
        )
          continue
        field.dispatchEvent(new Event('input', { bubbles: true }))
        field.dispatchEvent(new Event('change', { bubbles: true }))
      }
    } finally {
      applyingControls = false
    }
  }
  const capture = (event?: Event) => {
    const route = router.currentRoute.value.path
    if (!auth.user || route === '/account' || applyingControls) return
    const fields = namedControls()
    const scoped = new Map(
      (forms[route] ?? [])
        .filter((value) => value.key.includes('::'))
        .map((value) => [value.key, value]),
    )
    for (const { field, owner, key } of fields) {
      if (owner && field === event?.target) applied.add(field)
      if (owner && !applied.has(field) && mayRestoreScoped && scoped.has(key)) continue
      if (owner)
        scoped.set(key, {
          key,
          value: field.value,
          checked: field instanceof HTMLInputElement && field.checked,
        })
    }
    forms[route] = [
      ...scoped.values(),
      ...fields
        .filter((entry) => !entry.owner)
        .map(({ field, key }) => ({
          key,
          value: field.value,
          checked: field instanceof HTMLInputElement && field.checked,
        })),
    ]
    formRevision++
  }
  const observer = new MutationObserver((records) => {
    const saved = forms[router.currentRoute.value.path]
    if (!mayRestoreScoped || !saved?.length) return
    if (
      records.some((record) =>
        [...record.addedNodes].some(
          (node) =>
            node instanceof Element &&
            (node.matches(draftOwner) ||
              node.querySelector(draftOwner) ||
              (node.closest(draftOwner) &&
                (node.matches(draftControl) || node.querySelector(draftControl)))),
        ),
      )
    )
      restoreControls(saved, true)
  })
  observer.observe(document.body, { childList: true, subtree: true })
  const stopOwner = watch(
    () => JSON.stringify([auth.user?.id, store.current?.workspace_id, store.project?.path]),
    (value, previous) => {
      const scope = JSON.parse(value),
        before = previous ? JSON.parse(previous) : []
      if (scope[0] !== before[0] || scope[1] !== before[1]) restored = ''
      if (scope[0] !== before[0]) standaloneRestored = ''
      applied = new WeakSet<Field>()
      mayRestoreScoped = false
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
  let navigated = false
  const stopNavigation = router.beforeEach((_to, from) => {
    if (from.matched.length) navigated = true
  })
  const unwatch = watch(
    () => router.currentRoute.value.path,
    async () => {
      await nextTick()
      const saved = forms[router.currentRoute.value.path]
      if (saved && mayRestoreScoped) restoreControls(saved, true)
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
    if (polling || stopped) return
    polling = true
    try {
      if (!auth.user || auth.user.must_change) return
      if (!store.current && standaloneRestored !== auth.user.id) {
        standaloneRestored = auth.user.id
        const target = identity(),
          route = router.currentRoute.value.path,
          edits = formRevision
        const value = await request<{ forms?: Record<string, Control[]>; route?: string }>(
          '/maintenance/draft?' + new URLSearchParams({ tab_id: tabId }),
        )
        if (
          identity() === target &&
          formRevision === edits &&
          route === router.currentRoute.value.path &&
          value.route === route &&
          value.forms?.[route]
        ) {
          Object.assign(forms, value.forms)
          mayRestoreScoped = true
          await nextTick()
          if (
            identity() === target &&
            formRevision === edits &&
            route === router.currentRoute.value.path
          )
            restoreControls(value.forms[route])
        }
      }
      if (store.current && restored !== store.current.workspace_id) {
        restored = store.current.workspace_id
        const target = identity(),
          edits = formRevision,
          workspaceRevision = store.current.revision,
          viewsAtRequest = viewRevision()
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
          if (value.views && viewRevision() === viewsAtRequest)
            await restoreViews(value.views, current)
          if (!current()) return
          Object.assign(forms, value.forms)
          mayRestoreScoped = true
          store.analysisDraft = value.analysisDraft || null
          store.selectedCells = value.selectedCells || []
          // Replay the saved page only during initial hydration. Later drafts can still restore form values.
          if (!navigated && value.route && value.route !== router.currentRoute.value.path)
            await router.replace(value.route)
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
      const status = await request<{
        request: { id: string; policy?: string; deadline?: number } | null
        restoration?: { restored: number; failed: number; unavailable: boolean }
      }>('/maintenance/status')
      if (!reportedRestoration && !status.request && status.restoration) {
        reportedRestoration = true
        const recovery = status.restoration
        if (recovery.failed || recovery.unavailable) {
          store.notice = '更新已完成，部分临时状态未能恢复，请重新打开正式保存的项目。'
        } else if (recovery.restored) {
          store.notice = `更新已完成，已恢复你的 ${recovery.restored} 个工作区；未保存内容仍需主动保存。`
        }
      }
      store.maintenancePaused = Boolean(status.request)
      if (status.request) observedMaintenance = true
      if (status.request?.policy === 'deployment') {
        const seconds = Math.max(0, Math.ceil((status.request.deadline || 0) - Date.now() / 1000))
        store.notice =
          seconds > 0
            ? `服务将在 ${seconds} 秒后更新，已暂停新计算；可在顶部保存项目。未保存内容将尽力恢复。`
            : '服务正在更新，请稍候；未恢复的临时内容可从正式保存的项目重新开始。'
      }
      if (observedMaintenance && !status.request) {
        // Reconnect through a fresh document and reload the deployed frontend.
        window.location.reload()
        return
      }
      if (status.request?.id && nonce !== status.request.id && !store.busy && !working) {
        working = true
        try {
          const detail: BeforeMaintenanceDetail = { promises: [] }
          window.dispatchEvent(new CustomEvent(BEFORE_MAINTENANCE, { detail }))
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
          if (status.request.policy !== 'deployment')
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
      polling = false
      if (!stopped) timer = setTimeout(poll, document.hidden && !observedMaintenance ? 8000 : 2000)
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
        views: captureViews(),
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
  const visibility = () => {
    clearTimeout(timer)
    void poll()
  }
  document.addEventListener('visibilitychange', visibility)
  void poll()
  return () => {
    window.removeEventListener('pagehide', suspend)
    document.removeEventListener('visibilitychange', visibility)
    stopped = true
    observer.disconnect()
    clearTimeout(timer)
    unwatch()
    stopOwner()
    stopNavigation()
    document.removeEventListener('input', capture)
    document.removeEventListener('change', capture)
  }
}
