import { watch, onActivated, onDeactivated, onUnmounted } from 'vue'

/** Revision is insufficient for reads whose local input can change or return to an earlier value. */
export function useReadScope(identity: () => unknown, resume?: () => void) {
  let generation = 0
  let active = true
  let resumeNeeded = false
  const key = () => JSON.stringify(identity())
  const invalidate = () => {
    generation++
  }
  watch(key, invalidate, { flush: 'sync' })
  onActivated(() => {
    active = true
    if (resumeNeeded) {
      resumeNeeded = false
      resume?.()
    }
  })
  const stop = () => {
    active = false
    resumeNeeded = true
    invalidate()
  }
  onDeactivated(stop)
  onUnmounted(stop)
  function begin() {
    const token = ++generation
    const source = key()
    return () => active && token === generation && source === key()
  }
  return { begin, invalidate, isActive: () => active }
}
