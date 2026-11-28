import { watch, isRef, onUnmounted, nextTick, type Ref } from 'vue'

type Snapshot = Record<string, Record<string, unknown>>
type Entry = {
  refs: Record<string, Ref<unknown>>
  scope: number
  edits: number
  restored: Set<string>
}
const entries = new Map<string, Entry>()
let cached: Snapshot = {}
let pending: Snapshot = {}
let revision = 0
let scope = 0
let generation = 0
let applying = 0
let restorations = 0

export function viewRevision() {
  return revision
}
export let restoringViews = false

export function clearPendingViews() {
  scope++
  generation++
  cached = {}
  pending = {}
  restorations = 0
  restoringViews = false
}

function beginRestoration() {
  const owner = scope
  restorations++
  restoringViews = true
  return () => {
    if (owner === scope) restoringViews = --restorations > 0
  }
}

function snapshot(refs: Entry['refs']): Record<string, unknown> {
  return JSON.parse(
    JSON.stringify(
      Object.fromEntries(Object.entries(refs).map(([name, value]) => [name, value.value])),
    ),
  )
}

export function captureViews() {
  const result = { ...pending, ...cached }
  for (const [key, entry] of entries) if (entry.scope === scope) result[key] = snapshot(entry.refs)
  return result
}

function apply(entry: Entry, saved: Record<string, unknown>) {
  applying++
  try {
    for (const [name, value] of Object.entries(entry.refs)) {
      if (Object.hasOwn(saved, name) && isRef(value)) {
        value.value = saved[name]
        entry.restored.add(name)
      }
    }
  } finally {
    applying--
  }
}

async function restoreEntry(entry: Entry, saved: Record<string, unknown>) {
  const end = beginRestoration()
  try {
    apply(entry, saved)
    await nextTick()
  } finally {
    end()
  }
}

export async function restoreViews(value: Snapshot, isCurrent = () => true) {
  if (!isCurrent()) return
  const token = ++generation
  pending = JSON.parse(JSON.stringify(value)) as Snapshot
  const end = beginRestoration()
  try {
    for (const [key, entry] of entries) {
      const saved = pending[key]
      if (entry.scope === scope && saved) {
        delete pending[key]
        apply(entry, saved)
      }
    }
    await nextTick()
  } finally {
    if (token === generation && !isCurrent()) pending = {}
    end()
  }
}

export function useViewState(key: string, refs: Entry['refs']) {
  const entry: Entry = { refs, scope, edits: 0, restored: new Set() }
  const unwatch = watch(
    Object.values(refs),
    () => {
      if (entry.scope === scope && !applying) {
        entry.edits++
        revision++
      }
    },
    { deep: true, flush: 'sync' },
  )
  entries.set(key, entry)
  const token = generation
  void nextTick(() => {
    if (entry.scope !== scope || token !== generation || entries.get(key) !== entry) return
    const saved = cached[key] ?? pending[key]
    delete cached[key]
    delete pending[key]
    if (saved && entry.edits === 0) void restoreEntry(entry, saved)
  })
  onUnmounted(() => {
    unwatch()
    if (entries.get(key) === entry) {
      if (entry.scope === scope) {
        cached[key] = snapshot(refs)
        delete pending[key]
      }
      entries.delete(key)
    }
  })
  return (initialize: () => void) => {
    const preserve =
      entry.edits > 0
        ? refs
        : Object.fromEntries([...entry.restored].map((name) => [name, refs[name]!]))
    const saved = entry.scope === scope && Object.keys(preserve).length ? snapshot(preserve) : null
    applying++
    try {
      initialize()
      if (saved) void restoreEntry(entry, saved)
    } finally {
      applying--
    }
  }
}
