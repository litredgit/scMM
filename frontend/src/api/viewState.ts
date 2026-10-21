import { watch, isRef, onUnmounted, nextTick, type Ref } from 'vue'
const entries = new Map<string, Record<string, Ref<unknown>>>()
let pending: Record<string, Record<string, unknown>> = {}
let revision = 0
let generation = 0
export function viewRevision() {
  return revision
}
export let restoringViews = false
export function clearPendingViews() {
  generation++
  pending = {}
  restoringViews = false
}
export function captureViews() {
  const result = { ...pending }
  for (const [key, refs] of entries)
    result[key] = Object.fromEntries(
      Object.entries(refs).map(([name, value]) => [name, value.value]),
    )
  return JSON.parse(JSON.stringify(result)) as typeof pending
}
export async function restoreViews(value: typeof pending, isCurrent = () => true) {
  if (!isCurrent()) return
  const token = ++generation
  pending = value
  restoringViews = true
  const current = () => token === generation && isCurrent()
  try {
    if (!current()) return
    for (const [key, refs] of entries) apply(key, refs)
    await nextTick()
    if (!current()) return
    // Dependent watchers can clear plots; restore their recorded values after hydration.
    for (const [key, refs] of entries) apply(key, refs)
    await nextTick()
  } finally {
    if (token === generation) {
      if (!isCurrent()) pending = {}
      restoringViews = false
    }
  }
}
function apply(key: string, refs: Record<string, Ref<unknown>>) {
  const saved = pending[key]
  if (!saved) return
  for (const [name, value] of Object.entries(refs))
    if (Object.hasOwn(saved, name) && isRef(value)) value.value = saved[name]
}
export function useViewState(key: string, refs: Record<string, Ref<unknown>>) {
  const unwatch = watch(Object.values(refs), () => revision++, { deep: true })
  entries.set(key, refs)
  const token = generation
  if (pending[key])
    void nextTick(() => {
      if (token === generation && entries.get(key) === refs) apply(key, refs)
    })
  onUnmounted(() => {
    unwatch()
    entries.delete(key)
  })
}
