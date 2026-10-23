/** One in-flight read across pause/resume; stopping invalidates its publications, not server work. */
export function serialPolling(
  action: (isCurrent: () => boolean) => Promise<unknown>,
  interval: number,
  onError: (cause: unknown) => void,
) {
  let enabled = false
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: Promise<void> | undefined
  let rerun = false
  function schedule() {
    timer = setTimeout(() => void refresh(), interval)
  }
  function refresh(): Promise<void> {
    if (!enabled) return Promise.resolve()
    clearTimeout(timer)
    if (pending) {
      rerun = true
      return pending
    }
    const version = generation
    const isCurrent = () => enabled && version === generation
    const operation = Promise.resolve()
      .then(async () => {
        if (isCurrent()) await action(isCurrent)
      })
      .catch((cause) => {
        if (isCurrent()) onError(cause)
      })
      .finally(() => {
        pending = undefined
        if (!enabled) return
        if (rerun) {
          rerun = false
          void refresh()
        } else schedule()
      })
    pending = operation
    return operation
  }
  function start(immediate = true) {
    if (enabled) return
    enabled = true
    generation++
    if (pending) rerun = immediate
    else if (immediate) void refresh()
    else schedule()
  }
  function stop() {
    enabled = false
    generation++
    rerun = false
    clearTimeout(timer)
  }
  return { start, stop, refresh }
}
